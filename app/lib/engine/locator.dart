import 'dart:io';

/// How to start the engine: the command plus what it needs in its environment.
class EngineCommand {
  const EngineCommand({
    required this.executable,
    required this.arguments,
    this.environment = const {},
    required this.label,
    this.embedded = false,
  });

  final String executable;
  final List<String> arguments;
  final Map<String, String> environment;

  /// For the log and error messages (`.../python3 (embutido)`).
  final String label;
  final bool embedded;
}

class EngineNotFound implements Exception {
  const EngineNotFound();

  @override
  String toString() => '`auto-edit` não encontrado. Instale o CLI ou aponte AUTO_EDIT_BIN pro executável.';
}

/// The machine the app runs on, injectable for tests.
class Host {
  Host({Map<String, String>? environment, bool? isWindows, bool Function(String path)? isFile, this.repoRoot})
    : environment = environment ?? Platform.environment,
      isWindows = isWindows ?? Platform.isWindows,
      isFile = isFile ?? ((p) => File(p).existsSync());

  final Map<String, String> environment;
  final bool isWindows;
  final bool Function(String path) isFile;

  /// The checkout the app runs from in development (`flutter run`), if any.
  final String? repoRoot;

  String get sep => isWindows ? r'\' : '/';
  String join(List<String> parts) => parts.join(sep);
  String? get home => environment[isWindows ? 'USERPROFILE' : 'HOME'];
}

/// Windows: a path like `\\?\C:\...` breaks the bundled Git bash (it exits 0
/// without running ralph.sh) and would end up in PATH and every variable.
String plainPath(String path) {
  if (path.startsWith(r'\\?\UNC\')) return r'\\' + path.substring(8);
  if (path.startsWith(r'\\?\')) return path.substring(4);
  return path;
}

/// The engine shipped inside the app (scripts/stage_engine.py → `engine/`):
/// a portable Python with auto-edit, the pipeline files and an FFmpeg with
/// libass. Null when the app has none (development), which uses the CLI.
EngineCommand? embeddedEngine(String resourceDir, Host host, {required int port}) {
  final root = host.join([plainPath(resourceDir), 'engine']);
  final python = host.isWindows
      ? host.join([root, 'python', 'python.exe'])
      : host.join([root, 'python', 'bin', 'python3']);
  if (!host.isFile(python)) return null;
  final bin = host.join([root, 'bin']);
  final git = host.join([root, 'git']);
  final home = host.home;
  // ffmpeg/ffprobe from the bundle first, then what the person has (bash, the
  // agent CLIs). Windows: the bundled PortableGit brings bash and coreutils.
  final dirs = [
    bin,
    host.join([git, 'usr', 'bin']),
    host.join([git, 'bin']),
    ...?host.environment['PATH']?.split(host.isWindows ? ';' : ':').where((d) => d.isNotEmpty),
    if (home != null) host.join([home, '.local', 'bin']),
    '/opt/homebrew/bin',
    '/usr/local/bin',
  ];
  return EngineCommand(
    executable: python,
    arguments: ['-m', 'auto_edit.cli', 'serve', '--port', '$port'],
    environment: {
      'PATH': dirs.join(host.isWindows ? ';' : ':'),
      'AUTO_EDIT_REPO_ROOT': host.join([root, 'repo']),
      'AUTO_EDIT_FFMPEG': host.join([bin, host.isWindows ? 'ffmpeg.exe' : 'ffmpeg']),
      'PYTHON': python,
      'PYTHONNOUSERSITE': '1',
      'PYTHONUTF8': '1',
      // Nothing may be written inside the signed app (a new file breaks its
      // seal): .pyc come precompiled, numba caches in the home.
      'PYTHONDONTWRITEBYTECODE': '1',
      if (home != null) 'NUMBA_CACHE_DIR': host.join([home, '.auto-edit', 'cache', 'numba']),
    },
    label: '$python (embutido)',
    embedded: true,
  );
}

/// Where an installed `auto-edit` usually is, in the order they are tried.
/// An app opened from the Dock/Finder doesn't inherit the shell's PATH.
List<String> installedCandidates(Host host) {
  final exe = host.isWindows ? 'auto-edit.exe' : 'auto-edit';
  final home = host.home;
  return [
    if (host.repoRoot != null) host.join([host.repoRoot!, '.venv', host.isWindows ? 'Scripts' : 'bin', exe]),
    if (home != null) host.join([home, '.local', 'bin', exe]), // uv tool / pipx
    if (home != null) host.join([home, '.nix-profile', 'bin', exe]),
    if (!host.isWindows) ...['/opt/homebrew/bin/$exe', '/usr/local/bin/$exe'],
  ];
}

/// Asks the login shell (Unix) or `where` (Windows) for `auto-edit`.
Future<String?> lookupInShell(Host host) async {
  try {
    final ProcessResult out;
    if (host.isWindows) {
      out = await Process.run('where', ['auto-edit']);
    } else {
      out = await Process.run(host.environment['SHELL'] ?? '/bin/zsh', ['-lc', 'command -v auto-edit']);
    }
    final lines = '${out.stdout}'.trim().split(RegExp(r'\r?\n')).where((l) => l.trim().isNotEmpty);
    if (lines.isEmpty) return null;
    final path = (host.isWindows ? lines.first : lines.last).trim();
    return host.isFile(path) ? path : null;
  } on ProcessException {
    return null;
  }
}

/// The command that starts the engine: the embedded one when the app has it,
/// else the installed CLI (`AUTO_EDIT_BIN`, the usual spots, the shell).
Future<EngineCommand> resolveEngine(Host host, {String? resourceDir, required int port}) async {
  if (resourceDir != null) {
    final embedded = embeddedEngine(resourceDir, host, port: port);
    if (embedded != null) return embedded;
  }
  var bin = host.environment['AUTO_EDIT_BIN'];
  if (bin == null || bin.isEmpty) {
    bin = installedCandidates(host).where(host.isFile).firstOrNull ?? await lookupInShell(host);
  }
  if (bin == null) throw const EngineNotFound();
  return EngineCommand(
    executable: bin,
    arguments: ['serve', '--port', '$port'],
    // stdout goes to engine.log, not a console: without this Windows encodes
    // it as cp1252 and the engine dies on its first "→".
    environment: const {'PYTHONUTF8': '1'},
    label: bin,
  );
}

/// The checkout above [from] (a folder with `ralph.sh` and `auto_edit/`), if any.
String? findRepoRoot(Iterable<String> from) {
  for (final start in from) {
    var dir = Directory(start).absolute;
    for (var i = 0; i < 12; i++) {
      if (File('${dir.path}/ralph.sh').existsSync() && Directory('${dir.path}/auto_edit').existsSync()) {
        return dir.path;
      }
      final parent = dir.parent;
      if (parent.path == dir.path) break;
      dir = parent;
    }
  }
  return null;
}

/// Where the app keeps its bundled resources: `Contents/Resources` in the
/// macOS bundle, next to the executable on Windows and Linux.
String resourceDir() {
  final exeDir = File(Platform.resolvedExecutable).parent;
  return Platform.isMacOS ? '${exeDir.parent.path}/Resources' : exeDir.path;
}

/// Where the engine runs. `serve` keeps its library in `<cwd>/workspace`
/// (unless AUTO_EDIT_WORKSPACE says otherwise): the checkout in development,
/// so the app sees the CLI's workspaces; `~/.auto-edit` in an installed app.
String engineWorkingDirectory(Host host, {required bool development}) {
  final forced = host.environment['AUTO_EDIT_CWD'];
  if (forced != null && forced.isNotEmpty) return forced;
  if (development && host.repoRoot != null) return host.repoRoot!;
  final home =
      host.environment['AUTO_EDIT_HOME'] ??
      (host.home != null ? host.join([host.home!, '.auto-edit']) : Directory.systemTemp.path);
  Directory(home).createSync(recursive: true);
  return home;
}

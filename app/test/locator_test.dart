import 'dart:io';

import 'package:auto_edit/engine/locator.dart';
import 'package:flutter_test/flutter_test.dart';

Host unix({Map<String, String> env = const {}, Set<String> files = const {}, String? repo}) => Host(
  environment: {'HOME': '/home/ana', 'PATH': '/usr/bin:/bin', ...env},
  isWindows: false,
  isFile: files.contains,
  repoRoot: repo,
);

void main() {
  group('installed CLI', () {
    test('tries the checkout venv, ~/.local, nix, Homebrew, /usr/local — in that order', () {
      expect(installedCandidates(unix(repo: '/src/auto-edit-video')), [
        '/src/auto-edit-video/.venv/bin/auto-edit',
        '/home/ana/.local/bin/auto-edit',
        '/home/ana/.nix-profile/bin/auto-edit',
        '/opt/homebrew/bin/auto-edit',
        '/usr/local/bin/auto-edit',
      ]);
    });

    test('Windows uses Scripts and .exe', () {
      final host = Host(
        environment: {'USERPROFILE': r'C:\Users\ana'},
        isWindows: true,
        isFile: (_) => false,
        repoRoot: r'C:\src',
      );
      expect(installedCandidates(host), [
        r'C:\src\.venv\Scripts\auto-edit.exe',
        r'C:\Users\ana\.local\bin\auto-edit.exe',
        r'C:\Users\ana\.nix-profile\bin\auto-edit.exe',
      ]);
    });

    test('AUTO_EDIT_BIN wins over everything installed', () async {
      final host = unix(env: {'AUTO_EDIT_BIN': '/opt/ae/auto-edit'}, files: {'/home/ana/.local/bin/auto-edit'});
      final cmd = await resolveEngine(host, port: 8760);
      expect(cmd.executable, '/opt/ae/auto-edit');
      expect(cmd.arguments, ['serve', '--port', '8760']);
      expect(cmd.environment['PYTHONUTF8'], '1');
    });

    test('the first candidate that exists', () async {
      final host = unix(files: {'/usr/local/bin/auto-edit', '/home/ana/.local/bin/auto-edit'});
      expect((await resolveEngine(host, port: 9000)).executable, '/home/ana/.local/bin/auto-edit');
    });
  });

  group('embedded engine', () {
    test('found next to the app, with its PATH and variables', () {
      final host = unix(files: {'/app/engine/python/bin/python3'});
      final cmd = embeddedEngine('/app', host, port: 8760)!;
      expect(cmd.embedded, isTrue);
      expect(cmd.executable, '/app/engine/python/bin/python3');
      expect(cmd.arguments, ['-m', 'auto_edit.cli', 'serve', '--port', '8760']);
      expect(cmd.environment['PATH']!.split(':').take(3), [
        '/app/engine/bin',
        '/app/engine/git/usr/bin',
        '/app/engine/git/bin',
      ]);
      expect(cmd.environment['PATH'], contains('/usr/bin:/bin'));
      expect(cmd.environment['AUTO_EDIT_REPO_ROOT'], '/app/engine/repo');
      expect(cmd.environment['AUTO_EDIT_FFMPEG'], '/app/engine/bin/ffmpeg');
      expect(cmd.environment['PYTHONDONTWRITEBYTECODE'], '1');
      expect(cmd.environment['NUMBA_CACHE_DIR'], '/home/ana/.auto-edit/cache/numba');
    });

    test('preferred over the installed CLI', () async {
      final host = unix(env: {'AUTO_EDIT_BIN': '/x/auto-edit'}, files: {'/app/engine/python/bin/python3'});
      expect((await resolveEngine(host, resourceDir: '/app', port: 8760)).embedded, isTrue);
    });

    test('absent: null', () => expect(embeddedEngine('/app', unix(), port: 8760), isNull));

    test(r'Windows drops the \\?\ prefix', () {
      final host = Host(
        environment: {'PATH': r'C:\Windows'},
        isWindows: true,
        isFile: (p) => p == r'C:\Program Files\Auto-Edit\engine\python\python.exe',
      );
      final cmd = embeddedEngine(r'\\?\C:\Program Files\Auto-Edit', host, port: 8760)!;
      expect(cmd.executable, r'C:\Program Files\Auto-Edit\engine\python\python.exe');
      expect(cmd.environment['PATH']!.split(';').first, r'C:\Program Files\Auto-Edit\engine\bin');
      expect(cmd.environment['AUTO_EDIT_FFMPEG'], endsWith('ffmpeg.exe'));
    });
  });

  test('plainPath', () {
    expect(plainPath(r'\\?\C:\a'), r'C:\a');
    expect(plainPath(r'\\?\UNC\server\share'), r'\\server\share');
    expect(plainPath('/usr/bin'), '/usr/bin');
  });

  group('working directory', () {
    test('AUTO_EDIT_CWD, then the checkout in development', () {
      expect(engineWorkingDirectory(unix(env: {'AUTO_EDIT_CWD': '/w'}, repo: '/src'), development: true), '/w');
      expect(engineWorkingDirectory(unix(repo: '/src'), development: true), '/src');
    });

    test('installed: AUTO_EDIT_HOME (created)', () {
      final tmp = Directory.systemTemp.createTempSync('ae_home');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final dir = '${tmp.path}/perfil';
      expect(engineWorkingDirectory(unix(env: {'AUTO_EDIT_HOME': dir}, repo: '/src'), development: false), dir);
      expect(Directory(dir).existsSync(), isTrue);
    });
  });

  test('findRepoRoot walks up to the checkout', () {
    final tmp = Directory.systemTemp.createTempSync('ae_repo');
    addTearDown(() => tmp.deleteSync(recursive: true));
    File('${tmp.path}/ralph.sh').createSync();
    Directory('${tmp.path}/auto_edit').createSync();
    final deep = Directory('${tmp.path}/app/build/linux')..createSync(recursive: true);
    expect(findRepoRoot([deep.path]), tmp.absolute.path);
    expect(findRepoRoot([Directory.systemTemp.path]), isNull);
  });
}

import 'dart:async';
import 'dart:io';

import 'locator.dart';

/// What [EngineSupervisor.start] did.
enum EngineStart {
  /// Something already listened on the port (`auto-edit serve` run by hand):
  /// reused and left alone.
  reused,

  /// This app started it; it dies with the app.
  started,
}

/// The engine process behind the app (port of the Tauri shell's main.rs).
///
/// On [start] it reuses an engine already listening on [port], else starts
/// one with its output in `<logDir>/engine.log`. [stop] kills only the one
/// it started. [restart] (the sidebar's "Reiniciar o motor") moves the log to
/// `engine.prev.log`, to see why it hung.
class EngineSupervisor {
  EngineSupervisor({
    required this.logDir,
    required this.resolve,
    required this.workingDirectory,
    this.port = 8760,
    this.host = '127.0.0.1',
  });

  final String logDir;
  final int port;
  final String host;

  /// Finds the command each time it starts (an install in between counts).
  final Future<EngineCommand> Function(int port) resolve;
  final String Function() workingDirectory;

  Process? _process;
  IOSink? _log;

  /// Whether the running engine is one this app started (so it may kill it).
  bool get ownsEngine => _process != null;

  String get logPath => '$logDir${Platform.pathSeparator}engine.log';
  String get previousLogPath => '$logDir${Platform.pathSeparator}engine.prev.log';

  Future<bool> listening() async {
    try {
      final socket = await Socket.connect(host, port, timeout: const Duration(milliseconds: 300));
      socket.destroy();
      return true;
    } on SocketException {
      return false;
    }
  }

  Future<EngineStart> start() async {
    if (await listening()) return EngineStart.reused;
    await _spawn();
    return EngineStart.started;
  }

  Future<void> _spawn() async {
    final command = await resolve(port);
    await Directory(logDir).create(recursive: true);
    final log = File(logPath).openWrite();
    final cwd = workingDirectory();
    final Process process;
    try {
      process = await Process.start(
        command.executable,
        command.arguments,
        workingDirectory: cwd,
        environment: command.environment,
      );
    } on ProcessException catch (e) {
      await log.close();
      throw EngineStartFailed('${command.label}: ${e.message}');
    }
    _process = process;
    _log = log;
    log.writeln('[auto-edit] engine started: ${command.label} ${command.arguments.join(' ')} (cwd: $cwd)');
    process.stdout.listen(log.add);
    process.stderr.listen(log.add);
    unawaited(
      process.exitCode.then((code) {
        if (identical(_process, process)) {
          log.writeln('[auto-edit] engine exited with $code');
          _process = null;
        }
      }),
    );
  }

  /// Kills the engine this app started (nothing if it reused one).
  Future<void> stop() async {
    final process = _process;
    _process = null;
    if (process != null) {
      process.kill();
      await process.exitCode.timeout(
        const Duration(seconds: 5),
        onTimeout: () {
          process.kill(ProcessSignal.sigkill);
          return -1;
        },
      );
    }
    await _log?.flush();
    await _log?.close();
    _log = null;
  }

  /// Stops ours and starts a fresh one. Throws [EngineBusy] when the port is
  /// held by an engine this app didn't start (that one isn't ours to kill).
  Future<void> restart() async {
    await stop();
    for (var i = 0; i < 20 && await listening(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 150));
    }
    if (await listening()) throw const EngineBusy();
    final log = File(logPath);
    if (log.existsSync()) log.renameSync(previousLogPath);
    await _spawn();
  }
}

class EngineBusy implements Exception {
  const EngineBusy();

  @override
  String toString() =>
      'Outro motor, que não foi aberto pelo app, está usando a porta 8760. '
      'Feche-o (o terminal com auto-edit serve) e tente de novo.';
}

class EngineStartFailed implements Exception {
  const EngineStartFailed(this.message);
  final String message;

  @override
  String toString() => message;
}

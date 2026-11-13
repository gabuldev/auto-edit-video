@TestOn('!windows')
library;

import 'dart:io';

import 'package:auto_edit/engine/locator.dart';
import 'package:auto_edit/engine/supervisor.dart';
import 'package:flutter_test/flutter_test.dart';

/// A stand-in engine: prints a line and serves HTTP on the port it's given
/// (`serve --port N`), like `auto-edit serve`.
const fakeEngine = r'''#!/bin/sh
echo "fake engine on $3"
exec python3 -m http.server "$3" --bind 127.0.0.1
''';

Future<int> freePort() async {
  final s = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
  final port = s.port;
  await s.close();
  return port;
}

Future<void> until(Future<bool> Function() ok) async {
  for (var i = 0; i < 100; i++) {
    if (await ok()) return;
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
  fail('timed out');
}

void main() {
  late Directory tmp;
  late String script;
  late int port;

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('ae_sup');
    script = '${tmp.path}/auto-edit';
    File(script).writeAsStringSync(fakeEngine);
    await Process.run('chmod', ['+x', script]);
    port = await freePort();
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  EngineSupervisor supervisor() => EngineSupervisor(
    logDir: '${tmp.path}/logs',
    port: port,
    resolve: (p) async => EngineCommand(executable: script, arguments: ['serve', '--port', '$p'], label: script),
    workingDirectory: () => tmp.path,
  );

  test('starts the engine, logs it and kills it on stop', () async {
    final sup = supervisor();
    expect(await sup.start(), EngineStart.started);
    expect(sup.ownsEngine, isTrue);
    await until(sup.listening);
    await sup.stop();
    expect(await sup.listening(), isFalse);
    final log = File(sup.logPath).readAsStringSync();
    expect(log, contains('engine started: $script serve --port $port'));
    expect(log, contains('fake engine on $port'));
  });

  test('reuses an engine already on the port and never kills it', () async {
    final other = await ServerSocket.bind(InternetAddress.loopbackIPv4, port);
    addTearDown(other.close);
    other.listen((s) => s.destroy());
    final sup = supervisor();
    expect(await sup.start(), EngineStart.reused);
    expect(sup.ownsEngine, isFalse);
    await sup.stop();
    expect(await sup.listening(), isTrue);
  });

  test('restart keeps the old log as engine.prev.log', () async {
    final sup = supervisor();
    await sup.start();
    await until(sup.listening);
    await sup.restart();
    await until(sup.listening);
    expect(File(sup.previousLogPath).readAsStringSync(), contains('fake engine'));
    expect(File(sup.logPath).existsSync(), isTrue);
    await sup.stop();
  });

  test('restart refuses when someone else holds the port', () async {
    final other = await ServerSocket.bind(InternetAddress.loopbackIPv4, port);
    addTearDown(other.close);
    other.listen((s) => s.destroy());
    final sup = supervisor();
    await expectLater(sup.restart(), throwsA(isA<EngineBusy>()));
  });

  test('a missing executable is EngineStartFailed', () async {
    final sup = EngineSupervisor(
      logDir: '${tmp.path}/logs',
      port: port,
      resolve: (p) async => const EngineCommand(executable: '/nope/auto-edit', arguments: [], label: '/nope/auto-edit'),
      workingDirectory: () => tmp.path,
    );
    await expectLater(sup.start(), throwsA(isA<EngineStartFailed>()));
  });
}

// The real thing: resolveEngine finds `auto-edit`, the supervisor starts it
// and the client gets its health. Runs when AUTO_EDIT_BIN points at one
// (the CI does); skipped otherwise.
@TestOn('!windows')
library;

import 'dart:io';

import 'package:auto_edit/engine/locator.dart';
import 'package:auto_edit/engine/supervisor.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final bin = Platform.environment['AUTO_EDIT_BIN'];

  test(
    'starts auto-edit serve and gets its health',
    () async {
      final tmp = Directory.systemTemp.createTempSync('ae_engine');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final s = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
      final port = s.port;
      await s.close();

      final host = Host(
        environment: {
          ...Platform.environment,
          'AUTO_EDIT_WORKSPACE': '${tmp.path}/ws',
          'AUTO_EDIT_HOME': '${tmp.path}/home',
          'AUTO_EDIT_INBOX': '${tmp.path}/inbox',
          'AUTO_EDIT_OUTPUT': '${tmp.path}/out',
        },
      );
      final sup = EngineSupervisor(
        logDir: '${tmp.path}/logs',
        port: port,
        resolve: (p) => resolveEngine(host, port: p),
        workingDirectory: () => engineWorkingDirectory(host, development: false),
      );
      final client = AutoEditClient(EngineConfig.local(port: port));
      addTearDown(() async {
        client.close();
        await sup.stop();
      });

      expect(await sup.start(), EngineStart.started);
      Health? health;
      for (var i = 0; i < 100 && health == null; i++) {
        try {
          health = await client.api.health();
        } catch (_) {
          await Future<void>.delayed(const Duration(milliseconds: 200));
        }
      }
      expect(health, isNotNull, reason: File(sup.logPath).readAsStringSync());
      expect(health!.apiVersion.split('.').first, AutoEditApi.contractVersion.split('.').first);
      expect((await client.api.listLibrary()).videos, isEmpty);

      await sup.stop();
      expect(await sup.listening(), isFalse);
    },
    skip: bin == null ? 'AUTO_EDIT_BIN not set' : false,
    timeout: const Timeout(Duration(minutes: 1)),
  );
}

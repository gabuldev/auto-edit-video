import 'dart:convert';

import 'package:auto_edit/engine/status.dart';
import 'package:auto_edit/main.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const healthBody = {'ok': true, 'api_version': '1.0.0', 'version': '0.48.0', 'repo_root': '/src/auto-edit-video'};

AutoEditClient fakeEngine(bool Function() up) {
  final config = EngineConfig.local();
  final client = MockClient((req) async {
    if (!up()) throw http.ClientException('connection refused');
    return http.Response(jsonEncode(healthBody), 200);
  });
  return AutoEditClient(config, transport: Transport(config, client: client));
}

void main() {
  setUp(() {
    // a desktop window, not the 800x600 default
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1280, 800);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  testWidgets('boot screen until the engine answers, then the shell with its health', (tester) async {
    var up = false;
    await tester.pumpWidget(AutoEditApp(client: fakeEngine(() => up)));
    await tester.pump();
    expect(find.text('Iniciando o motor…'), findsOneWidget);

    up = true;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('Motor conectado'), findsOneWidget);
    expect(find.text('0.48.0'), findsOneWidget);
    expect(find.text('1.0.0 (este app: ${AutoEditApi.contractVersion})'), findsOneWidget);
    expect(find.text('Edições'), findsWidgets);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('engine stops answering: offline banner, then back', (tester) async {
    var up = true;
    await tester.pumpWidget(AutoEditApp(client: fakeEngine(() => up)));
    await tester.pump();
    await tester.pump();
    expect(find.text('Motor conectado'), findsOneWidget);

    up = false;
    await tester.pump(const Duration(seconds: 6));
    await tester.pump();
    expect(find.text('Motor sem resposta'), findsOneWidget);
    expect(find.textContaining('Motor offline'), findsOneWidget);
    // Without an engine the app started, there is nothing to restart.
    expect(find.text('Rode auto-edit serve no terminal.'), findsOneWidget);

    up = true;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('Motor conectado'), findsOneWidget);
    expect(find.textContaining('Motor offline'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('the sidebar switches sections', (tester) async {
    await tester.pumpWidget(AutoEditApp(client: fakeEngine(() => true)));
    await tester.pump();
    await tester.pump();
    await tester.tap(find.text('Configurações'));
    await tester.pump();
    expect(find.textContaining('#138'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  group('EngineStatus', () {
    test('offers the restart only after restartAfter and only when it can', () async {
      var now = DateTime(2026);
      final status = EngineStatus(
        health: () async => throw Exception('down'),
        onRestart: () async {},
        restartAfter: const Duration(seconds: 10),
        offInterval: const Duration(hours: 1),
        clock: () => now,
      );
      addTearDown(status.dispose);
      await status.check();
      expect(status.ok, isFalse);
      expect(status.stuck, isFalse);
      now = now.add(const Duration(seconds: 11));
      expect(status.stuck, isTrue);
      expect(status.canRestart, isTrue);
    });

    test('a failed restart shows why', () async {
      final status = EngineStatus(
        health: () async => throw Exception('down'),
        onRestart: () async => throw Exception('porta ocupada'),
        offInterval: const Duration(hours: 1),
      );
      addTearDown(status.dispose);
      await status.restart();
      expect(status.restarting, isFalse);
      expect(status.error, contains('porta ocupada'));
    });
  });
}

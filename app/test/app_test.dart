import 'package:auto_edit/engine/status.dart';
import 'package:auto_edit/main.dart';
import 'package:auto_edit/platform.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';

/// A machine already set up: an agent tested, Whisper downloaded.
FakeEngine readyEngine() => FakeEngine()
  ..verifiedAgent = 'claude'
  ..whisper = {'model': 'small', 'ready': true, 'downloading': false, 'progress': 1.0, 'size_mb': 466, 'error': null};

Widget app(FakeEngine engine, {AppPrefs? prefs}) =>
    AutoEditApp(client: engine.client(), prefs: prefs ?? AppPrefs.memory());

void main() {
  setUp(() {
    // a desktop window, not the 800x600 default
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1280, 800);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  testWidgets('boot screen until the engine answers, then the shell with its health', (tester) async {
    final engine = readyEngine()..up = false;
    await tester.pumpWidget(app(engine));
    await tester.pump();
    expect(find.text('Iniciando o motor…'), findsOneWidget);

    engine.up = true;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('Motor conectado'), findsOneWidget);
    expect(find.text('Edições'), findsWidgets);
    // Which engine: at the end of Configurações.
    await tester.tap(find.text('Configurações'));
    await tester.pump();
    await tester.pump();
    await tester.scrollUntilVisible(
      find.text('0.48.0'),
      300,
      scrollable: find.ancestor(of: find.text('Pastas'), matching: find.byType(Scrollable)).first,
    );
    expect(find.text('1.1.0 (este app: ${AutoEditApi.contractVersion})'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('engine stops answering: offline banner, then back', (tester) async {
    final engine = readyEngine();
    await tester.pumpWidget(app(engine));
    await tester.pump();
    await tester.pump();
    expect(find.text('Motor conectado'), findsOneWidget);

    engine.up = false;
    await tester.pump(const Duration(seconds: 6));
    await tester.pump();
    expect(find.text('Motor sem resposta'), findsOneWidget);
    expect(find.textContaining('Motor offline'), findsOneWidget);
    // Without an engine the app started, there is nothing to restart.
    expect(find.text('Rode auto-edit serve no terminal.'), findsOneWidget);

    engine.up = true;
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(find.text('Motor conectado'), findsOneWidget);
    expect(find.textContaining('Motor offline'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('the sidebar switches sections', (tester) async {
    await tester.pumpWidget(app(readyEngine()));
    await tester.pump();
    await tester.pump();
    await tester.tap(find.text('Biblioteca'));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Nenhum vídeo nesta pasta'), findsOneWidget);
    await tester.tap(find.text('Estilos'));
    await tester.pump();
    expect(find.text('Importar estilo'), findsOneWidget);
    await tester.tap(find.text('Configurações'));
    await tester.pump();
    await tester.pump();
    expect(find.text('Agente de IA, contas e padrões das edições'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  group('first run', () {
    testWidgets('a machine that cannot edit yet opens on the welcome screen', (tester) async {
      await tester.pumpWidget(app(FakeEngine()));
      await tester.pump();
      await tester.pump();
      await tester.pump();
      expect(find.text('Vamos deixar o Auto-Edit pronto'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('"configurar depois": remembered, and a banner in Edições says what is missing', (tester) async {
      final prefs = AppPrefs.memory();
      await tester.pumpWidget(app(FakeEngine(), prefs: prefs));
      await tester.pump();
      await tester.pump();
      await tester.pump();
      await tester.tap(find.text('configurar depois'));
      await tester.pump();
      await tester.pump();
      expect(prefs.setupLater, isTrue);
      expect(find.text('Vamos deixar o Auto-Edit pronto'), findsNothing);
      expect(find.text('Falta um agente de IA funcionando e o modelo de transcrição.'), findsOneWidget);

      // Next launch: straight to Edições, the banner leads back.
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(app(FakeEngine(), prefs: prefs));
      await tester.pump();
      await tester.pump();
      await tester.pump();
      expect(find.text('Vamos deixar o Auto-Edit pronto'), findsNothing);
      await tester.tap(find.text('Configurar'));
      await tester.pump();
      await tester.pump();
      expect(find.text('Vamos deixar o Auto-Edit pronto'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });
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

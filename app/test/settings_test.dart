import 'dart:convert';

import 'package:auto_edit/ui/settings/settings_screen.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:auto_edit/ui/welcome.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';

const debounce = Duration(milliseconds: 10);

Future<void> settle(WidgetTester tester) async {
  // Enough for the debounce, the fake engine and an ExpansionTile opening.
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

Widget host(Widget child) => MaterialApp(
  theme: buildTheme(),
  home: Scaffold(body: child),
);

void main() {
  setUp(() {
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1280, 3000); // the whole screen, no scrolling
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  group('Configurações', () {
    late FakeEngine engine;
    late FakePickers pickers;

    Future<void> open(WidgetTester tester) async {
      await tester.pumpWidget(host(SettingsScreen(client: engine.client(), pickers: pickers, debounce: debounce)));
      await settle(tester);
    }

    setUp(() {
      engine = FakeEngine();
      pickers = FakePickers();
    });

    testWidgets('lists the agents with what each needs', (tester) async {
      await open(tester);
      expect(find.text('Claude Code'), findsOneWidget);
      expect(find.text('principal'), findsOneWidget);
      expect(find.text('2.1 (Claude Code)'), findsOneWidget);
      expect(find.text('sem chave da API'), findsOneWidget); // OpenRouter
      expect(find.text('Ollama (local)'), findsWidgets);
      expect(find.text('Ollama não instalado — ollama.com'), findsOneWidget);
    });

    testWidgets('choosing the primary saves itself', (tester) async {
      await open(tester);
      await tester.tap(find.byWidgetPredicate((w) => w is Radio<String> && w.value == 'cursor'));
      await settle(tester);
      expect(engine.settingsPuts, hasLength(1));
      final put = engine.settingsPuts.single;
      expect((put['agent'] as Map)['primary'], 'cursor');
      // Only what this screen edits: verified_agent, the brand and the style change elsewhere.
      expect(put.keys, unorderedEquals(['agent', 'language', 'whisper_model', 'cold_open', 'reorder']));
      expect(find.text('Salvo'), findsOneWidget);
    });

    testWidgets('"sem fallback" sends the null that clears it', (tester) async {
      engine.settings = {
        ...engine.settings,
        'agent': {'primary': 'claude', 'fallback': 'cursor', 'models': <String, Object?>{}},
      };
      await open(tester);
      expect(find.text('fallback'), findsOneWidget);
      await tester.tap(find.text('Cursor Agent').last); // the dropdown
      await settle(tester);
      await tester.tap(find.text('sem fallback').last);
      await settle(tester);
      final agent = engine.settingsPuts.last['agent'] as Map;
      expect(agent.containsKey('fallback'), isTrue);
      expect(agent['fallback'], isNull);
    });

    testWidgets('a model typed is saved once, after the last key', (tester) async {
      await open(tester);
      await tester.enterText(find.byType(TextField).first, 'claude-sonnet-5-5');
      await settle(tester);
      expect(engine.settingsPuts, hasLength(1));
      expect(((engine.settingsPuts.single['agent'] as Map)['models'] as Map)['claude'], 'claude-sonnet-5-5');
    });

    testWidgets('Testar shows how long it took', (tester) async {
      await open(tester);
      await tester.tap(find.text('Testar').first);
      await settle(tester);
      expect(find.text('✓ respondeu em 2,4s'), findsOneWidget);
      expect(engine.calls, contains('POST /api/agents/claude/test'));
    });

    testWidgets('a failed test shows the error and what it answered', (tester) async {
      engine.testResult = (name) => {'name': name, 'ok': false, 'seconds': 1.0, 'error': 'não logado', 'answer': 'oi'};
      await open(tester);
      await tester.tap(find.text('Testar').first);
      await settle(tester);
      expect(find.text('✗ não logado\nresposta: oi'), findsOneWidget);
    });

    testWidgets('OpenRouter: the key is saved and only its hint comes back', (tester) async {
      await open(tester);
      await tester.enterText(find.widgetWithText(TextField, 'cole a chave: sk-or-…'), 'sk-or-v1-secret');
      await tester.tap(find.text('Salvar chave'));
      await settle(tester);
      expect(engine.calls, contains('PUT /api/agents/openrouter/key'));
      expect(find.textContaining('sk-or-…abcd'), findsOneWidget);
      expect(find.text('✓ chave salva — clique em Testar'), findsOneWidget);
    });

    testWidgets('folders: Trocar saves the one picked, "usar a padrão" clears it', (tester) async {
      await open(tester);
      expect(find.text('/src/auto-edit-video/workspace/input'), findsOneWidget);
      pickers.nextFolder = '/home/me/Gravações';
      await tester.tap(find.text('Trocar').first);
      await settle(tester);
      expect(engine.settingsPuts.last, {'inbox': '/home/me/Gravações'});
      expect(find.text('/home/me/Gravações'), findsOneWidget);

      await tester.tap(find.text('usar a padrão'));
      await settle(tester);
      expect(engine.settingsPuts.last, {'inbox': null});
      expect(find.text('/src/auto-edit-video/workspace/input'), findsOneWidget);

      await tester.tap(find.byTooltip('Abrir a pasta').first);
      await settle(tester);
      expect(engine.calls, contains('POST /api/folders/inbox/open'));
    });

    testWidgets('YouTube: the guide is open until there is a credential, then Conectar', (tester) async {
      await open(tester);
      expect(find.textContaining('Não configurado'), findsOneWidget);
      expect(find.textContaining('Crie um projeto'), findsOneWidget);
      final connect = find.widgetWithText(OutlinedButton, 'Conectar YouTube');
      expect(tester.widget<OutlinedButton>(connect).onPressed, isNull);

      pickers.nextJson = '{"installed": {"client_id": "123"}}';
      await tester.tap(find.text('Escolher arquivo JSON'));
      await settle(tester);
      expect(engine.calls, contains('PUT /api/publish/youtube/client'));
      expect(find.text('Não conectado'), findsOneWidget);
      expect(find.textContaining('123-abc.apps.googleusercontent.com'), findsOneWidget);

      await tester.tap(find.widgetWithText(FilledButton, 'Conectar YouTube'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/publish/youtube/connect'));
      expect(find.textContaining('Aguardando você autorizar'), findsOneWidget);
      expect(find.text('Cancelar'), findsOneWidget);
      await tester.pumpWidget(const SizedBox()); // stops following the consent
    });

    testWidgets('a guide link opens through the engine', (tester) async {
      await open(tester);
      await tester.tapOnText(find.textRange.ofSubstring('Abrir o Google Cloud'));
      await settle(tester);
      final opened = engine.requests.where((r) => r.url.path == '/api/open-url').single;
      expect(opened.body, contains('console.cloud.google.com/projectcreate'));
    });

    testWidgets('the defaults of a new edit', (tester) async {
      await open(tester);
      await tester.tap(find.text('Cold open — abrir com o melhor momento'));
      await settle(tester);
      expect(engine.settingsPuts.last['cold_open'], isFalse);
    });
  });

  group('Boas-vindas', () {
    late FakeEngine engine;

    Future<void> open(WidgetTester tester, {VoidCallback? onDone}) async {
      await tester.pumpWidget(
        host(
          WelcomeScreen(
            client: engine.client(),
            onDone: onDone ?? () {},
            onLater: () {},
            every: const Duration(milliseconds: 50),
          ),
        ),
      );
      await settle(tester);
    }

    setUp(() => engine = FakeEngine());

    testWidgets('Claude first: Testar makes it the agent, then the Whisper', (tester) async {
      var done = false;
      await open(tester, onDone: () => done = true);
      expect(find.text('pendente'), findsNWidgets(2));
      expect(find.text('Claude Code'), findsOneWidget);
      expect(find.text('recomendado'), findsOneWidget);
      final start = find.widgetWithText(FilledButton, 'Começar a editar');
      expect(tester.widget<FilledButton>(start).onPressed, isNull);

      await tester.tap(find.text('Testar'));
      await settle(tester);
      expect(find.textContaining('este agente vai editar seus vídeos'), findsOneWidget);
      expect(find.text('✓ funcionando'), findsOneWidget);
      expect(find.text('pronto'), findsOneWidget);

      await tester.tap(find.text('Baixar'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/setup/whisper'));
      expect(find.text('baixando'), findsOneWidget);
      expect(find.text('25%'), findsOneWidget);

      // The download ends while the screen keeps checking.
      engine.whisper = {...engine.whisper, 'ready': true, 'downloading': false, 'progress': 1.0};
      await tester.pump(const Duration(milliseconds: 60));
      await settle(tester);
      expect(find.text('pronto'), findsNWidgets(2));
      await tester.tap(start);
      expect(done, isTrue);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('other agents: install opens the terminal, the note says what next', (tester) async {
      await open(tester);
      await tester.tap(find.textContaining('Usar outro agente'));
      await settle(tester);
      await tester.tap(find.text('Instalar').first); // Codex
      await settle(tester);
      expect(engine.calls, contains('POST /api/agents/codex/install'));
      expect(find.textContaining('Abri o Terminal com o instalador oficial'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    test('what is missing, in words', () {
      final e = FakeEngine();
      String? missing() => missingForSetup(Setup.fromJson(jsonDecode(jsonEncode(e.setup)) as Map<String, Object?>));
      expect(missing(), 'Falta um agente de IA funcionando e o modelo de transcrição.');
      e.verifiedAgent = 'claude';
      expect(missing(), 'Falta o modelo de transcrição.');
      e.whisper = {...e.whisper, 'ready': true};
      expect(missing(), isNull);
    });
  });
}

import 'dart:convert';
import 'dart:typed_data';

import 'package:auto_edit/ui/player.dart';
import 'package:auto_edit/ui/shorts_screen.dart';
import 'package:auto_edit/ui/styles/styles_controller.dart';
import 'package:auto_edit/ui/styles/styles_screen.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

final played = <PlayerSource>[];

Widget host(Widget child) => MaterialApp(
  theme: buildTheme(),
  home: PlayerScope(
    builder: (context, s) {
      played.add(s);
      return const ColoredBox(color: Colors.black);
    },
    child: Scaffold(body: child),
  ),
);

Map<String, Object?> clip(
  int n,
  double start,
  double end, {
  double? score,
  String hook = '',
  Map<String, Object?>? short,
}) => {
  'number': n,
  'start': start,
  'end': end,
  'duration': end - start,
  'score': score,
  'hook': hook,
  'reason': null,
  'text': 'o que é dito no $n',
  'overlaps': n == 2,
  'short': short,
};

Map<String, Object?> shortsState({bool plan = true, List<Object?> clips = const [], Map<String, Object?>? job}) => {
  'id': 'aula',
  'name': 'Aula de Dart',
  'eligible': true,
  'reason': null,
  'has_plan': plan,
  'max_duration': 90.0,
  'clips': clips,
  'rejected': plan ? ['#4: passa de 90s'] : <String>[],
  'notes': '',
  'job': job,
};

Map<String, Object?> tokens(String accent) => {
  'colors': {'accent': accent, 'panel': '#151a22', 'text': '#ffffff'},
  'fonts': {'title': 'anton', 'text': 'inter'},
  'radius': 12,
  'speed': 1.0,
  'panel_opacity': .9,
  'thumbnail': {'accent_from': 'topic'},
  'lower_third': {'position': 'bottom-left', 'avatar': true},
  'cta': {
    'position': 'bottom-center',
    'steps': [
      {'icon': 'like', 'text': 'DEIXA O LIKE', 'color': null},
    ],
  },
  'captions': {
    'position': 'bottom',
    'offset': 33,
    'size': 100,
    'font': 'anton',
    'color': '#ffffff',
    'highlight': '#2ee6c6',
    'highlight_mode': 'outline',
    'outline': 3,
    'background': 'none',
    'words': 2,
    'uppercase': true,
  },
};

Map<String, Object?> stylesState() => {
  'active': 'padrao',
  'styles': [
    {'id': 'padrao', 'name': 'Padrão', 'description': 'O de sempre', 'builtin': true, 'tokens': tokens('#2ee6c6')},
    {'id': 'neon', 'name': 'Neon', 'description': 'Roxo', 'builtin': true, 'tokens': tokens('#8b5cf6')},
    {'id': 'meu', 'name': 'Meu', 'description': '', 'builtin': false, 'tokens': tokens('#f87171')},
  ],
  'fonts': [
    {'id': 'anton', 'label': 'Anton'},
    {'id': 'inter', 'label': 'Inter'},
  ],
  'icons': ['like', 'subscribe', 'bell', 'comment'],
  'positions': {
    'lower_third': ['bottom-left', 'bottom-right', 'top-left'],
    'cta': ['bottom-center', 'bottom-right', 'top-right'],
  },
  'brand': {'name': 'gabuldev', 'handle': null, 'logo': null, 'logo_bg': null},
  'ai_vision': true,
};

void main() {
  setUp(() {
    played.clear();
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1440, 3000);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  group('Shorts', () {
    late FakeEngine engine;
    var cut = 0;
    final opened = <String>[];

    Future<void> open(WidgetTester tester) async {
      cut = 0;
      opened.clear();
      await tester.pumpWidget(
        host(ShortsScreen(client: engine.client(), id: 'aula', onBack: () {}, onCut: () => cut++, onOpen: opened.add)),
      );
      await settle(tester);
    }

    setUp(() => engine = FakeEngine());

    testWidgets('no candidates yet: Propor runs the clipper and shows its log', (tester) async {
      engine.shorts['aula'] = shortsState(plan: false);
      await open(tester);
      expect(find.text('Ainda sem candidatos'), findsOneWidget);
      engine.events['aula'] = [
        {'type': 'log', 'line': 'clipper: lendo a transcrição'},
      ];
      await tester.tap(find.text('Propor shorts').last);
      await settle(tester);
      final post = engine.requests.lastWhere((r) => r.method == 'POST' && r.url.path == '/api/videos/aula/shorts');
      expect(jsonDecode(post.body), {'max_dur': 90.0});
      expect(find.text('clipper: lendo a transcrição'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
    });

    testWidgets('watch one, tick two, cut them', (tester) async {
      engine.shorts['aula'] = shortsState(
        clips: [
          clip(1, 10, 40, score: 9, hook: 'O erro que todo mundo comete'),
          clip(2, 35, 70, score: 6),
          clip(
            3,
            100,
            130,
            short: {'id': 'aula_short3', 'status': 'done', 'overwrite_warning': 'aula_short3 já foi editado'},
          ),
        ],
      );
      await open(tester);
      expect(find.text('3 candidatos · 1 já cortado(s)'), findsOneWidget);
      expect(find.text('O erro que todo mundo comete'), findsOneWidget);
      expect(find.text('sobrepõe outro candidato'), findsOneWidget);
      expect(find.textContaining('Cortar de novo sobrescreve'), findsOneWidget);
      expect(find.text('•  #4: passa de 90s'), findsNothing); // folded

      await tester.tap(find.widgetWithText(OutlinedButton, 'Assistir').first);
      await settle(tester);
      expect(played.last.start, const Duration(seconds: 10));
      expect(played.last.end, const Duration(seconds: 40));
      expect(played.last.autoplay, isTrue);
      expect(find.text('Tocando'), findsOneWidget);

      await tester.tap(find.text('o que é dito no 1'));
      await tester.tap(find.text('o que é dito no 3'));
      await settle(tester);
      await tester.tap(find.text('Cortar 2 selecionados'));
      await settle(tester);
      final body = jsonDecode(engine.requests.lastWhere((r) => r.url.path == '/api/videos/aula/shorts/cut').body);
      expect(body, {
        'pick': [1, 3],
        'max_dur': 90.0,
      });
      expect(cut, 1);

      await tester.tap(find.text('já cortado · aula_short3'));
      expect(opened, ['aula_short3']);
    });
  });

  group('Estilos', () {
    late FakeEngine engine;
    late FakePickers pickers;

    Future<void> open(WidgetTester tester) async {
      await tester.pumpWidget(host(StylesScreen(client: engine.client(), pickers: pickers)));
      await settle(tester);
    }

    setUp(() {
      engine = FakeEngine()..styles = stylesState();
      pickers = FakePickers();
    });

    test('tokens by path', () {
      final t = cloneTokens(tokens('#000000'));
      setTok(t, 'captions.size', 120);
      setTok(t, 'thumbnail.html', '<div/>');
      expect(getTok(t, 'captions.size'), 120);
      expect(getTok(t, 'thumbnail.html'), '<div/>');
      expect(getTok(tokens('#000000'), 'captions.size'), 100); // the copy is deep
      expect(parseHex('#2ee6c6'), const Color(0xFF2EE6C6));
      expect(parseHex('red'), isNull);
      expect(hexOf(const Color(0xFF2EE6C6)), '#2ee6c6');
    });

    testWidgets('the gallery with real previews; use another; export', (tester) async {
      await open(tester);
      expect(find.text('Padrão'), findsWidgets);
      expect(find.text('em uso'), findsOneWidget);
      expect(find.text('seu'), findsOneWidget);
      // the four previews and one thumbnail per style
      final previews = engine.calls.where((c) => c.startsWith('POST /api/styles/preview/')).toList();
      expect(previews.where((c) => c.endsWith('/thumbnail')).length, greaterThanOrEqualTo(4));
      expect(previews, containsAll(['POST /api/styles/preview/lower_third', 'POST /api/styles/preview/caption']));
      // a preset can't be deleted
      expect(find.text('Excluir'), findsNothing);

      await tester.tap(find.text('Neon'));
      await settle(tester);
      expect(find.text('Roxo'), findsOneWidget);
      await tester.tap(find.text('Usar este estilo'));
      await settle(tester);
      expect(jsonDecode(engine.requests.lastWhere((r) => r.url.path == '/api/styles/active').body), {'id': 'neon'});
      expect(find.text('Usar este estilo'), findsNothing);

      await tester.tap(find.text('Exportar'));
      await settle(tester);
      expect(find.text('exportado: /home/me/Downloads/neon.autoedit-style.json'), findsOneWidget);
    });

    testWidgets('customize a preset: saved as a copy, activated', (tester) async {
      await open(tester);
      await tester.tap(find.text('Personalizar'));
      await settle(tester);
      expect(find.text('Personalizando: Padrão'), findsOneWidget);
      expect(find.text('Salvar como novo'), findsNothing); // a preset is always saved as new
      await tester.tap(find.text('TUDO EM MAIÚSCULAS'));
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      await tester.tap(find.text('+ adicionar passo'));
      await settle(tester);
      await tester.tap(find.text('Salvar e usar'));
      await settle(tester);
      final saved =
          jsonDecode(engine.requests.lastWhere((r) => r.method == 'POST' && r.url.path == '/api/styles').body) as Map;
      expect(saved['id'], isNull);
      expect(saved['name'], 'Meu Padrão');
      expect(saved['activate'], true);
      expect((saved['tokens'] as Map)['captions']['uppercase'], false);
      expect(((saved['tokens'] as Map)['cta']['steps'] as List).length, 2);
      expect(find.text('Personalizando: Padrão'), findsNothing);
      expect(find.text('Meu Padrão'), findsWidgets);
    });

    testWidgets('discarding asks twice; deleting your own asks twice', (tester) async {
      await open(tester);
      await tester.tap(find.text('Meu'));
      await settle(tester);
      await tester.tap(find.text('Personalizar'));
      await settle(tester);
      await tester.tap(find.text('Descartar'));
      await settle(tester);
      expect(find.text('Clique de novo pra descartar'), findsOneWidget);
      await tester.tap(find.text('Clique de novo pra descartar'));
      await settle(tester);
      expect(find.text('Personalizar'), findsOneWidget);

      await tester.tap(find.text('Excluir'));
      await settle(tester);
      expect(engine.calls.where((c) => c.startsWith('DELETE')), isEmpty);
      await tester.tap(find.text('Confirmar exclusão'));
      await settle(tester);
      expect(engine.calls, contains('DELETE /api/styles/meu'));
      await tester.pump(const Duration(seconds: 3));
    });

    testWidgets('brand: name saved with the logo kept; a logo is uploaded as a data URL', (tester) async {
      await open(tester);
      await tester.enterText(find.widgetWithText(TextField, 'padrão: gabuldev (canal do YouTube)'), 'Gabul');
      await tester.enterText(find.widgetWithText(TextField, '@seucanal'), 'gabuldev');
      await tester.pump(const Duration(milliseconds: 800));
      await settle(tester);
      final put = engine.settingsPuts.last;
      expect(put['brand'], {'name': 'Gabul', 'handle': '@gabuldev', 'logo': null, 'logo_bg': null});
      expect(find.text('salvo'), findsOneWidget);

      pickers.nextImage = (Uint8List.fromList([1, 2, 3]), 'logo.png');
      await tester.tap(find.byTooltip('Escolher a logo').first);
      await settle(tester);
      final logo = jsonDecode(engine.requests.lastWhere((r) => r.url.path == '/api/brand/logo').body) as Map;
      expect(logo['data'], 'data:image/png;base64,AQID');
      expect(find.byTooltip('Remover a logo'), findsOneWidget);
      await tester.pump(const Duration(seconds: 2));
    });

    testWidgets('import: the file content goes to the engine; a bad one says so', (tester) async {
      await open(tester);
      pickers.nextStyleFile = 'não é json';
      await tester.tap(find.text('Importar estilo'));
      await settle(tester);
      expect(find.text('Arquivo não é um estilo do Auto-Edit.'), findsOneWidget);

      pickers.nextStyleFile = jsonEncode({
        'format': 1,
        'name': 'Do amigo',
        'description': '',
        'tokens': tokens('#00ff00'),
      });
      await tester.tap(find.text('Importar estilo'));
      await settle(tester);
      final body = jsonDecode(engine.requests.lastWhere((r) => r.url.path == '/api/styles/import').body) as Map;
      expect((body['file'] as Map)['name'], 'Do amigo');
      expect(find.text('Do amigo'), findsWidgets);
    });
  });
}

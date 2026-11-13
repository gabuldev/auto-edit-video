import 'dart:convert';

import 'package:auto_edit/ui/player.dart';
import 'package:auto_edit/ui/result/effects_panel.dart';
import 'package:auto_edit/ui/result/result_screen.dart';
import 'package:auto_edit/ui/result/retention_panel.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:auto_edit/ui/trend_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';
import 'result_test.dart' show account, publishState, result;

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

/// The control the screen gave the (stand-in) player.
PlayerControl? control;

Widget host(Widget child) => MaterialApp(
  theme: buildTheme(),
  home: PlayerScope(
    builder: (context, s) {
      control = s.control;
      return const ColoredBox(color: Colors.black);
    },
    child: Scaffold(body: child),
  ),
);

Map<String, Object?> retentionState({bool data = true, bool connected = true}) => {
  'id': 'aula',
  'youtube_id': 'yt1',
  'data': data
      ? {
          'duration': 120.0,
          'at_30s': .61,
          'at_60s': .48,
          'at_half': .42,
          'relative_median': 1.1,
          'curve': [
            [0.0, 1.0],
            [30.0, .61],
            [60.0, .48],
            [120.0, .3],
          ],
          'drops': [
            {
              'start': 40.0,
              'end': 48.0,
              'loss': .08,
              'excess': .04,
              'text': 'agora vamos instalar',
              'preamble': 'enrolação',
            },
          ],
          'fetched_at': '2026-11-12T10:00:00+00:00',
        }
      : null,
  'versus_previous': data
      ? {
          'previous': 3,
          'lessons': 2,
          'at_30s': {'before': .55, 'after': .61, 'delta': .06},
          'at_60s': {'before': .5, 'after': .48, 'delta': -.02},
        }
      : null,
  'account': account(connected: connected),
};

void main() {
  setUp(() {
    control = null;
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1440, 3200);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  test('times', () {
    expect(parseTime('1:05.5'), 65.5);
    expect(parseTime('65,5'), 65.5);
    expect(parseTime('1:00:00'), 3600);
    expect(parseTime('abc'), isNull);
    expect(parseTime(''), isNull);
    expect(clock(65.5), '1:05.5');
    expect(pct(.613), '61%');
    expect(pp(.064), '+6.4 pp');
    expect(pp(-.02), '-2.0 pp');
    expect(mmss(75), '1:15');
  });

  group('Resultado: efeitos e retenção', () {
    late FakeEngine engine;
    late FakePickers pickers;
    var pipeline = 0;

    Future<void> open(WidgetTester tester) async {
      pipeline = 0;
      await tester.pumpWidget(
        host(
          ResultScreen(
            client: engine.client(),
            id: 'aula',
            pickers: pickers,
            onBack: () {},
            onPipeline: () => pipeline++,
            onSettings: () {},
          ),
        ),
      );
      await settle(tester);
    }

    setUp(() {
      engine = FakeEngine()
        ..results['aula'] = result('aula')
        ..publishes['aula'] = publishState('aula');
      pickers = FakePickers();
    });

    testWidgets('zoom marked with the player time, a B-roll, a cut, then re-render', (tester) async {
      await open(tester);
      expect(find.text('Efeitos e cortes'), findsOneWidget);

      // the player is at 0:12.0 → "usar o tempo do player" on Começo
      control!.report(const Duration(seconds: 12));
      await tester.tap(find.byTooltip('Usar o tempo do player').first);
      await tester.enterText(find.widgetWithText(TextField, 'm:ss').last, '0:15');
      await settle(tester);
      expect(find.text('0:12.0'), findsOneWidget);
      await tester.tap(find.text('Adicionar'));
      await settle(tester);
      var body = jsonDecode(
        engine.requests.lastWhere((r) => r.method == 'POST' && r.url.path.endsWith('/effects')).body,
      );
      expect(body, {'type': 'zoom', 'start': 12.0, 'end': 15.0, 'scale': 1.2, 'timeline': 'edited'});
      expect(find.text('zoom'), findsOneWidget);
      expect(find.textContaining('refaça o render'), findsOneWidget);

      await tester.tap(find.text('B-roll'));
      await settle(tester);
      await tester.enterText(find.widgetWithText(TextField, 'm:ss').first, '20');
      await tester.enterText(find.widgetWithText(TextField, 'm:ss').last, '24');
      await tester.tap(find.text('Adicionar'));
      await settle(tester);
      expect(find.text('Escolha a imagem ou o vídeo do B-roll.'), findsOneWidget);
      pickers.nextBroll = '/home/me/broll/tela.png';
      await tester.tap(find.text('Escolher imagem ou vídeo'));
      await settle(tester);
      await tester.tap(find.text('Adicionar'));
      await settle(tester);
      body = jsonDecode(engine.requests.lastWhere((r) => r.method == 'POST' && r.url.path.endsWith('/effects')).body);
      expect(body['file'], '/home/me/broll/tela.png');
      expect(find.text('tela.png'), findsNWidgets(2)); // the button and the list

      // remove the zoom
      await tester.tap(find.byTooltip('Remover').first);
      await settle(tester);
      expect(engine.calls, contains('DELETE /api/videos/aula/effects/0'));
      expect(find.text('zoom'), findsNothing);

      await tester.tap(find.text('Cortar trecho'));
      await settle(tester);
      await tester.enterText(find.widgetWithText(TextField, 'm:ss').first, '30');
      await tester.enterText(find.widgetWithText(TextField, 'm:ss').last, '35');
      await tester.tap(find.text('Tirar o trecho'));
      await settle(tester);
      body = jsonDecode(engine.requests.lastWhere((r) => r.url.path.endsWith('/plan/cut')).body);
      expect(body, {'start': 30.0, 'end': 35.0, 'timeline': 'edited'});

      await tester.tap(find.widgetWithText(FilledButton, 'Refazer o render'));
      await settle(tester);
      expect(jsonDecode(engine.requests.lastWhere((r) => r.url.path.endsWith('/resume')).body), {
        'from_stage': 'execute',
      });
      expect(pipeline, 1);
    });

    testWidgets('retention: numbers vs. the ones before, a drop seeks the player', (tester) async {
      engine.retention['aula'] = retentionState();
      await open(tester);
      expect(find.text('Retenção no YouTube'), findsOneWidget);
      expect(find.text('61%'), findsOneWidget);
      expect(find.text('+6.0 pp vs. anteriores'), findsOneWidget);
      expect(find.textContaining('média dos 3 vídeo(s)'), findsOneWidget);
      expect(find.textContaining('agora vamos instalar', findRichText: true), findsOneWidget);
      await tester.tap(find.textContaining('agora vamos instalar', findRichText: true));
      await settle(tester);
      expect(control!.position, const Duration(seconds: 37)); // 3s before the drop
    });

    testWidgets('retention not fetched yet: Buscar curva; not connected: says so', (tester) async {
      engine.retention['aula'] = retentionState(data: false);
      engine.retentionRefreshed = retentionState();
      await open(tester);
      expect(find.textContaining('Ainda sem curva'), findsOneWidget);
      await tester.tap(find.text('Buscar curva'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/videos/aula/retention'));
      expect(find.text('61%'), findsOneWidget);

      engine.retention['aula'] = retentionState(data: false, connected: false);
      await tester.pumpWidget(const SizedBox());
      await open(tester);
      expect(find.textContaining('Conecte (ou reconecte) o YouTube'), findsOneWidget);
    });
  });

  group('Retenção do canal', () {
    testWidgets('the videos, older vs newer, with vs without lessons; a row opens it', (tester) async {
      final engine = FakeEngine()
        ..trend = {
          'videos': [
            {
              'id': 'a',
              'type': 'long',
              'title': 'Primeiro',
              'published_at': '2026-10-01T10:00:00Z',
              'at_30s': .5,
              'lessons': null,
            },
            {
              'id': 'b',
              'type': 'long',
              'title': 'Segundo',
              'published_at': '2026-11-01T10:00:00Z',
              'at_30s': .62,
              'lessons': 3,
              'drops': 2,
            },
          ],
          'summary': {
            'long': {
              'count': 2,
              'older_vs_newer': {
                'older': 1,
                'newer': 1,
                'at_30s': {'before': .5, 'after': .62, 'delta': .12},
              },
              'with_vs_without_lessons': {
                'without': 1,
                'with': 1,
                'at_30s': {'before': .5, 'after': .62, 'delta': .12},
              },
            },
          },
        };
      final opened = <String>[];
      await tester.pumpWidget(host(TrendScreen(client: engine.client(), onOpen: opened.add)));
      await settle(tester);
      expect(engine.calls, contains('GET /api/insights/trend'));
      expect(engine.requests.last.url.queryParameters['type'], 'long');
      expect(find.text('2 vídeos analisados'), findsOneWidget);
      expect(find.text('1 sem, 1 com'), findsOneWidget);
      expect(find.text('+12.0 pp'), findsNWidgets(2));
      expect(find.text('3 lições'), findsOneWidget);
      await tester.tap(find.text('Segundo'));
      expect(opened, ['b']);

      await tester.tap(find.text('Shorts'));
      await settle(tester);
      expect(engine.requests.last.url.queryParameters['type'], 'short');
    });

    testWidgets('nothing analyzed yet', (tester) async {
      final engine = FakeEngine();
      await tester.pumpWidget(host(TrendScreen(client: engine.client(), onOpen: (_) {})));
      await settle(tester);
      expect(find.textContaining('Nenhum vídeo com retenção analisada'), findsOneWidget);
    });
  });
}

import 'dart:convert';

import 'package:auto_edit/ui/pipeline/cuts_screen.dart';
import 'package:auto_edit/ui/pipeline/pipeline_screen.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

Widget host(Widget child) => MaterialApp(
  theme: buildTheme(),
  home: Scaffold(body: child),
);

Map<String, Object?> segment(int i, double start, double end, String text, {String? summary}) => {
  'index': i,
  'start': start,
  'end': end,
  'duration': end - start,
  'summary': summary,
  'text': text,
};

void main() {
  setUp(() {
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1440, 1400);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  test('formatters', () {
    expect(timecode(75.25), '01:15.3');
    expect(timecode(5), '00:05.0');
    expect(shortDuration(75), '1m15s');
    expect(shortDuration(9.4), '9s');
    expect(droppedBlocks('um'), ['um']);
    expect(
      droppedBlocks([
        'a',
        {'reason': 'b'},
      ]),
      ['a', 'b'],
    );
    expect(thousands(1234567), '1.234.567');
  });

  group('Pipeline', () {
    late FakeEngine engine;
    final went = <String>[];

    Future<void> open(WidgetTester tester, String id) async {
      went.clear();
      await tester.pumpWidget(
        host(
          PipelineScreen(
            client: engine.client(),
            id: id,
            every: const Duration(hours: 1),
            onBack: () => went.add('back'),
            onCuts: () => went.add('cuts'),
            onResult: () => went.add('result'),
          ),
        ),
      );
      await settle(tester);
    }

    setUp(() => engine = FakeEngine());

    testWidgets('running: stages, the live log, and a two-click stop', (tester) async {
      engine.library = [summary('aula', status: 'running', stage: 'plan', name: 'Aula de Dart')];
      engine.details['aula'] = {
        'context': 'tutorial de Dart',
        'estimated_tokens': 12345,
        'stage_detail': {
          'extract': {'status': 'complete', 'completed_at': '2026-11-13T12:00:05'},
          'plan': {'status': 'running'},
          'caption': {'status': 'skip'},
        },
      };
      engine.events['aula'] = [
        {'type': 'log', 'line': 'extract: whisper small'},
        {'type': 'stage', 'stage': 'plan'},
        {'type': 'log', 'line': 'plan: aguardando claude responder… 30s'},
      ];
      await open(tester, 'aula');

      expect(find.text('Aula de Dart'), findsOneWidget);
      expect(find.text('~12.345 tokens'), findsOneWidget);
      expect(find.text('plan: aguardando claude responder… 30s'), findsOneWidget);
      expect(find.text('── stage: plan ──'), findsOneWidget);
      // a long never captions
      expect(find.text('caption'), findsNothing);
      expect(find.text('overlay'), findsWidgets);
      expect(find.text('tutorial de Dart'), findsOneWidget);
      // running: no resume, and no result yet
      expect(tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Retomar')).onPressed, isNull);
      expect(find.text('Resultado'), findsNothing);

      await tester.tap(find.text('Parar'));
      await settle(tester);
      expect(engine.calls.where((c) => c.endsWith('/stop')), isEmpty);
      await tester.tap(find.text('Confirmar: parar edição'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/videos/aula/stop'));
      expect(find.text('── parado ──'), findsOneWidget);

      await tester.tap(find.text('Revisar cortes'));
      expect(went, ['cuts']);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
    });

    testWidgets('failed: resume from a chosen stage clears the log', (tester) async {
      engine.library = [summary('vlog', status: 'failed', stage: 'execute')];
      engine.details['vlog'] = {
        'output': '/out/vlog.mp4',
        'stage_detail': {
          'extract': {'status': 'complete'},
          'execute': {'status': 'pending'},
        },
      };
      await open(tester, 'vlog');
      // the current stage reads as failed, not "aguardando"
      expect(find.text('falhou'), findsOneWidget);
      expect(find.text('Sem job ao vivo — o log aparece quando um run está em andamento.'), findsOneWidget);
      expect(find.text('Resultado'), findsOneWidget); // there is an output

      await tester.tap(find.text('execute').last);
      await settle(tester);
      await tester.tap(find.text('plan').last);
      await settle(tester);
      engine.events['vlog'] = [
        {'type': 'log', 'line': 'plan: ok'},
      ];
      await tester.tap(find.text('Retomar'));
      await settle(tester);
      final resume = engine.requests.lastWhere((r) => r.url.path == '/api/videos/vlog/resume');
      expect(jsonDecode(resume.body), {'from_stage': 'plan'});
      expect(find.text('── retomando de plan ──'), findsOneWidget);
      expect(find.text('plan: ok'), findsOneWidget);

      await tester.tap(find.text('/out/vlog.mp4'));
      await settle(tester);
      final reveal = engine.requests.lastWhere((r) => r.url.path == '/api/videos/vlog/open/video');
      expect(jsonDecode(reveal.body), {'reveal': true});
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
    });
  });

  group('Revisar cortes', () {
    late FakeEngine engine;
    var recut = 0;

    Future<void> open(WidgetTester tester, String id) async {
      recut = 0;
      await tester.pumpWidget(host(CutsScreen(client: engine.client(), id: id, onBack: () {}, onRecut: () => recut++)));
      await settle(tester);
    }

    setUp(() => engine = FakeEngine());

    testWidgets('no plan yet', (tester) async {
      await open(tester, 'aula');
      expect(find.textContaining('ainda não tem plano de cortes'), findsOneWidget);
    });

    testWidgets('untick a segment, save and recut', (tester) async {
      engine.library = [summary('aula')];
      engine.plans['aula'] = {
        'id': 'aula',
        'name': 'Aula de Dart',
        'source': 'cut_plan.json',
        'editable': false,
        'duration': 600.0,
        'kept_total': 50.0,
        'kept_segments': [
          segment(0, 0, 20, 'Olá, hoje vamos falar de Dart', summary: 'abertura'),
          segment(1, 30, 60, 'Primeiro, os tipos'),
          segment(2, 70, 75, ''),
        ],
        'cuts': [
          {'start': 20.0, 'end': 30.0, 'duration': 10.0, 'reason': 'silêncio', 'type': 'silence'},
        ],
        'dropped_blocks': [
          {'reason': 'Bloco sobre o setup, repetido'},
        ],
      };
      await open(tester, 'aula');
      expect(find.text('3 de 3 trechos'), findsOneWidget);
      expect(find.text('55s de corte final'), findsOneWidget);
      expect(find.textContaining('rascunho do planner'), findsOneWidget);
      expect(find.text('•  Bloco sobre o setup, repetido'), findsOneWidget);
      expect(find.text('(sem transcrição para este trecho)'), findsOneWidget);
      expect(find.text('O que o planner já cortou (1)'), findsOneWidget);

      await tester.tap(find.text('Primeiro, os tipos'));
      await settle(tester);
      expect(find.text('2 de 3 trechos'), findsOneWidget);
      expect(find.text('25s de corte final'), findsOneWidget);

      await tester.tap(find.text('Salvar e recortar'));
      await settle(tester);
      final put = engine.requests.lastWhere((r) => r.method == 'PUT');
      expect(jsonDecode(put.body), {
        'kept_segments': [
          {'start': 0.0, 'end': 20.0, 'summary': 'abertura'},
          {'start': 70.0, 'end': 75.0},
        ],
      });
      final resume = engine.requests.lastWhere((r) => r.url.path == '/api/videos/aula/resume');
      expect(jsonDecode(resume.body), {'from_stage': 'execute'});
      expect(recut, 1);
      expect(find.text('2 de 2 trechos'), findsOneWidget);
      expect(find.textContaining('rascunho do planner'), findsNothing);
    });
  });
}

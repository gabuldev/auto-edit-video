import 'dart:convert';

import 'package:auto_edit/ui/player.dart';
import 'package:auto_edit/ui/result/caption_adjust.dart';
import 'package:auto_edit/ui/result/publish_card.dart';
import 'package:auto_edit/ui/result/result_screen.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

/// What the screens asked the player to play.
final played = <PlayerSource>[];

Widget host(Widget child) => MaterialApp(
  theme: buildTheme(),
  home: PlayerScope(
    builder: (context, s) {
      played.add(s);
      return ColoredBox(color: Colors.black, child: Text('player ${s.url.path}'));
    },
    child: Scaffold(body: child),
  ),
);

Map<String, Object?> thumb(String id, {bool chosen = false, String qa = 'aprovada', List<String> why = const []}) => {
  'id': id,
  'kind': id == 'A' ? 'thumbnail' : 'thumbnail_${id.toLowerCase()}',
  'layout': 'layout $id',
  'qa': qa,
  'qa_reasons': why,
  'chosen': chosen,
};

Map<String, Object?> result(String id, {String type = 'long', List<Object?> thumbnails = const []}) => {
  'id': id,
  'name': 'Aula de Dart',
  'video_name': id,
  'type': type,
  'status': 'done',
  'metadata': {
    'youtube_title': 'Dart do zero',
    'tags': ['dart', 'flutter'],
    'hook': '',
  },
  'files': {
    'video': {'path': '/out/${id}_final.mp4', 'size': 1536000},
    'notes': {'path': '/out/$id.txt', 'size': 900},
  },
  'thumbnails': thumbnails,
};

Map<String, Object?> account({bool connected = true, bool secret = true, bool connecting = false}) => {
  'connected': connected,
  'connecting': connecting,
  'needs_reconnect': false,
  'channel': connected ? 'gabuldev' : null,
  'error': null,
  'has_client_secret': secret,
  'client_id': null,
};

Map<String, Object?> publishState(
  String id, {
  String type = 'long',
  Map<String, Object?>? acct,
  List<Object?> published = const [],
}) => {
  'id': id,
  'type': type,
  'eligible': true,
  'reason': null,
  'defaults': {
    'title': 'Dart do zero',
    'description': '[REVISAR] escreva a descrição',
    'tags': ['dart', 'flutter'],
    'privacy': 'unlisted',
  },
  'thumbnail': true,
  'thumbnail_variant': 'A',
  'captions': true,
  'pinned_comment': 'Qual a sua dúvida?',
  'title_options': ['Dart do zero', 'Aprenda Dart em 10 min'],
  'next_video': {'title': 'Flutter na prática'},
  'limits': {'title': 100, 'description': 5000},
  'published': published,
  'account': acct ?? account(),
  'job': null,
};

void main() {
  setUp(() {
    played.clear();
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1440, 2400);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  group('caption band math', () {
    test('bottom, top and middle anchor like libass', () {
      const a = Adjust(position: 'bottom', offset: 33, size: 100);
      expect(bandTop(a), closeTo(1 - .33 - .07, 1e-9));
      expect(bandTop(const Adjust(position: 'top', offset: 10)), closeTo(.10, 1e-9));
      // dropped near the top: top, offset from the edge
      expect(fromTop(a, .05), const Adjust(position: 'top', offset: 5, size: 100));
      // in the middle band
      expect(fromTop(a, .47).position, 'middle');
      // low: bottom, offset clamped at 40
      expect(fromTop(a, .9).offset, 3);
      expect(fromTop(a, .2).offset, 20);
    });
  });

  group('publish helpers', () {
    test('[REVISAR] becomes the hint, never the value', () {
      expect(reviewed('[REVISAR] escreva a descrição'), ('', 'escreva a descrição'));
      expect(reviewed('Dart do zero'), ('Dart do zero', null));
    });

    test('where a sent video stands', () {
      PublishStatePublishedItem p(Map<String, Object?> j) =>
          PublishStatePublishedItem.fromJson({'video_id': 'yt1', ...j});
      GetPublishLiveResponse live(Map<String, Object?> videos) =>
          GetPublishLiveResponse.fromJson({'checked': true, 'videos': videos});
      final now = DateTime.utc(2026, 11, 13);
      expect(standingOf(p({'privacy': 'unlisted'}), live({})), isA<Gone>());
      expect(standingOf(p({'privacy': 'unlisted', 'removed': true}), null), isA<Gone>());
      final sched = standingOf(p({'privacy': 'private', 'publish_at': '2026-11-20T21:00:00Z'}), null, now: now) as Live;
      expect(sched.status, startsWith('Programado pra'));
      // YouTube says it went public by itself
      final pub =
          standingOf(
                p({'privacy': 'private', 'publish_at': '2026-11-10T21:00:00Z'}),
                live({
                  'yt1': {'privacy': 'public', 'publish_at': null, 'upload_status': 'processed'},
                }),
              )
              as Live;
      expect((pub.privacy, pub.status), ('public', 'Publicado'));
    });
  });

  group('Resultado', () {
    late FakeEngine engine;
    var pipeline = 0;

    Future<void> open(WidgetTester tester, String id) async {
      pipeline = 0;
      await tester.pumpWidget(
        host(
          ResultScreen(client: engine.client(), id: id, onBack: () {}, onPipeline: () => pipeline++, onSettings: () {}),
        ),
      );
      await settle(tester);
    }

    setUp(() => engine = FakeEngine());

    testWidgets('a long: player, A/B/C with QA, files, copy, publish form', (tester) async {
      engine.results['aula'] = result(
        'aula',
        thumbnails: [
          thumb('A', chosen: true),
          thumb('B', qa: 'reprovada', why: ['texto sobre o rosto']),
        ],
      );
      engine.publishes['aula'] = publishState('aula');
      await open(tester, 'aula');

      expect(find.text('Aula de Dart'), findsOneWidget);
      expect(played.single.url.path, '/api/videos/aula/file/video');
      expect(find.text('Vídeo final'), findsWidgets);
      expect(find.text('Metadata (.txt)'), findsOneWidget);
      expect(find.text('vai na publicação'), findsOneWidget);
      // the empty hook is not listed
      expect(find.text('Gancho'), findsNothing);

      // B: its QA and the reasons, and "Usar esta"
      await tester.tap(find.text('B'));
      await settle(tester);
      expect(find.text('QA reprovou'), findsOneWidget);
      expect(find.text('•  texto sobre o rosto'), findsOneWidget);
      await tester.tap(find.text('Usar esta na publicação'));
      await settle(tester);
      final put = engine.requests.lastWhere((r) => r.url.path == '/api/videos/aula/thumbnail');
      expect(jsonDecode(put.body), {'variant': 'B'});
      expect(find.text('vai na publicação'), findsOneWidget);
      expect(find.textContaining('A thumbnail B vai junto'), findsOneWidget);

      // copy the title
      final copied = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') copied.add((call.arguments as Map)['text'] as String);
        return null;
      });
      await tester.tap(find.byTooltip('Copiar Tags'));
      await settle(tester);
      expect(copied, ['#dart #flutter']);

      // the form: filled from metadata, [REVISAR] as the hint only
      expect(find.text('Conectado como gabuldev'), findsOneWidget);
      expect(find.text('escreva a descrição'), findsOneWidget);
      expect(find.textContaining('Tela final (últimos 20s, no Studio): indique "Flutter na prática".'), findsOneWidget);
      await tester.tap(find.text('Aprenda Dart em 10 min'));
      await settle(tester);
      engine.events['aula'] = [
        {'type': 'progress', 'pct': 40},
      ];
      await tester.tap(find.text('Enviar pro YouTube'));
      await settle(tester);
      final pub = engine.requests.lastWhere((r) => r.url.path == '/api/videos/aula/publish/youtube');
      expect(jsonDecode(pub.body), {
        'title': 'Aprenda Dart em 10 min',
        'description': '',
        'tags': ['dart', 'flutter'],
        'privacy': 'unlisted',
        'captions': true,
        'force': false,
      });
      expect(find.text('Enviando pro YouTube…'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
    });

    testWidgets('already sent: the history, YouTube says it is public; send again asks', (tester) async {
      engine.results['aula'] = result('aula');
      engine.publishes['aula'] = publishState(
        'aula',
        published: [
          {
            'video_id': 'yt1',
            'url': 'https://youtu.be/yt1',
            'title': 'Dart do zero',
            'privacy': 'private',
            'publish_at': '2026-11-10T21:00:00Z',
            'published_at': '2026-11-09T10:00:00Z',
            'captions': true,
            'warnings': ['comentário não postado: vídeo privado'],
          },
        ],
      );
      engine.lives['aula'] = {
        'checked': true,
        'videos': {
          'yt1': {'privacy': 'public', 'publish_at': null, 'upload_status': 'processed'},
        },
      };
      await open(tester, 'aula');
      expect(find.text('Publicado'), findsOneWidget);
      expect(find.text('Público'), findsOneWidget);
      expect(find.textContaining('com legenda'), findsOneWidget);
      expect(find.text('Comentário não postado'), findsNothing); // inside a rich text
      expect(find.textContaining('vídeo privado', findRichText: true), findsOneWidget);
      expect(find.text('Enviar pro YouTube'), findsNothing);
      await tester.tap(find.text('Ver no YouTube'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/open-url'));
      await tester.tap(find.text('Enviar de novo'));
      await settle(tester);
      expect(find.widgetWithText(OutlinedButton, 'Enviar de novo'), findsOneWidget);
      expect(find.text('Cancelar'), findsOneWidget);
    });

    testWidgets('not connected: no credential sends to Configurações; with one, Conectar', (tester) async {
      engine.results['aula'] = result('aula');
      engine.publishes['aula'] = publishState('aula', acct: account(connected: false, secret: false));
      await open(tester, 'aula');
      expect(find.text('YouTube não configurado'), findsOneWidget);
      expect(find.text('Abrir Configurações'), findsOneWidget);

      engine.publishes['aula'] = publishState('aula', acct: account(connected: false));
      engine.youtube = {...engine.youtube, 'has_client_secret': true};
      await tester.pumpWidget(const SizedBox());
      await open(tester, 'aula');
      await tester.tap(find.text('Conectar YouTube'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/publish/youtube/connect'));
      expect(find.text('Esperando autorização…'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
    });

    testWidgets('a short: adjust the caption, drag the band, regravar', (tester) async {
      engine.results['clip'] = result('clip', type: 'short');
      engine.publishes['clip'] = publishState('clip', type: 'short');
      engine.library = [summary('clip', type: 'short')];
      engine.captions['clip'] = {
        'captions': {'position': 'bottom', 'offset': 33, 'size': 100},
        'adjust': <String, Object?>{},
        'fast': true,
        'source_ok': true,
        'video_path': '/inbox/clip.mp4',
      };
      await open(tester, 'clip');
      expect(find.textContaining('Short: o YouTube não aceita thumbnail'), findsOneWidget);
      await tester.tap(find.text('Ajustar legenda'));
      await tester.pump(const Duration(milliseconds: 500));
      await settle(tester);
      expect(engine.calls, contains('POST /api/videos/clip/captions/preview'));
      expect(find.text('Tamanho 100%'), findsOneWidget);

      await tester.drag(find.byKey(const Key('caption-band')), const Offset(0, -380));
      await tester.pump(const Duration(milliseconds: 500));
      await settle(tester);
      await tester.tap(find.text('Esconder legenda'));
      await tester.pump(const Duration(milliseconds: 500));
      await tester.tap(find.text('Regravar legenda'));
      await settle(tester);
      final put = jsonDecode(engine.requests.lastWhere((r) => r.method == 'PUT').body) as Map;
      expect(put['position'], 'top');
      expect(put['hidden'], true);
      final resume = engine.requests.lastWhere((r) => r.url.path == '/api/videos/clip/resume');
      expect(jsonDecode(resume.body), {'from_stage': 'caption', 'caption_only': true});
      expect(pipeline, 1);
    });

    testWidgets('a short whose recording is gone (old video): regravar is blocked, says why', (tester) async {
      engine.results['clip'] = result('clip', type: 'short');
      engine.publishes['clip'] = publishState('clip', type: 'short');
      engine.captions['clip'] = {
        'captions': <String, Object?>{},
        'adjust': <String, Object?>{},
        'fast': false,
        'source_ok': false,
        'video_path': '/inbox/clip.mp4',
      };
      await open(tester, 'clip');
      await tester.tap(find.text('Ajustar legenda'));
      await tester.pump(const Duration(milliseconds: 500));
      await settle(tester);
      expect(find.textContaining('O vídeo original não está mais em /inbox/clip.mp4'), findsOneWidget);
      final b = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Regravar legenda (vai recortar, alguns minutos)'),
      );
      expect(b.onPressed, isNull);
    });
  });
}

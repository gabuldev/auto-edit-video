import 'package:auto_edit/main.dart';
import 'package:auto_edit/platform.dart';
import 'package:auto_edit/ui/edits/edits_screen.dart';
import 'package:auto_edit/ui/format.dart';
import 'package:auto_edit/ui/new_edit_screen.dart';
import 'package:auto_edit/ui/recordings_screen.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:auto_edit/ui/video_pick.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
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

/// A machine already set up, so the app opens on Edições.
FakeEngine readyEngine() => FakeEngine()
  ..verifiedAgent = 'claude'
  ..whisper = {'model': 'small', 'ready': true, 'downloading': false, 'progress': 1.0, 'size_mb': 466, 'error': null};

Map<String, Object?> recording(
  String name, {
  int w = 1920,
  int h = 1080,
  String folder = '',
  List<Object?> edits = const [],
}) => {
  'name': name,
  'path': '/home/me/Gravações/${folder.isEmpty ? '' : '$folder/'}$name',
  'folder': folder,
  'ext': name.split('.').last,
  'size': 1536000000,
  'modified': '2026-11-10T13:05:00+00:00',
  'duration': 754.2,
  'width': w,
  'height': h,
  'edits': edits,
};

void main() {
  setUp(() {
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(1440, 2000);
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  group('format', () {
    test('sizes, durations, search', () {
      expect(humanSize(1536), '1.5 KB');
      expect(humanSize(1536000000), '1.4 GB');
      expect(duration(754.2), '12:34');
      expect(duration(3725), '1:02:05');
      expect(matchesQuery('cafe tec', ['Café com Tecnologia']), isTrue);
      expect(matchesQuery('cafe python', ['Café com Tecnologia']), isFalse);
      expect(baseName(r'C:\videos\a.mp4'), 'a.mp4');
      expect(VideoDrop.pick(['/a/notes.txt', '/a/b.MOV']), ('/a/b.MOV', null));
      expect(VideoDrop.pick(['/a/notes.txt']).$2, notVideo);
    });
  });

  group('Edições', () {
    late FakeEngine engine;
    late FakePickers pickers;
    String? newEditPath;
    var newEditOpened = false;
    final opened = <String>[];

    Future<void> open(WidgetTester tester) async {
      newEditOpened = false;
      newEditPath = null;
      opened.clear();
      await tester.pumpWidget(
        host(
          EditsScreen(
            client: engine.client(),
            pickers: pickers,
            every: const Duration(hours: 1),
            onNewEdit: ({String? path}) {
              newEditOpened = true;
              newEditPath = path;
            },
            onOpen: (id, {bool result = false}) => opened.add(result ? '$id/result' : id),
          ),
        ),
      );
      await settle(tester);
    }

    setUp(() {
      engine = FakeEngine();
      pickers = FakePickers();
    });

    testWidgets('a row opens its pipeline; a finished one also its result', (tester) async {
      engine.library = [summary('aula', status: 'running', stage: 'plan'), summary('vlog', name: 'Vlog de sábado')];
      await open(tester);
      await tester.tap(find.text('aula.mp4'));
      await settle(tester);
      expect(find.text('Ver resultado'), findsOneWidget); // only the finished one
      await tester.tap(find.text('Ver resultado'));
      await tester.tap(find.text('Vlog de sábado'));
      await settle(tester);
      expect(opened, ['aula', 'vlog/result', 'vlog']);
    });

    testWidgets('empty: a drop zone; picking a video opens Novo edit with it', (tester) async {
      await open(tester);
      expect(find.text('Nenhuma edição ainda'), findsOneWidget);
      pickers.nextVideo = '/home/me/Gravações/aula.mp4';
      await tester.tap(find.text('Nenhuma edição ainda'));
      await settle(tester);
      expect(newEditPath, '/home/me/Gravações/aula.mp4');
    });

    testWidgets('the rows: name, status, the stages it runs', (tester) async {
      engine.library = [
        summary('aula', name: 'Aula de Dart'),
        summary('vlog', type: 'short', status: 'failed', stage: 'plan'),
        summary(
          'pub',
          title: 'Publicado no canal',
          published: {'privacy': 'unlisted', 'published_at': '2026-11-10T13:05:00+00:00', 'count': 2},
        ),
      ];
      await open(tester);
      expect(find.text('3 edições · 0 em andamento'), findsOneWidget);
      expect(find.text('Aula de Dart'), findsOneWidget);
      expect(find.text('vlog.mp4'), findsOneWidget); // no name yet: the file's
      expect(find.text('Pronto'), findsOneWidget);
      expect(find.text('Falhou'), findsOneWidget);
      expect(find.text('Publicado'), findsOneWidget);
      expect(find.text('plan'), findsOneWidget);
      // A long skips caption: 8 of the 9 stages.
      final row = find.ancestor(of: find.text('Aula de Dart'), matching: find.byType(Material)).first;
      expect(row, findsOneWidget);

      await tester.enterText(find.byType(TextField), 'publicado');
      await settle(tester);
      expect(find.text('Aula de Dart'), findsNothing);
      expect(find.text('Publicado no canal'), findsOneWidget);
      expect(find.text('1 de 3 edições · 0 em andamento'), findsOneWidget);
    });

    testWidgets('a running edit follows its live stream', (tester) async {
      engine.library = [summary('aula', status: 'running', stage: 'extract')];
      engine.events['aula'] = [
        {'type': 'stage', 'stage': 'plan'},
        {'type': 'log', 'line': 'plan: aguardando claude responder… 30s'},
      ];
      await open(tester);
      expect(find.text('Rodando'), findsOneWidget);
      expect(find.text('plan'), findsOneWidget);
      expect(find.text('plan: aguardando claude responder… 30s'), findsOneWidget);
      expect(engine.calls, contains('GET /api/videos/aula/events'));
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 1)); // the stream's reconnect delay
    });

    testWidgets('delete asks first, in the row', (tester) async {
      engine.library = [summary('aula', name: 'Aula de Dart')];
      await open(tester);
      await tester.tap(find.byTooltip('Excluir vídeo'));
      await settle(tester);
      expect(engine.calls, isNot(contains('DELETE /api/videos/aula')));
      await tester.tap(find.widgetWithText(OutlinedButton, 'Excluir'));
      await settle(tester);
      expect(engine.calls, contains('DELETE /api/videos/aula'));
      expect(find.text('Nenhuma edição ainda'), findsOneWidget);
    });

    testWidgets('a running edit can be cancelled (asked first)', (tester) async {
      engine.library = [summary('aula', status: 'running', stage: 'plan')];
      await open(tester);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Cancelar'));
      await settle(tester);
      expect(find.text('Cancelar edição'), findsOneWidget);
      await tester.tap(find.text('Cancelar edição'));
      await settle(tester);
      expect(engine.calls, contains('POST /api/videos/aula/stop'));
      expect(find.text('Falhou'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('several selected, deleted together', (tester) async {
      engine.library = [summary('a', status: 'running', stage: 'plan'), summary('b'), summary('c')];
      await open(tester);
      final boxes = find.byType(Checkbox);
      await tester.tap(boxes.at(1));
      await tester.tap(boxes.at(2));
      await settle(tester);
      expect(find.text('2 selecionadas'), findsOneWidget);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Excluir'));
      await settle(tester);
      expect(find.textContaining('Uma está rodando e vai ser cancelada.'), findsOneWidget);
      await tester.tap(find.text('Excluir 2 edições'));
      await settle(tester);
      expect(engine.calls.where((c) => c.startsWith('DELETE')), ['DELETE /api/videos/a', 'DELETE /api/videos/b']);
      expect(find.text('1 edição · 0 em andamento'), findsOneWidget);
    });

    testWidgets('"Novo edit" in the top bar', (tester) async {
      engine.library = [summary('a')];
      await open(tester);
      await tester.tap(find.text('Novo edit'));
      expect(newEditOpened, isTrue);
      expect(newEditPath, isNull);
    });
  });

  group('Biblioteca', () {
    testWidgets('the inbox videos; Editar ticks the type by the shape', (tester) async {
      final engine = FakeEngine()
        ..recordings = {
          'folder': '/home/me/Gravações',
          'exists': true,
          'truncated': false,
          'recordings': [
            recording(
              'aula.mp4',
              folder: '2026/nov',
              edits: [
                {'id': 'aula', 'name': 'Aula de Dart', 'status': 'done'},
              ],
            ),
            recording('reel.mov', w: 1080, h: 1920),
          ],
        };
      (String, VideoType?)? edited;
      var toSettings = false;
      await tester.pumpWidget(
        host(
          RecordingsScreen(
            client: engine.client(),
            onEdit: (p, t) => edited = (p, t),
            onSettings: () => toSettings = true,
          ),
        ),
      );
      await settle(tester);
      expect(find.text('aula.mp4'), findsOneWidget);
      expect(find.text('Pasta: 2026/nov'), findsOneWidget);
      expect(find.text('Pasta principal'), findsOneWidget);
      expect(find.text('12:34'), findsNWidgets(2));
      expect(find.text('Horizontal'), findsOneWidget);
      expect(find.text('Vertical'), findsOneWidget);
      expect(find.text('1.4 GB'), findsNWidgets(2));
      expect(find.text('Editado'), findsOneWidget);

      await tester.tap(find.text('Editar').last);
      expect(edited, ('/home/me/Gravações/reel.mov', VideoType.short));

      await tester.enterText(find.byType(TextField), 'dart');
      await settle(tester);
      expect(find.text('reel.mov'), findsNothing); // found by its edit's name
      expect(find.text('aula.mp4'), findsOneWidget);

      await tester.tapOnText(find.textRange.ofSubstring('trocar pasta'));
      expect(toSettings, isTrue);
    });

    testWidgets('an inbox that is gone says so', (tester) async {
      final engine = FakeEngine()
        ..recordings = {'folder': '/sumiu', 'exists': false, 'truncated': false, 'recordings': <Object?>[]};
      await tester.pumpWidget(host(RecordingsScreen(client: engine.client(), onEdit: (_, _) {}, onSettings: () {})));
      await settle(tester);
      expect(find.text('A pasta de entrada não existe mais: /sumiu.'), findsOneWidget);
      expect(find.text('Escolher outra em Configurações'), findsOneWidget);
    });
  });

  group('Novo edit', () {
    late FakeEngine engine;
    late FakePickers pickers;
    String? started;

    Future<void> open(WidgetTester tester, {String? path, VideoType? type}) async {
      started = null;
      await tester.pumpWidget(
        host(
          NewEditScreen(
            client: engine.client(),
            pickers: pickers,
            path: path,
            type: type,
            onStarted: (id) => started = id,
            onCancel: () {},
          ),
        ),
      );
      await settle(tester);
    }

    setUp(() {
      engine = FakeEngine()..settings = {...FakeEngine().settings, 'language': 'en', 'cold_open': false};
      pickers = FakePickers();
    });

    FilledButton startButton(WidgetTester tester) =>
        tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Iniciar edição'));

    testWidgets('pick, type, context: starts with what Configurações set', (tester) async {
      await open(tester);
      expect(startButton(tester).onPressed, isNull);
      pickers.nextVideo = '/home/me/Gravações/aula.mp4';
      await tester.tap(find.text('Arraste o vídeo pra cá'));
      await settle(tester);
      expect(find.text('aula.mp4'), findsOneWidget);
      expect(find.text('Sem nome, usa “aula”'), findsOneWidget);
      expect(startButton(tester).onPressed, isNull); // no type yet

      await tester.tap(find.text('Pra vídeo no YouTube'));
      await tester.enterText(
        find.widgetWithText(TextField, 'review de produto tech, tom direto, manter as comparações de preço'),
        'tutorial de Dart',
      );
      await settle(tester);
      await tester.tap(find.text('Iniciar edição'));
      await settle(tester);
      final body = engine.edits.single;
      expect(body['video_path'], '/home/me/Gravações/aula.mp4');
      expect(body['type'], 'long');
      expect(body['context'], 'tutorial de Dart');
      expect(body['language'], 'en');
      expect(body['cold_open'], false);
      expect(body['reorder'], true);
      expect(body['max_iterations'], 3);
      expect(body.containsKey('name'), isFalse); // blank: the file's name
      expect(started, 'aula');
    });

    testWidgets('from Biblioteca: the video and its type already chosen', (tester) async {
      await open(tester, path: '/home/me/Gravações/reel.mov', type: VideoType.short);
      expect(find.text('reel.mov'), findsOneWidget);
      await tester.enterText(find.widgetWithText(TextField, 'Sem nome, usa “reel”'), 'Reel do café');
      await tester.tap(find.text('Iniciar edição'));
      await settle(tester);
      expect(engine.edits.single['type'], 'short');
      expect(engine.edits.single['name'], 'Reel do café');
    });

    testWidgets('a file that is not a video', (tester) async {
      await open(tester, path: '/home/me/notas.txt');
      expect(find.text(notVideo), findsOneWidget);
    });
  });

  testWidgets('the whole way: Biblioteca → Editar → Novo edit → it shows up running in Edições', (tester) async {
    final engine = readyEngine()
      ..recordings = {
        'folder': '/home/me/Gravações',
        'exists': true,
        'truncated': false,
        'recordings': [recording('aula.mp4')],
      };
    await tester.pumpWidget(AutoEditApp(client: engine.client(), prefs: AppPrefs.memory(), pickers: FakePickers()));
    await settle(tester);
    expect(find.text('Nenhuma edição ainda'), findsOneWidget);
    await tester.tap(find.text('Biblioteca'));
    await settle(tester);
    await tester.tap(find.text('Editar'));
    await settle(tester);
    expect(find.text('Novo edit'), findsWidgets);
    await tester.tap(find.text('Iniciar edição')); // long ticked by the shape
    await settle(tester);
    expect(engine.edits.single['type'], 'long');
    // straight to its pipeline
    expect(find.text('Revisar cortes'), findsOneWidget);
    expect(find.text('Rodando'), findsOneWidget);
    await tester.tap(find.byTooltip('Voltar'));
    await settle(tester);
    expect(find.text('Rodando'), findsOneWidget);
    expect(find.text('1 edição · 1 em andamento'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}

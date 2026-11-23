import 'package:auto_edit/main.dart';
import 'package:auto_edit/platform.dart';
import 'package:auto_edit/remote/discovery.dart';
import 'package:auto_edit/remote/edit_watcher.dart';
import 'package:auto_edit/remote/pair_screen.dart';
import 'package:auto_edit/remote/remote_root.dart';
import 'package:auto_edit/remote/remote_store.dart';
import 'package:auto_edit/ui/shell.dart';
import 'package:auto_edit/ui/theme.dart';
import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_engine.dart';

const fp = 'ab12cd34ef567890ab12cd34ef567890ab12cd34ef567890ab12cd34ef567890';
const link = 'autoedit://pair?host=192.168.0.10&port=8761&code=c0d1g0&fp=$fp&name=estudio';

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

class FakeNotifier implements Notifier {
  final shown = <String>[];
  @override
  Future<void> init() async {}
  @override
  Future<void> show(int id, String title, String body) async => shown.add('$title: $body');
}

RemoteEngine saved({String host = '192.168.0.10'}) =>
    RemoteEngine(baseUrl: Uri.parse('https://$host:8761'), token: 'tok-123', fingerprint: fp, name: 'estudio');

void main() {
  late FakeEngine engine;

  setUp(() {
    engine = FakeEngine();
    final view = TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
    view.physicalSize = const Size(390, 844); // a phone
    view.devicePixelRatio = 1;
  });
  tearDown(() => TestWidgetsFlutterBinding.instance.platformDispatcher.views.first.resetPhysicalSize());

  test('the QR link becomes the engine to pair with', () {
    final l = EngineConfig.pairingLink(link)!;
    expect(l.config.baseUrl.toString(), 'https://192.168.0.10:8761');
    expect(l.config.fingerprint, fp);
    expect(l.code, 'c0d1g0');
    expect(l.name, 'estudio');
    expect(EngineConfig.pairingLink('https://example.com'), isNull);
  });

  group('Parear', () {
    Future<List<RemoteEngine>> open(WidgetTester tester) async {
      final paired = <RemoteEngine>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTheme(),
          home: PairScreen(onPaired: paired.add, connect: engine.client),
        ),
      );
      return paired;
    }

    testWidgets('a pasted link pairs and keeps the token', (tester) async {
      final paired = await open(tester);
      await tester.enterText(find.byType(TextField), link);
      await tester.tap(find.text('Parear'));
      await settle(tester);
      expect(paired.single.token, 'tok-123');
      expect(paired.single.fingerprint, fp);
      expect(paired.single.baseUrl.host, '192.168.0.10');
      // it connected with the QR's address and certificate
      expect(engine.configs.last.fingerprint, fp);
    });

    testWidgets('an old code says what to do', (tester) async {
      engine.pairCode = 'outro';
      final paired = await open(tester);
      await tester.enterText(find.byType(TextField), link);
      await tester.tap(find.text('Parear'));
      await settle(tester);
      expect(paired, isEmpty);
      expect(find.textContaining('gere outro QR'), findsOneWidget);
    });

    testWidgets('a link that is not ours is refused before any request', (tester) async {
      await open(tester);
      await tester.enterText(find.byType(TextField), 'https://example.com');
      await tester.tap(find.text('Parear'));
      await settle(tester);
      expect(find.textContaining('não é o QR code do Auto-Edit'), findsOneWidget);
      expect(engine.requests, isEmpty);
    });

    testWidgets('the camera reads the code too', (tester) async {
      final paired = <RemoteEngine>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTheme(),
          home: PairScreen(
            onPaired: paired.add,
            connect: engine.client,
            scanner: (context, onCode) => TextButton(onPressed: () => onCode(link), child: const Text('câmera')),
          ),
        ),
      );
      await tester.tap(find.text('câmera'));
      await settle(tester);
      expect(paired, hasLength(1));
    });
  });

  group('No celular', () {
    Future<MemoryRemoteStore> open(WidgetTester tester, {RemoteEngine? stored, Discovery? discovery}) async {
      final store = MemoryRemoteStore(stored);
      await tester.pumpWidget(
        RemoteRoot(
          store: store,
          prefs: AppPrefs.memory({'setup_later': true}),
          discovery: discovery ?? const NoDiscovery(),
          scanner: null,
          connect: engine.client,
        ),
      );
      await settle(tester);
      return store;
    }

    testWidgets('without a computer it asks to pair, then opens the app', (tester) async {
      final store = await open(tester);
      expect(find.text('Conectar ao computador'), findsOneWidget);
      await tester.enterText(find.byType(TextField), link);
      await tester.tap(find.text('Parear'));
      await settle(tester);
      expect(store.engine?.token, 'tok-123');
      // the app, with the sections at the bottom (a phone)
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(engine.configs.last.token, 'tok-123');
    });

    testWidgets('a revoked phone goes back to pairing and says why', (tester) async {
      engine.revoked = true;
      final store = await open(tester, stored: saved());
      expect(find.text('Conectar ao computador'), findsOneWidget);
      expect(find.textContaining('desconectou este celular'), findsOneWidget);
      expect(store.engine, isNull);
    });

    testWidgets('a computer with a new IP is found again by its certificate', (tester) async {
      engine.up = false; // the old address doesn't answer
      final store = await open(
        tester,
        stored: saved(host: '192.168.0.10'),
        discovery: const NoDiscovery([
          FoundEngine(host: '192.168.0.99', port: 8761, fingerprint: 'outro'),
          FoundEngine(host: '192.168.0.42', port: 8761, fingerprint: fp),
        ]),
      );
      expect(store.engine!.baseUrl.host, '192.168.0.42');
      expect(store.engine!.token, 'tok-123');
    });

    testWidgets('Configurações → Desconectar forgets the computer', (tester) async {
      final store = await open(tester, stored: saved());
      await tester.tap(find.byIcon(Section.settings.icon));
      await settle(tester);
      expect(find.textContaining('Auto-Edit em estudio'), findsOneWidget);
      await tester.ensureVisible(find.text('Desconectar este celular'));
      await tester.tap(find.text('Desconectar este celular'));
      await settle(tester);
      await tester.tap(find.text('Desconectar mesmo'));
      await settle(tester);
      expect(store.engine, isNull);
      expect(find.text('Conectar ao computador'), findsOneWidget);
    });
  });

  test('says when a running edit finishes or fails, not what was already done', () async {
    final notifier = FakeNotifier();
    engine.library = [
      summary('a', status: 'running', stage: 'execute', name: 'Vlog'),
      summary('b', status: 'running', stage: 'plan', name: 'Review'),
      summary('c', status: 'done', name: 'Velho'),
    ];
    final watcher = EditWatcher(engine.client(), notifier, every: const Duration(hours: 1));
    await watcher.check();
    expect(notifier.shown, isEmpty);
    engine.library = [
      summary('a', status: 'done', name: 'Vlog'),
      summary('b', status: 'failed', stage: 'plan', name: 'Review'),
      summary('c', status: 'done', name: 'Velho'),
    ];
    await watcher.check();
    expect(notifier.shown, [
      'Edição pronta: Vlog está pronto pra ver e publicar.',
      'A edição parou: Review falhou no stage plan.',
    ]);
    watcher.dispose();
  });

  testWidgets('a desktop window keeps the sidebar', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    await tester.pumpWidget(AutoEditApp(client: engine.client(), prefs: AppPrefs.memory({'setup_later': true})));
    await settle(tester);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.byType(Sidebar), findsOneWidget);
  });
}

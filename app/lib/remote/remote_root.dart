import 'dart:async';
import 'dart:io';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../main.dart';
import '../platform.dart';
import '../ui/theme.dart';
import 'discovery.dart';
import 'edit_watcher.dart';
import 'mobile_pickers.dart';
import 'pair_screen.dart';
import 'remote_store.dart';

/// What the phone opens with: the pairing screen until there's a computer,
/// then the app driving it.
///
/// On the way in it checks the saved computer: a revoked token (401) goes
/// back to pairing with a word on why; an address that stopped answering is
/// looked up by mDNS (the same certificate at a new IP).
class RemoteRoot extends StatefulWidget {
  const RemoteRoot({
    super.key,
    required this.store,
    required this.prefs,
    this.discovery = const NsdDiscovery(),
    this.scanner = cameraScanner,
    this.notifier,
    this.connect,
  });

  final RemoteStore store;
  final AppPrefs prefs;
  final Discovery discovery;
  final ScannerBuilder? scanner;
  final Notifier? notifier;
  final AutoEditClient Function(EngineConfig)? connect;

  @override
  State<RemoteRoot> createState() => _RemoteRootState();
}

class _RemoteRootState extends State<RemoteRoot> {
  RemoteEngine? _engine;
  AutoEditClient? _client;
  String? _notice;
  bool _loading = true;
  final _navigator = GlobalKey<NavigatorState>();

  AutoEditClient Function(EngineConfig) get _connect => widget.connect ?? AutoEditClient.new;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final saved = await widget.store.load();
    if (saved != null) await _use(await _checked(saved));
    if (mounted) setState(() => _loading = false);
  }

  /// The saved computer if it answers; else the same one found by mDNS; null if it revoked us.
  Future<RemoteEngine?> _checked(RemoteEngine engine) async {
    final client = _connect(engine.config);
    try {
      await client.api.health().timeout(const Duration(seconds: 5));
      return engine;
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        await widget.store.clear();
        _notice = 'O computador desconectou este celular. Pareie de novo.';
        return null;
      }
      return engine;
    } catch (_) {
      // Not answering: maybe a new IP. The certificate says it's the same machine.
      try {
        final found = await widget.discovery.scan();
        for (final f in found) {
          if (f.fingerprint == engine.fingerprint) {
            final moved = engine.at(f.host, f.port);
            await widget.store.save(moved);
            return moved;
          }
        }
      } catch (_) {
        // no mDNS: keep the saved address, the app keeps retrying
      }
      return engine;
    } finally {
      client.close();
    }
  }

  Future<void> _use(RemoteEngine? engine) async {
    _client?.close();
    _engine = engine;
    _client = engine == null ? null : _connect(engine.config);
  }

  Future<void> _paired(RemoteEngine engine) async {
    await widget.store.save(engine);
    await _use(engine);
    if (mounted) setState(() => _notice = null);
  }

  Future<void> _unpair() async {
    await widget.store.clear();
    await _use(null);
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final engine = _engine;
    final client = _client;
    if (_loading || engine == null || client == null) {
      return MaterialApp(
        title: 'Auto-Edit',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: _loading
            ? const Scaffold(body: Center(child: CircularProgressIndicator()))
            : PairScreen(
                onPaired: (e) => unawaited(_paired(e)),
                scanner: widget.scanner,
                notice: _notice,
                connect: widget.connect,
              ),
      );
    }
    final name = engine.name ?? engine.baseUrl.host;
    return AutoEditApp(
      key: ValueKey(engine.baseUrl),
      client: client,
      prefs: widget.prefs,
      remote: name,
      onUnpair: () => unawaited(_unpair()),
      navigatorKey: _navigator,
      pickers: MobilePickers(client: client, navigator: _navigator),
      watcher: widget.notifier == null ? null : EditWatcher(client, widget.notifier!),
    );
  }
}

/// The camera reading QR codes (mobile_scanner).
Widget cameraScanner(BuildContext context, ValueChanged<String> onCode) => MobileScanner(
  onDetect: (capture) {
    for (final b in capture.barcodes) {
      final text = b.rawValue;
      if (text != null && text.startsWith('autoedit://')) {
        onCode(text);
        return;
      }
    }
  },
);

/// The phone build: no local engine, a paired computer instead.
bool get isPhone => Platform.isAndroid || Platform.isIOS;

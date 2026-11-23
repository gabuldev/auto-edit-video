import 'dart:async';
import 'dart:io';
import 'dart:ui';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:path_provider/path_provider.dart';

import 'engine/locator.dart';
import 'engine/status.dart';
import 'engine/supervisor.dart';
import 'platform.dart';
import 'remote/edit_watcher.dart';
import 'remote/remote_root.dart';
import 'remote/remote_store.dart';
import 'ui/boot.dart';
import 'ui/shell.dart';
import 'ui/theme.dart';

const enginePort = 8760;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  final support = (await getApplicationSupportDirectory()).path;
  final prefs = AppPrefs(File('$support${Platform.pathSeparator}prefs.json'));
  if (isPhone) {
    // The phone drives the computer's engine (#147): pairing, then the same screens.
    runApp(RemoteRoot(store: SecureRemoteStore(), prefs: prefs, notifier: LocalNotifier()));
    return;
  }
  final host = Host(repoRoot: findRepoRoot([Directory.current.path, File(Platform.resolvedExecutable).parent.path]));
  final logs = Directory('$support${Platform.pathSeparator}logs');
  final supervisor = EngineSupervisor(
    logDir: logs.path,
    port: enginePort,
    resolve: (port) => resolveEngine(host, resourceDir: resourceDir(), port: port),
    workingDirectory: () => engineWorkingDirectory(host, development: kDebugMode),
  );
  runApp(
    AutoEditApp(
      client: AutoEditClient(EngineConfig.local(port: enginePort)),
      supervisor: supervisor,
      prefs: prefs,
    ),
  );
}

class AutoEditApp extends StatefulWidget {
  const AutoEditApp({
    super.key,
    required this.client,
    this.supervisor,
    required this.prefs,
    this.pickers,
    this.remote,
    this.onUnpair,
    this.navigatorKey,
    this.watcher,
  });

  final AutoEditClient client;
  final AppPrefs prefs;

  /// The OS dialogs; tests answer them.
  final Pickers? pickers;

  /// Starts and stops the local engine. Null: only talk to [client] (tests,
  /// or the computer the phone is paired with).
  final EngineSupervisor? supervisor;

  /// On the phone: the paired computer's name, and forgetting it.
  final String? remote;
  final VoidCallback? onUnpair;

  final GlobalKey<NavigatorState>? navigatorKey;

  /// Says when an edit finishes (a notification on the phone).
  final EditWatcher? watcher;

  @override
  State<AutoEditApp> createState() => _AutoEditAppState();
}

class _AutoEditAppState extends State<AutoEditApp> {
  late final EngineStatus _status;
  late final AppLifecycleListener _lifecycle;
  String? _startError;

  @override
  void initState() {
    super.initState();
    final supervisor = widget.supervisor;
    _status = EngineStatus(health: widget.client.api.health, onRestart: supervisor?.restart)..start();
    // The engine this app started dies with it.
    _lifecycle = AppLifecycleListener(
      onExitRequested: () async {
        await supervisor?.stop();
        return AppExitResponse.exit;
      },
    );
    if (supervisor != null) unawaited(_startEngine(supervisor));
    widget.watcher?.start();
  }

  Future<void> _startEngine(EngineSupervisor supervisor) async {
    try {
      final how = await supervisor.start();
      debugPrint('[auto-edit] engine ${how.name} on 127.0.0.1:${supervisor.port} (log: ${supervisor.logPath})');
    } catch (e) {
      // Not fatal: the boot screen keeps waiting for one started by hand.
      debugPrint('[auto-edit] could not start engine: $e');
      if (mounted) setState(() => _startError = '$e');
    }
    unawaited(_status.check());
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    _status.dispose();
    widget.watcher?.dispose();
    unawaited(widget.supervisor?.stop());
    widget.client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Auto-Edit',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      navigatorKey: widget.navigatorKey,
      home: ListenableBuilder(
        listenable: _status,
        builder: (context, _) => _status.everConnected
            ? Shell(
                status: _status,
                client: widget.client,
                prefs: widget.prefs,
                pickers: widget.pickers ?? const NativePickers(),
                remote: widget.remote,
                onUnpair: widget.onUnpair,
              )
            : BootScreen(startError: _startError, remote: widget.remote, onUnpair: widget.onUnpair),
      ),
    );
  }
}

import 'dart:async';
import 'dart:io';
import 'dart:ui';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import 'engine/locator.dart';
import 'engine/status.dart';
import 'engine/supervisor.dart';
import 'platform.dart';
import 'ui/boot.dart';
import 'ui/shell.dart';
import 'ui/theme.dart';

const enginePort = 8760;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final host = Host(repoRoot: findRepoRoot([Directory.current.path, File(Platform.resolvedExecutable).parent.path]));
  final support = (await getApplicationSupportDirectory()).path;
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
      prefs: AppPrefs(File('$support${Platform.pathSeparator}prefs.json')),
    ),
  );
}

class AutoEditApp extends StatefulWidget {
  const AutoEditApp({super.key, required this.client, this.supervisor, required this.prefs, this.pickers});

  final AutoEditClient client;
  final AppPrefs prefs;

  /// The OS dialogs; tests answer them.
  final Pickers? pickers;

  /// Starts and stops the local engine. Null: only talk to [client] (tests,
  /// or a remote engine later).
  final EngineSupervisor? supervisor;

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
      home: ListenableBuilder(
        listenable: _status,
        builder: (context, _) => _status.everConnected
            ? Shell(
                status: _status,
                client: widget.client,
                prefs: widget.prefs,
                pickers: widget.pickers ?? const NativePickers(),
              )
            : BootScreen(startError: _startError),
      ),
    );
  }
}

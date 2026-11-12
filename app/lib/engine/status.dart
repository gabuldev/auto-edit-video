import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';

/// The engine as the sidebar shows it: connected, not answering, restarting.
///
/// Asks `/api/health` every [okInterval] while it answers and every
/// [offInterval] once it stops; still silent after [restartAfter], the app
/// offers "Reiniciar o motor" (when [onRestart] exists: only an engine the app
/// can start).
class EngineStatus extends ChangeNotifier {
  EngineStatus({
    required this.health,
    this.onRestart,
    this.okInterval = const Duration(seconds: 5),
    this.offInterval = const Duration(milliseconds: 1500),
    this.restartAfter = const Duration(seconds: 10),
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;

  final Future<Health> Function() health;
  final Future<void> Function()? onRestart;
  final Duration okInterval;
  final Duration offInterval;
  final Duration restartAfter;
  final DateTime Function() _clock;

  /// null until the first answer (or failure).
  bool? get ok => _ok;
  bool? _ok;

  /// The last health that came back.
  Health? get info => _info;
  Health? _info;

  bool get restarting => _restarting;
  bool _restarting = false;

  /// Why the last restart failed, if it did.
  String? get error => _error;
  String? _error;

  /// Has it ever answered (the boot screen waits for this).
  bool get everConnected => _info != null;

  DateTime? _offSince;
  Timer? _timer;
  bool _disposed = false;

  bool get canRestart => onRestart != null;

  /// Off for long enough that waiting is not going to fix it.
  bool get stuck =>
      _ok == false && !_restarting && _offSince != null && _clock().difference(_offSince!) >= restartAfter;

  void start() {
    _timer?.cancel();
    unawaited(check());
  }

  /// Asks the engine now (a screen that saw a request fail can call this).
  Future<void> check() async {
    _timer?.cancel();
    try {
      _info = await health();
      _set(true);
    } catch (_) {
      _set(false);
    }
    if (!_disposed) _timer = Timer(_ok == true ? okInterval : offInterval, check);
  }

  void _set(bool ok) {
    if (!ok && _ok != false) _offSince = _clock();
    if (ok) _error = null;
    _ok = ok;
    _notify();
  }

  Future<void> restart() async {
    final run = onRestart;
    if (run == null || _restarting) return;
    _restarting = true;
    _error = null;
    _notify();
    try {
      await run();
    } catch (e) {
      _restarting = false;
      _error = '$e';
      _notify();
      return;
    }
    // The engine takes a few seconds to load.
    for (var i = 0; i < 60 && !_disposed; i++) {
      try {
        _info = await health();
        _restarting = false;
        _set(true);
        return;
      } catch (_) {
        await Future<void>.delayed(const Duration(milliseconds: 500));
      }
    }
    _restarting = false;
    _offSince = _clock();
    _error = 'Subiu, mas não respondeu. Veja o engine.log do app.';
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}

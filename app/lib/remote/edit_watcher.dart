import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Shows a notification (the OS one on the phone; a fake in tests).
abstract class Notifier {
  Future<void> init();
  Future<void> show(int id, String title, String body);
}

/// Watches the library and says when an edit that was running finishes or
/// fails ("Edição pronta"), while the app is open or in the background.
class EditWatcher {
  EditWatcher(this.client, this.notifier, {this.every = const Duration(seconds: 20)});

  final AutoEditClient client;
  final Notifier notifier;
  final Duration every;

  /// The status each video had at the last look.
  final _last = <String, VideoStatus>{};
  Timer? _timer;
  bool _first = true;

  void start() {
    unawaited(notifier.init().then((_) {}, onError: (_) {}));
    unawaited(check());
    _timer = Timer.periodic(every, (_) => check());
  }

  Future<void> check() async {
    final List<VideoSummary> videos;
    try {
      videos = (await client.api.listLibrary()).videos;
    } catch (_) {
      return; // offline: the next look catches up
    }
    for (final v in videos) {
      final before = _last[v.id];
      _last[v.id] = v.status;
      if (_first || before == null) continue; // only changes seen by this app
      final wasBusy = before == VideoStatus.running || before == VideoStatus.queued;
      if (!wasBusy) continue;
      final name = v.name ?? v.title ?? v.videoName;
      if (v.status == VideoStatus.done) {
        await notifier.show(v.id.hashCode, 'Edição pronta', '$name está pronto pra ver e publicar.');
      } else if (v.status == VideoStatus.failed) {
        await notifier.show(v.id.hashCode, 'A edição parou', '$name falhou no stage ${v.currentStage ?? '?'}.');
      }
    }
    _first = false;
  }

  void dispose() => _timer?.cancel();
}

class LocalNotifier implements Notifier {
  final _plugin = FlutterLocalNotificationsPlugin();

  @override
  Future<void> init() async {
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(),
      ),
    );
    await _plugin
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
  }

  @override
  Future<void> show(int id, String title, String body) => _plugin.show(
    id: id,
    title: title,
    body: body,
    notificationDetails: const NotificationDetails(
      android: AndroidNotificationDetails('edits', 'Edições', importance: Importance.high, priority: Priority.high),
      iOS: DarwinNotificationDetails(),
    ),
  );
}

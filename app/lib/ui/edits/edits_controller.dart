import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';

import '../format.dart';
import '../widgets.dart';

/// The stages in pipeline order (library.js `STAGES`).
const stages = ['extract', 'plan', 'review', 'evaluate', 'execute', 'overlay', 'caption', 'metadata', 'thumbnail'];

/// The video's real name: the one given on Novo edit, else its title once
/// metadata ran, the context typed before that, and only then the file name.
String editName(VideoSummary v) => v.name ?? v.title ?? v.context ?? v.videoName;

bool isStoppable(VideoSummary v) => v.status == VideoStatus.running || v.status == VideoStatus.queued;

/// What a running row shows while its SSE stream delivers.
class Live {
  Live({this.stage, this.line});
  String? stage;
  String? line;
}

/// Edições (desktop/ui/js/library.js): the workspaces, polled every 5s, and a
/// live SSE stream for each running one (stage and last log line).
class EditsController extends ChangeNotifier {
  EditsController(this.client, {this.every = const Duration(seconds: 5)});

  final AutoEditClient client;
  final Duration every;
  AutoEditApi get _api => client.api;

  /// Null until the first answer.
  List<VideoSummary>? videos;
  String? error;
  bool offline = false;
  String query = '';

  final Set<String> selected = {};

  /// The row asking "are you sure?" (stop or delete), and which.
  (String, String)? armed;

  bool bulkArmed = false;

  /// While deleting the selection: (done, total).
  (int, int)? bulkBusy;

  final Map<String, Live> live = {};
  final Map<String, StreamSubscription<JobEvent>> _streams = {};

  /// Ids whose stream 404'd: the workspace reads "running" but the engine has
  /// no live job (it was restarted mid-edit). Not reopened on every poll.
  final Set<String> _noStream = {};
  Timer? _poll;
  bool _disposed = false;

  void start() {
    unawaited(refresh());
    // A video deleted on YouTube stops being "Publicado" (the engine asks at
    // most once a minute).
    unawaited(
      _api.youtubeRefresh().then((r) {
        if (r.changed) unawaited(refresh());
      }, onError: (_) {}),
    );
    _poll = Timer.periodic(every, (_) => refresh());
  }

  List<VideoSummary> get shown => [
    for (final v in videos ?? const <VideoSummary>[])
      if (matchesQuery(query, [
        v.name,
        v.title,
        v.context,
        v.videoName,
        baseName(v.videoPath),
        baseName(v.output),
        v.derivedFrom,
        v.type.value,
        if (v.status == VideoStatus.done && v.published != null) 'publicado',
      ]))
        v,
  ];

  int get running => (videos ?? const []).where((v) => v.status == VideoStatus.running).length;

  Future<void> refresh() async {
    try {
      final list = (await _api.listLibrary()).videos;
      videos = list;
      offline = false;
      if (bulkBusy == null) selected.removeWhere((id) => !list.any((v) => v.id == id)); // gone
      for (final v in list) {
        if (v.status == VideoStatus.running) _subscribe(v.id);
      }
      for (final id in _streams.keys.toList()) {
        if (!list.any((v) => v.id == id && v.status == VideoStatus.running)) _close(id);
      }
    } catch (_) {
      // The offline banner says so; keep what is on screen (an empty list would lie).
      offline = true;
    }
    _notify();
  }

  void _subscribe(String id) {
    if (_streams.containsKey(id) || _noStream.contains(id)) return;
    live[id] = Live();
    _streams[id] = _api
        .videoEvents(id)
        .listen(
          (ev) {
            final l = live[id] ??= Live();
            switch (ev.type) {
              case 'stage':
                l.stage = ev.stage;
              case 'log':
                final line = ev.line ?? '';
                l.line = line.length > 90 ? line.substring(0, 90) : line;
              case 'done' || 'error':
                _close(id);
                unawaited(refresh());
            }
            _notify();
          },
          onError: (Object e) {
            _close(id);
            _noStream.add(id);
          },
          onDone: () => _close(id),
          cancelOnError: true,
        );
  }

  void _close(String id) {
    unawaited(_streams.remove(id)?.cancel());
    live.remove(id);
  }

  /// The stage a row is on: the live one while streaming, else the saved one.
  String? stageOf(VideoSummary v) => live[v.id]?.stage ?? v.currentStage;

  /// Each stage this video runs (a short never overlays, a long never
  /// captions) and how far it got.
  List<(String, String)> dots(VideoSummary v) {
    final current = stageOf(v);
    final i = stages.indexOf(current ?? '');
    return [
      for (final (idx, s) in stages.indexed)
        if (v.stages[s] != 'skip')
          (
            s,
            current == 'done' || (live.containsKey(v.id) && i >= 0 && idx < i) || v.stages[s] == 'complete'
                ? 'done'
                : s == current && v.status == VideoStatus.running
                ? 'cur'
                : s == current && v.status == VideoStatus.failed
                ? 'err'
                : '',
          ),
    ];
  }

  void setQuery(String q) {
    query = q;
    _notify();
  }

  // ── one row: stop / delete, asking first in the row ───────────────────────

  Future<void> act(String id, String what) async {
    if (armed != (id, what)) {
      armed = (id, what);
      _notify();
      return;
    }
    armed = null;
    error = null;
    _notify();
    try {
      if (what == 'stop') {
        await _api.stopVideo(id);
      } else {
        _close(id);
        await _api.deleteVideo(id);
      }
    } catch (e) {
      error = 'Não deu pra ${what == 'stop' ? 'cancelar' : 'excluir'}: ${errorText(e)}';
    }
    await refresh();
  }

  void disarm() {
    armed = null;
    _notify();
  }

  // ── several at once ───────────────────────────────────────────────────────

  void select(String id, bool on) {
    on ? selected.add(id) : selected.remove(id);
    bulkArmed = false;
    _notify();
  }

  void selectAll(bool on) {
    for (final v in shown) {
      on ? selected.add(v.id) : selected.remove(v.id);
    }
    bulkArmed = false;
    _notify();
  }

  void clearSelection() {
    selected.clear();
    bulkArmed = false;
    _notify();
  }

  void armBulk(bool on) {
    bulkArmed = on;
    _notify();
  }

  int get selectedRunning => (videos ?? const []).where((v) => selected.contains(v.id) && isStoppable(v)).length;

  Future<void> deleteSelected() async {
    final ids = selected.toList();
    bulkArmed = false;
    bulkBusy = (0, ids.length);
    error = null;
    _notify();
    final failed = <String>[];
    for (final (i, id) in ids.indexed) {
      _close(id);
      try {
        await _api.deleteVideo(id);
        selected.remove(id);
      } catch (e) {
        final v = videos?.where((x) => x.id == id).firstOrNull;
        failed.add('${v == null ? id : editName(v)} (${errorText(e)})');
      }
      bulkBusy = (i + 1, ids.length);
      _notify();
    }
    bulkBusy = null;
    if (failed.isNotEmpty) {
      error = 'Não deu pra excluir ${failed.length == 1 ? 'esta' : 'estas'}: ${failed.join('; ')}';
    }
    await refresh();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    for (final id in _streams.keys.toList()) {
      _close(id);
    }
    super.dispose();
  }
}

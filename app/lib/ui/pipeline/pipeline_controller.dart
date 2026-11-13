import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';

import '../edits/edits_controller.dart' show stages;
import '../widgets.dart';

/// What each stage does, under its name (pipeline.js `STAGE_HINT`).
const stageHint = {
  'extract': 'Whisper transcreve o áudio',
  'plan': 'O planner decide os cortes',
  'review': 'O reviewer confere o plano',
  'evaluate': 'Julga o corte planejado (antes de renderizar) e aprova ou devolve pro plan',
  'execute': 'FFmpeg corta o vídeo',
  'overlay': 'Lower third e CTA na tela',
  'caption': 'Legenda animada estilo CapCut',
  'metadata': 'Título, descrição e tags',
  'thumbnail': 'Escolhe o frame de capa',
};

/// The log keeps this many lines (FFmpeg prints several a second).
const maxLogLines = 500;

/// The stages this video runs: a short never overlays, a long never captions.
List<String> stagesOf(VideoDetail d) => [
  for (final s in stages)
    if (d.stageDetail[s]?['status'] != 'skip') s,
];

/// One stage's state as the list shows it: ralph only marks a stage when it
/// gets that far, so a run that died on the way in leaves "pending" on the
/// current one, which would contradict the header's "Falhou".
String stageState(VideoDetail d, String name) {
  final status = (d.stageDetail[name]?['status'] as String?) ?? 'pending';
  if (name == d.currentStage && (status == 'pending' || status == 'running')) {
    if (d.status == VideoStatus.failed) return 'failed';
    if (d.status == VideoStatus.running) return 'running';
  }
  return status;
}

/// Pipeline ao vivo (desktop/ui/js/pipeline.js): one workspace, polled every
/// 5s, with its job's log over SSE, "Retomar a partir de" and "Parar".
class PipelineController extends ChangeNotifier {
  PipelineController(this.client, this.id, {this.every = const Duration(seconds: 5)});

  final AutoEditClient client;
  final String id;
  final Duration every;
  AutoEditApi get _api => client.api;

  VideoDetail? detail;
  String? error;

  /// The stage picked in "Retomar a partir de" (null: the current one).
  String? resumeFrom;
  bool resuming = false;

  /// "Parar" asks once; the second click stops.
  bool stopArmed = false;
  bool stopping = false;

  final List<String> lines = [];

  /// Bumped on every new line, so the log view knows to scroll.
  int logVersion = 0;

  StreamSubscription<JobEvent>? _stream;
  Timer? _poll;
  Timer? _disarm;
  bool _disposed = false;

  bool get streaming => _stream != null;

  void start() {
    unawaited(load());
    openStream();
    _poll = Timer.periodic(every, (_) => load());
  }

  Future<void> load() async {
    try {
      final d = await _api.getVideo(id);
      detail = d;
      error = null;
      final runs = stagesOf(d);
      if (resumeFrom != null && !runs.contains(resumeFrom)) resumeFrom = null;
      if (d.status != VideoStatus.running && d.status != VideoStatus.queued) {
        stopArmed = false;
      }
    } catch (e) {
      error = 'Não deu pra ler esse vídeo: ${errorText(e)}';
    }
    _notify();
  }

  /// The stage the picker shows: the one chosen, else the current stage.
  String? get resumeStage {
    final d = detail;
    if (d == null) return null;
    final runs = stagesOf(d);
    if (resumeFrom != null) return resumeFrom;
    if (d.currentStage != null && runs.contains(d.currentStage)) return d.currentStage;
    return runs.firstOrNull;
  }

  bool get live => detail?.status == VideoStatus.running;
  bool get stoppable => live || detail?.status == VideoStatus.queued;

  void pickResume(String? stage) {
    resumeFrom = stage;
    _notify();
  }

  /// The engine replays the job's history on each connection, so the log
  /// starts from the top; a 404 means no live job (the log stays empty).
  void openStream() {
    unawaited(_stream?.cancel());
    _stream = _api
        .videoEvents(id)
        .listen(
          (ev) {
            switch (ev.type) {
              case 'log':
                push(ev.line ?? '');
              case 'stage':
                push('── stage: ${ev.stage} ──');
                unawaited(load());
              case 'done':
                push('── terminou ──');
                _closeStream();
                unawaited(load());
              case 'error':
                push('── falhou${ev.stage != null ? ' no stage ${ev.stage}' : ''} ──');
                _closeStream();
                unawaited(load());
            }
          },
          onError: (Object _) => _closeStream(),
          onDone: _closeStream,
          cancelOnError: true,
        );
  }

  void _closeStream() {
    unawaited(_stream?.cancel());
    _stream = null;
    _notify();
  }

  void push(String line) {
    lines.add(line);
    if (lines.length > maxLogLines * 1.5) lines.removeRange(0, lines.length - maxLogLines);
    logVersion++;
    _notify();
  }

  Future<void> resume() async {
    final stage = resumeStage;
    if (stage == null || resuming) return;
    resuming = true;
    error = null;
    _notify();
    try {
      await _api.resumeVideo(id, ResumeVideoRequest(fromStage: stage));
      lines.clear();
      push('── retomando de $stage ──');
      resumeFrom = null;
      openStream();
      await load();
    } catch (e) {
      error = errorText(e);
    } finally {
      resuming = false;
      _notify();
    }
  }

  Future<void> stop() async {
    if (!stopArmed) {
      stopArmed = true;
      _disarm?.cancel();
      _disarm = Timer(const Duration(seconds: 4), () {
        stopArmed = false;
        _notify();
      });
      _notify();
      return;
    }
    _disarm?.cancel();
    stopArmed = false;
    stopping = true;
    _notify();
    try {
      await _api.stopVideo(id);
      push('── parado ──');
    } catch (e) {
      push('── não deu pra parar: ${errorText(e)} ──');
    } finally {
      stopping = false;
      _closeStream();
      await load();
    }
  }

  /// The original video or the delivered one, shown in its folder.
  Future<void> reveal(String kind) async {
    try {
      await _api.openFile(id, kind, body: const OpenFileRequest(reveal: true));
    } catch (e) {
      error = 'Não deu pra abrir a pasta: ${errorText(e)}';
      _notify();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    _disarm?.cancel();
    unawaited(_stream?.cancel());
    super.dispose();
  }
}

import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../shell.dart';
import '../theme.dart';
import '../widgets.dart';

/// 75.25 → "01:15.3" (cuts.js `tc`).
String timecode(double? seconds) {
  if (seconds == null) return '—';
  final s = seconds < 0 ? 0.0 : seconds;
  final m = s ~/ 60;
  final rest = (s - m * 60).toStringAsFixed(1).padLeft(4, '0');
  return '${m.toString().padLeft(2, '0')}:$rest';
}

/// 75 → "1m15s", 9 → "9s" (cuts.js `dur`).
String shortDuration(double? seconds) {
  if (seconds == null) return '—';
  final m = seconds ~/ 60;
  final s = (seconds % 60).round();
  return m > 0 ? '${m}m${s.toString().padLeft(2, '0')}s' : '${s}s';
}

/// `dropped_blocks` is a list of strings or {reason}, or one of them.
List<String> droppedBlocks(Object? blocks) {
  final list = blocks is List ? blocks : (blocks == null ? const [] : [blocks]);
  return [
    for (final b in list)
      if (b is String) b else if (b is Map && b['reason'] is String) b['reason'] as String else '$b',
  ];
}

/// Revisar cortes (desktop/ui/js/cuts.js): what is left of the video, with
/// what is said in each segment. Unticking a segment and saving rewrites
/// reviewed_plan.json; "Salvar e recortar" also resumes from execute.
class CutsScreen extends StatefulWidget {
  const CutsScreen({super.key, required this.client, required this.id, required this.onBack, required this.onRecut});

  final AutoEditClient client;
  final String id;
  final VoidCallback onBack;

  /// After "Salvar e recortar": the pipeline, running again.
  final VoidCallback onRecut;

  @override
  State<CutsScreen> createState() => _CutsScreenState();
}

class _CutsScreenState extends State<CutsScreen> {
  Plan? _plan;

  /// No plan yet (before plan and review ran).
  bool _none = false;
  String? _error;
  bool _busy = false;
  Set<int> _keep = {};

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  void _show(Plan p) {
    _plan = p;
    _keep = {for (final s in p.keptSegments) s.index};
  }

  Future<void> _load() async {
    try {
      final p = await _api.getPlan(widget.id);
      if (mounted) setState(() => _show(p));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        if (e.isNotFound && e.message == 'no_plan') {
          _none = true;
        } else {
          _error = e.message;
        }
      });
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    }
  }

  List<PlanKeptSegmentsItem> get _kept => [
    for (final s in _plan?.keptSegments ?? const <PlanKeptSegmentsItem>[])
      if (_keep.contains(s.index)) s,
  ];

  Future<void> _save({bool recut = false}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final updated = await _api.savePlan(
        widget.id,
        SavePlanRequest(
          keptSegments: [for (final s in _kept) SegmentInput(start: s.start, end: s.end, summary: s.summary)],
        ),
      );
      if (!mounted) return;
      setState(() => _show(updated));
      if (recut) {
        await _api.resumeVideo(widget.id, const ResumeVideoRequest(fromStage: 'execute'));
        widget.onRecut();
      }
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = _plan;
    final kept = _kept;
    final total = kept.fold<double>(0, (a, s) => a + s.duration);
    const mono = TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.dim);
    final canSave = !_busy && p != null && kept.isNotEmpty;
    final blocks = droppedBlocks(p?.droppedBlocks);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TopBar(
          title: p?.name ?? widget.id,
          onBack: widget.onBack,
          subtitleWidget: p == null
              ? null
              : Padding(
                  padding: const EdgeInsets.only(top: 3),
                  // one line: the draft note gives way in a narrow window
                  child: Row(
                    children: [
                      Text(
                        '${kept.length} de ${p.keptSegments.length} trechos',
                        style: const TextStyle(fontSize: 13, color: Tokens.dim),
                      ),
                      const SizedBox(width: 12),
                      Text('${shortDuration(total)} de corte final', style: mono),
                      if (p.duration != null) ...[
                        const SizedBox(width: 12),
                        Text('bruto ${shortDuration(p.duration)}', style: mono),
                      ],
                      if (!p.editable) ...[
                        const SizedBox(width: 12),
                        Flexible(
                          child: Text(
                            'rascunho do planner (${p.source}) — salvar cria o reviewed_plan',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: mono,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
          actions: [
            OutlinedButton(onPressed: canSave ? _save : null, child: const Text('Salvar plano')),
            const SizedBox(width: 8),
            FilledButton(onPressed: canSave ? () => _save(recut: true) : null, child: const Text('Salvar e recortar')),
          ],
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
            children: [
              if (_error != null) Notice(_error!),
              if (_none)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Text(
                    'Este vídeo ainda não tem plano de cortes — ele aparece depois dos stages plan e review.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Tokens.dim),
                  ),
                ),
              if (p == null && !_none && _error == null)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(child: CircularProgressIndicator()),
                ),
              if (p != null) ...[
                if (blocks.isNotEmpty)
                  Panel(
                    title: 'Blocos descartados',
                    subtitle: const Text('Curadoria editorial do planner de vídeos long.'),
                    children: [
                      for (final b in blocks)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Text('•  $b', style: const TextStyle(fontSize: 13.5, height: 1.45)),
                        ),
                    ],
                  ),
                const Padding(
                  padding: EdgeInsets.only(bottom: 10),
                  child: Row(
                    children: [
                      Text('Trechos mantidos', style: TextStyle(fontWeight: FontWeight.w600)),
                      SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'desmarque o que não deve entrar no corte final',
                          style: TextStyle(fontSize: 12.5, color: Tokens.dim),
                        ),
                      ),
                    ],
                  ),
                ),
                if (p.keptSegments.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(28),
                    child: Text(
                      'O plano não tem trechos mantidos.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Tokens.dim),
                    ),
                  ),
                for (final s in p.keptSegments)
                  _Segment(
                    s: s,
                    on: _keep.contains(s.index),
                    onChanged: _busy ? null : (on) => setState(() => on ? _keep.add(s.index) : _keep.remove(s.index)),
                  ),
                if (p.cuts.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 14),
                    child: Material(
                      color: Tokens.panel,
                      shape: RoundedRectangleBorder(
                        side: const BorderSide(color: Tokens.border),
                        borderRadius: BorderRadius.circular(14),
                      ),
                      clipBehavior: Clip.antiAlias,
                      child: ExpansionTile(
                        title: Text(
                          'O que o planner já cortou (${p.cuts.length})',
                          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                        ),
                        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                        children: [for (final cut in p.cuts) _Cut(cut)],
                      ),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _Segment extends StatelessWidget {
  const _Segment({required this.s, required this.on, required this.onChanged});
  final PlanKeptSegmentsItem s;
  final bool on;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final summary = s.summary;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Opacity(
        opacity: on ? 1 : .55,
        child: Material(
          color: Tokens.panel,
          shape: RoundedRectangleBorder(
            side: const BorderSide(color: Tokens.borderSoft),
            borderRadius: BorderRadius.circular(12),
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: onChanged == null ? null : () => onChanged!(!on),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(6, 8, 14, 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Checkbox(value: on, onChanged: onChanged == null ? null : (x) => onChanged!(x ?? false)),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(top: 10),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Wrap(
                            spacing: 12,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              Text(
                                '${timecode(s.start)} → ${timecode(s.end)}',
                                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.accent),
                              ),
                              Text(
                                shortDuration(s.duration),
                                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.faint),
                              ),
                              if (summary != null && summary.isNotEmpty)
                                Text(summary, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(
                            s.text.isNotEmpty ? s.text : '(sem transcrição para este trecho)',
                            style: TextStyle(
                              fontSize: 13.5,
                              height: 1.5,
                              color: s.text.isEmpty ? Tokens.faint : Tokens.dim,
                              fontStyle: s.text.isEmpty ? FontStyle.italic : null,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Cut extends StatelessWidget {
  const _Cut(this.cut);
  final PlanCutsItem cut;

  @override
  Widget build(BuildContext context) {
    const mono = TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.faint);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 150, child: Text('${timecode(cut.start)} → ${timecode(cut.end)}', style: mono)),
          SizedBox(width: 60, child: Text(shortDuration(cut.duration), style: mono)),
          Expanded(
            child: Text(cut.reason ?? '—', style: const TextStyle(fontSize: 13, color: Tokens.dim)),
          ),
          if (cut.type != null) ...[const SizedBox(width: 10), Text(cut.type!, style: mono)],
        ],
      ),
    );
  }
}

import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../../platform.dart';
import '../format.dart';
import '../player.dart';
import '../theme.dart';
import '../widgets.dart';

/// "1:05.5" / "65.5" / "65,5" → seconds (null if it isn't a time).
double? parseTime(String text) {
  final t = text.trim().replaceAll(',', '.');
  if (t.isEmpty) return null;
  final parts = t.split(':');
  if (parts.length > 3) return null;
  var total = 0.0;
  for (final p in parts) {
    final v = double.tryParse(p);
    if (v == null || v < 0) return null;
    total = total * 60 + v;
  }
  return total;
}

/// 65.5 → "1:05.5".
String clock(double s) {
  final m = s ~/ 60;
  final rest = s - m * 60;
  final sec = rest.toStringAsFixed(1).padLeft(4, '0');
  return '$m:$sec';
}

/// Efeitos e cortes, on Resultado: zoom and B-roll on a stretch of the video
/// (marked with the player's time), cutting a stretch out, and the re-render
/// that applies them. The times typed are the edited video's (what you
/// watch); the list shows them in the original recording, as the engine keeps them.
class EffectsPanel extends StatefulWidget {
  const EffectsPanel({
    super.key,
    required this.client,
    required this.id,
    required this.pickers,
    required this.control,
    required this.onRerender,
  });

  final AutoEditClient client;
  final String id;
  final Pickers pickers;
  final PlayerControl control;

  /// After "Refazer o render": the pipeline, running it.
  final VoidCallback onRerender;

  @override
  State<EffectsPanel> createState() => _EffectsPanelState();
}

class _EffectsPanelState extends State<EffectsPanel> {
  Effects? _e;
  String? _error;
  String? _note;
  bool _busy = false;

  /// What the form adds: zoom, broll or cut.
  String _kind = 'zoom';
  final _start = TextEditingController();
  final _end = TextEditingController();
  double _scale = 1.2;
  String? _file;

  /// Something changed since the last render (the button says so).
  bool _pending = false;

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _start.dispose();
    _end.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final e = await _api.listEffects(widget.id);
      if (mounted) setState(() => _e = e);
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    }
  }

  void _mark(TextEditingController c) {
    final s = widget.control.position.inMilliseconds / 1000;
    c.text = clock(s);
    setState(() {});
  }

  (double, double)? get _window {
    final a = parseTime(_start.text), b = parseTime(_end.text);
    if (a == null || b == null || b <= a) return null;
    return (a, b);
  }

  Future<void> _add() async {
    final w = _window;
    if (w == null) {
      setState(() => _error = 'Marque o começo e o fim (o fim depois do começo).');
      return;
    }
    if (_kind == 'broll' && _file == null) {
      setState(() => _error = 'Escolha a imagem ou o vídeo do B-roll.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _note = null;
    });
    try {
      if (_kind == 'cut') {
        final r = await _api.cutRange(widget.id, CutRangeRequest(start: w.$1, end: w.$2, timeline: Timeline.edited));
        _note = 'Trecho ${clock(w.$1)}–${clock(w.$2)} sai do vídeo (${r.keptSegments.length} trechos ficam).';
      } else {
        final e = await _api.addEffect(
          widget.id,
          EffectInput(
            type: _kind,
            start: w.$1,
            end: w.$2,
            scale: _kind == 'zoom' ? _scale : null,
            file: _kind == 'broll' ? _file : null,
            timeline: Timeline.edited,
          ),
        );
        _e = e;
      }
      _pending = true;
      _start.clear();
      _end.clear();
    } catch (e) {
      _error = errorText(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(int index) async {
    try {
      final e = await _api.removeEffect(widget.id, index);
      setState(() {
        _e = e;
        _pending = true;
      });
    } catch (e) {
      setState(() => _error = errorText(e));
    }
  }

  Future<void> _rerender() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _api.resumeVideo(widget.id, ResumeVideoRequest(fromStage: _e?.rerenderFrom ?? 'execute'));
      widget.onRerender();
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final e = _e;
    const mono = TextStyle(fontFamily: Tokens.mono, fontSize: 12.5);
    return Panel(
      title: 'Efeitos e cortes',
      subtitle: const Text(
        'Zoom ou B-roll num trecho, ou tirar um trecho. Use o tempo do vídeo acima; '
        'vale quando você refizer o render.',
      ),
      children: [
        if (_error != null) Notice(_error!),
        if (_note != null) Notice(_note!, tone: Tone.ok),
        for (final n in e?.notes ?? const <String>[]) Notice(n, tone: Tone.info),
        if (e != null && e.effects.isNotEmpty) ...[
          for (final fx in e.effects)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                children: [
                  SizedBox(
                    width: 80,
                    child: Badge2(
                      fx.type == 'zoom' ? 'zoom' : 'B-roll',
                      color: fx.type == 'zoom' ? Tokens.accent : Tokens.info,
                    ),
                  ),
                  Text('${clock(fx.start)} – ${clock(fx.end)}', style: mono),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      fx.type == 'zoom' ? '${((fx.scale ?? 1.2) * 100).round()}%' : baseName(fx.file),
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 13, color: Tokens.dim),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Remover',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => _remove(fx.index),
                    icon: const Icon(Icons.close, size: 18),
                  ),
                ],
              ),
            ),
          const Padding(
            padding: EdgeInsets.only(bottom: 10),
            child: Text(
              'Os tempos da lista são do vídeo original (o motor guarda assim).',
              style: TextStyle(fontSize: 12, color: Tokens.faint),
            ),
          ),
        ],
        SegmentedButton<String>(
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(value: 'zoom', label: Text('Zoom'), icon: Icon(Icons.zoom_in, size: 17)),
            ButtonSegment(value: 'broll', label: Text('B-roll'), icon: Icon(Icons.image_outlined, size: 17)),
            ButtonSegment(value: 'cut', label: Text('Cortar trecho'), icon: Icon(Icons.content_cut, size: 17)),
          ],
          selected: {_kind},
          onSelectionChanged: (s) => setState(() => _kind = s.first),
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 14,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            _timeField('Começo', _start),
            _timeField('Fim', _end),
            if (_kind == 'zoom')
              SizedBox(
                width: 220,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Zoom ${(_scale * 100).round()}%', style: const TextStyle(fontSize: 12.5, color: Tokens.dim)),
                    Slider(
                      value: _scale,
                      min: 1.05,
                      max: 2,
                      divisions: 19,
                      onChanged: (v) => setState(() => _scale = double.parse(v.toStringAsFixed(2))),
                    ),
                  ],
                ),
              ),
            if (_kind == 'broll')
              OutlinedButton.icon(
                onPressed: () async {
                  final f = await widget.pickers.broll();
                  if (f != null) setState(() => _file = f);
                },
                icon: const Icon(Icons.attach_file, size: 18),
                label: Text(_file == null ? 'Escolher imagem ou vídeo' : baseName(_file)),
              ),
            FilledButton(onPressed: _busy ? null : _add, child: Text(_kind == 'cut' ? 'Tirar o trecho' : 'Adicionar')),
          ],
        ),
        const Divider(height: 32),
        Row(
          children: [
            Expanded(
              child: Text(
                _pending
                    ? 'Mudou: refaça o render pra ver no vídeo (corta de novo a partir do execute, alguns minutos).'
                    : 'O render refaz o vídeo a partir do execute com os efeitos e cortes de agora.',
                style: TextStyle(fontSize: 13, color: _pending ? Tokens.run : Tokens.dim),
              ),
            ),
            const SizedBox(width: 12),
            if (_pending)
              FilledButton(onPressed: _busy ? null : _rerender, child: const Text('Refazer o render'))
            else
              OutlinedButton(onPressed: _busy ? null : _rerender, child: const Text('Refazer o render')),
          ],
        ),
      ],
    );
  }

  Widget _timeField(String label, TextEditingController c) => SizedBox(
    width: 190,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12.5, color: Tokens.dim)),
        const SizedBox(height: 4),
        TextField(
          controller: c,
          style: const TextStyle(fontFamily: Tokens.mono, fontSize: 13.5),
          onChanged: (_) => setState(() {}),
          decoration: fieldDecoration(hint: 'm:ss').copyWith(
            suffixIcon: IconButton(
              tooltip: 'Usar o tempo do player',
              onPressed: () => _mark(c),
              icon: const Icon(Icons.my_location, size: 18),
            ),
          ),
        ),
      ],
    ),
  );
}

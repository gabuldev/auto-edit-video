import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../theme.dart';
import '../widgets.dart';

/// position / offset / size / hidden: the only things a short's caption
/// adjust changes (the rest comes from the style).
class Adjust {
  const Adjust({this.position = 'bottom', this.offset = 33, this.size = 100, this.hidden = false});

  final String position;
  final double offset;
  final double size;
  final bool hidden;

  Adjust copyWith({String? position, double? offset, double? size, bool? hidden}) => Adjust(
    position: position ?? this.position,
    offset: offset ?? this.offset,
    size: size ?? this.size,
    hidden: hidden ?? this.hidden,
  );

  CaptionAdjust toApi() => CaptionAdjust(position: position, offset: offset, size: size, hidden: hidden);

  @override
  bool operator ==(Object other) =>
      other is Adjust &&
      other.position == position &&
      other.offset == offset &&
      other.size == size &&
      other.hidden == hidden;

  @override
  int get hashCode => Object.hash(position, offset, size, hidden);
}

double _clamp(num v, num lo, num hi) => math.min(hi, math.max(lo, v)).toDouble();

/// The band's height as a fraction of the video: about one caption line,
/// following the size (caption-adjust.js `bandH`).
double bandHeight(Adjust a) => 0.07 * _clamp(a.size, 50, 200) / 100;

/// The band's top edge (0–1). libass anchors the text by its edge: bottom →
/// the bottom edge sits at (1 − offset); top → the top edge at offset.
double bandTop(Adjust a) {
  final off = _clamp(a.offset, 0, 40) / 100;
  final h = bandHeight(a);
  if (a.position == 'top') return off;
  if (a.position == 'middle') return 0.5 - h / 2;
  return 1 - off - h;
}

/// position/offset from where the band's top edge was dropped.
Adjust fromTop(Adjust a, double top) {
  final h = bandHeight(a);
  final c = _clamp(top, 0, 1 - h) + h / 2;
  if (c < 0.4) return a.copyWith(position: 'top', offset: _clamp(((c - h / 2) * 100).round(), 0, 40));
  if (c > 0.6) return a.copyWith(position: 'bottom', offset: _clamp(((1 - c - h / 2) * 100).round(), 0, 40));
  return a.copyWith(position: 'middle');
}

/// Ajustar legenda (desktop/ui/js/caption-adjust.js), beside a finished
/// short's player: "Ajustar legenda" swaps the video for the engine's preview
/// (a frame with the caption where it will be) and a band dragged up or
/// down; size and "esconder" on the side. Nothing is saved until "Regravar
/// legenda" (PUT, then resume from caption, caption only); "Cancelar" goes
/// back to what was saved.
class CaptionAdjuster extends StatefulWidget {
  const CaptionAdjuster({
    super.key,
    required this.client,
    required this.id,
    required this.player,
    required this.ratio,
    required this.onAdjusting,
    required this.onRecorded,
    this.debounce = const Duration(milliseconds: 350),
  });

  final AutoEditClient client;
  final String id;
  final Widget player;
  final double ratio;
  final ValueChanged<bool> onAdjusting;
  final VoidCallback onRecorded;
  final Duration debounce;

  @override
  State<CaptionAdjuster> createState() => _CaptionAdjustState();
}

class _CaptionAdjustState extends State<CaptionAdjuster> {
  Captions? _c;
  Adjust _saved = const Adjust();
  Adjust _a = const Adjust();
  bool _editing = false;
  bool _busy = false;
  bool _loadingPreview = false;
  String? _error;
  Uint8List? _png;
  Timer? _timer;
  int _seq = 0;

  /// While dragging: the band's top (0–1).
  double? _dragTop;

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final c = await _api.getCaptions(widget.id);
      final style = c.captions;
      final adj = c.adjust;
      final a = Adjust(
        position: adj.position ?? (style['position'] as String?) ?? 'bottom',
        offset: adj.offset ?? (style['offset'] as num?)?.toDouble() ?? 33,
        size: adj.size ?? (style['size'] as num?)?.toDouble() ?? 100,
        hidden: adj.hidden ?? (style['hidden'] as bool?) ?? false,
      );
      if (mounted) {
        setState(() {
          _c = c;
          _saved = a;
          _a = a;
        });
      }
    } catch (_) {
      // No captions route / no caption: there is simply no adjusting.
    }
  }

  String? get _blocked => _c == null || _c!.fast || _c!.sourceOk
      ? null
      : 'O vídeo original não está mais em ${_c!.videoPath.isEmpty ? '(sem caminho)' : _c!.videoPath}; '
            'sem ele não dá pra recortar e regravar a legenda';

  void _preview({bool now = false}) {
    _timer?.cancel();
    _timer = Timer(now ? Duration.zero : widget.debounce, () async {
      final seq = ++_seq;
      setState(() => _loadingPreview = true);
      try {
        final png = await _api.previewCaptions(widget.id, body: _a.toApi());
        if (!mounted || seq != _seq) return;
        setState(() {
          _png = png;
          _error = null;
        });
      } catch (e) {
        if (mounted && seq == _seq) setState(() => _error = errorText(e));
      } finally {
        if (mounted && seq == _seq) setState(() => _loadingPreview = false);
      }
    });
  }

  void _edit(bool on) {
    setState(() {
      _editing = on;
      _error = null;
      if (!on) _a = _saved;
    });
    widget.onAdjusting(on);
    if (on) _preview(now: true);
  }

  void _set(Adjust a) {
    setState(() => _a = a);
    _preview();
  }

  Future<void> _record() async {
    if (_blocked != null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _api.saveCaptions(widget.id, _a.toApi());
      await _api.resumeVideo(widget.id, const ResumeVideoRequest(fromStage: 'caption', captionOnly: true));
      widget.onAdjusting(false);
      widget.onRecorded();
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final c = _c;
        const panelW = 280.0;
        final h = math.min(560.0, (box.maxWidth - (c == null ? 0 : panelW + 20)) / widget.ratio);
        final w = h * widget.ratio;
        final stage = SizedBox(width: w, height: h, child: _editing ? _stage(w, h) : widget.player);
        if (c == null) return Align(alignment: Alignment.centerLeft, child: stage);
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            stage,
            const SizedBox(width: 20),
            SizedBox(width: panelW, child: _panel(c)),
          ],
        );
      },
    );
  }

  Widget _stage(double w, double h) {
    final top = _dragTop ?? bandTop(_a);
    final bandH = bandHeight(_a);
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: Stack(
        children: [
          const Positioned.fill(child: ColoredBox(color: Colors.black)),
          if (_png != null)
            Positioned.fill(
              child: Image.memory(
                _png!,
                fit: BoxFit.contain,
                gaplessPlayback: true,
                semanticLabel: 'prévia da legenda',
              ),
            ),
          if (_loadingPreview)
            const Positioned(
              right: 10,
              top: 10,
              child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            ),
          if (!_a.hidden)
            Positioned(
              left: 0,
              right: 0,
              top: top * h,
              height: bandH * h,
              child: Tooltip(
                message: 'Arraste pra cima ou pra baixo',
                child: MouseRegion(
                  cursor: SystemMouseCursors.resizeUpDown,
                  child: GestureDetector(
                    key: const Key('caption-band'),
                    onVerticalDragStart: (_) => setState(() => _dragTop = bandTop(_a)),
                    onVerticalDragUpdate: (d) =>
                        setState(() => _dragTop = _clamp((_dragTop ?? bandTop(_a)) + d.delta.dy / h, 0, 1 - bandH)),
                    onVerticalDragEnd: (d) {
                      final dropped = _dragTop;
                      setState(() => _dragTop = null);
                      // a click (barely moved) changes nothing
                      if (dropped == null || (dropped - bandTop(_a)).abs() * h < 4) return;
                      _set(fromTop(_a, dropped));
                    },
                    child: Container(
                      decoration: BoxDecoration(
                        color: Tokens.accent.withValues(alpha: .08),
                        border: Border.all(color: Tokens.accent, width: 1.5),
                      ),
                      alignment: top < 0.08 ? Alignment.bottomCenter : Alignment.topCenter,
                      child: FractionalTranslation(
                        translation: Offset(0, top < 0.08 ? 1 : -1),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          color: Tokens.accent,
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.swap_vert, size: 13, color: Colors.black),
                              SizedBox(width: 3),
                              Text(
                                'arraste pra mover',
                                style: TextStyle(fontSize: 11, color: Colors.black, fontWeight: FontWeight.w600),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _panel(Captions c) {
    final blocked = _blocked;
    final err = _error ?? blocked;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('Legenda', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
        const Padding(
          padding: EdgeInsets.only(top: 4, bottom: 12),
          child: Text('Mude a posição e o tamanho direto no vídeo.', style: TextStyle(fontSize: 13, color: Tokens.dim)),
        ),
        if (err != null) Notice(err),
        if (!_editing) ...[
          const Text(
            '1. Clique em Ajustar legenda: o vídeo pausa e mostra a legenda numa faixa.\n'
            '2. Arraste a faixa pra cima ou pra baixo pra mudar a posição.\n'
            '3. Mude o tamanho e clique em Regravar legenda.',
            style: TextStyle(fontSize: 13, color: Tokens.dim, height: 1.6),
          ),
          const SizedBox(height: 14),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(onPressed: () => _edit(true), child: const Text('Ajustar legenda')),
          ),
        ] else ...[
          Text('Tamanho ${_a.size.round()}%', style: const TextStyle(fontSize: 13)),
          Slider(
            value: _clamp(_a.size, 50, 200),
            min: 50,
            max: 200,
            divisions: 30,
            label: '${_a.size.round()}%',
            onChanged: (v) => _set(_a.copyWith(size: v.roundToDouble())),
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            dense: true,
            value: _a.hidden,
            onChanged: (v) => _set(_a.copyWith(hidden: v ?? false)),
            title: const Text('Esconder legenda', style: TextStyle(fontSize: 13.5)),
          ),
          const SizedBox(height: 10),
          Tooltip(
            message:
                blocked ?? (c.fast ? '' : 'Esse vídeo é de antes desta versão: vai recortar de novo (alguns minutos)'),
            child: FilledButton(
              onPressed: _busy || blocked != null ? null : _record,
              child: Text(c.fast ? 'Regravar legenda' : 'Regravar legenda (vai recortar, alguns minutos)'),
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _busy ? null : () => _edit(false), child: const Text('Cancelar')),
        ],
      ],
    );
  }
}

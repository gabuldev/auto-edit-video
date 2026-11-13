import 'dart:async';
import 'dart:math' as math;

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../format.dart';
import '../player.dart';
import '../theme.dart';
import '../widgets.dart';

/// 0.613 → "61%".
String pct(Object? x) => x is num ? '${(x * 100).round()}%' : '—';

/// 75 → "1:15".
String mmss(num s) {
  final t = math.max(0, s.round());
  return '${t ~/ 60}:${(t % 60).toString().padLeft(2, '0')}';
}

/// A change in percentage points: +3.2 pp / -1.0 pp (empty without one).
String pp(Object? delta) {
  if (delta is! num) return '';
  final v = delta * 100;
  return '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)} pp';
}

/// (t, watching) of a saved curve.
List<(double, double)> curveOf(Object? raw) => [
  for (final p in raw is List ? raw : const [])
    if (p is List && p.length >= 2 && p[0] is num && p[1] is num) ((p[0] as num).toDouble(), (p[1] as num).toDouble()),
];

/// Retenção no YouTube (desktop/ui/js/retention.js), on Resultado of a
/// published video: the curve, 30s/60s/half, this video against the ones
/// before it, and the drops above normal with what was being said; clicking
/// one takes the player there.
class RetentionPanel extends StatefulWidget {
  const RetentionPanel({super.key, required this.client, required this.id, required this.control});

  final AutoEditClient client;
  final String id;
  final PlayerControl control;

  @override
  State<RetentionPanel> createState() => _RetentionPanelState();
}

class _RetentionPanelState extends State<RetentionPanel> {
  Retention? _r;
  String? _error;
  bool _busy = false;

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final r = await _api.getRetention(widget.id);
      if (mounted) setState(() => _r = r);
    } catch (_) {
      // not published / no route: no card
    }
  }

  Future<void> _refresh() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await _api.refreshRetention(widget.id);
      if (mounted) setState(() => _r = r);
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _r;
    if (r == null || r.youtubeId == null) return const SizedBox.shrink();
    final d = r.data;
    final reconnect = !r.account.connected;
    final drops = [for (final x in (d?['drops'] as List?) ?? const []) (x as Map).cast<String, Object?>()];
    final vs = r.versusPrevious;
    return Panel(
      title: 'Retenção no YouTube',
      subtitle: Text(
        d == null
            ? 'Onde o público saiu, com o que era dito.'
            : 'Onde o público saiu, com o que era dito · atualizado ${when(d['fetched_at'] as String?)}',
      ),
      trailing: OutlinedButton(
        onPressed: _busy || reconnect ? null : _refresh,
        child: Text(
          _busy
              ? 'Buscando…'
              : d == null
              ? 'Buscar curva'
              : 'Atualizar',
        ),
      ),
      children: [
        if (_error != null) Notice(_error!),
        if (d == null)
          Text(
            reconnect
                ? 'Conecte (ou reconecte) o YouTube no card de publicar pra ler a retenção.'
                : 'Ainda sem curva. O YouTube costuma liberar 24–48h depois de publicar.',
            style: const TextStyle(fontSize: 13.5, color: Tokens.dim),
          )
        else ...[
          Wrap(
            spacing: 28,
            runSpacing: 12,
            children: [
              for (final (k, label) in [('at_30s', 'aos 30s'), ('at_60s', 'aos 60s'), ('at_half', 'na metade')])
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(pct(d[k]), style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w700)),
                    Text(label, style: const TextStyle(fontSize: 12.5, color: Tokens.dim)),
                    if (vs != null && pp((vs[k] as Map?)?['delta']).isNotEmpty)
                      Text(
                        '${pp((vs[k] as Map?)?['delta'])} vs. anteriores',
                        style: TextStyle(
                          fontSize: 12,
                          fontFamily: Tokens.mono,
                          color: ((vs[k] as Map)['delta'] as num) >= 0 ? Tokens.ok : Tokens.err,
                        ),
                      ),
                  ],
                ),
            ],
          ),
          if (vs != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'Comparado à média dos ${vs['previous']} vídeo(s) do mesmo tipo publicados antes'
                '${vs['lessons'] is int ? ' · planejado com ${vs['lessons']} lição(ões) de retenção' : ''}.',
                style: const TextStyle(fontSize: 12.5, color: Tokens.faint),
              ),
            ),
          const SizedBox(height: 16),
          SizedBox(
            height: 180,
            child: RetentionChart(
              curve: curveOf(d['curve']),
              duration: (d['duration'] as num?)?.toDouble(),
              drops: [
                for (final x in drops)
                  if (x['start'] is num && x['end'] is num)
                    ((x['start'] as num).toDouble(), (x['end'] as num).toDouble()),
              ],
            ),
          ),
          const SizedBox(height: 14),
          if (drops.isEmpty)
            const Text(
              'Nenhuma queda acima do normal — a curva cai de forma regular.',
              style: TextStyle(fontSize: 13, color: Tokens.dim),
            ),
          for (final (i, dr) in drops.indexed)
            Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: BorderRadius.circular(8),
                // a few seconds before: hear what was said as people left
                onTap: () => widget.control.seekTo(
                  Duration(milliseconds: (math.max(0, (dr['start'] as num) - 3) * 1000).round()),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 24,
                        child: Text(
                          '${i + 1}',
                          style: const TextStyle(fontFamily: Tokens.mono, color: Tokens.run),
                        ),
                      ),
                      SizedBox(
                        width: 96,
                        child: Text(
                          '${mmss(dr['start'] as num)}–${mmss(dr['end'] as num)}',
                          style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5),
                        ),
                      ),
                      SizedBox(
                        width: 56,
                        child: Text(
                          '-${(((dr['loss'] as num?) ?? 0) * 100).round()}%',
                          style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5, color: Tokens.err),
                        ),
                      ),
                      Expanded(
                        child: Text.rich(
                          TextSpan(
                            children: [
                              if (dr['preamble'] is String)
                                TextSpan(
                                  text: '${dr['preamble']}  ',
                                  style: const TextStyle(color: Tokens.run, fontWeight: FontWeight.w600),
                                ),
                              TextSpan(
                                text: (dr['text'] as String?)?.isNotEmpty == true
                                    ? dr['text'] as String
                                    : '(sem fala nesse trecho)',
                              ),
                            ],
                          ),
                          style: const TextStyle(fontSize: 13, color: Tokens.dim, height: 1.45),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ],
    );
  }
}

/// The retention curve: the share still watching over the video, the drops
/// as bands (numbered like the list), a crosshair on hover.
class RetentionChart extends StatefulWidget {
  const RetentionChart({super.key, required this.curve, this.duration, this.drops = const []});

  final List<(double, double)> curve;
  final double? duration;
  final List<(double, double)> drops;

  @override
  State<RetentionChart> createState() => _RetentionChartState();
}

class _RetentionChartState extends State<RetentionChart> {
  (double, double)? _hover;

  @override
  Widget build(BuildContext context) {
    final curve = widget.curve;
    if (curve.length < 2) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, box) {
        final painter = _ChartPainter(curve, widget.duration ?? curve.last.$1, widget.drops, _hover);
        return MouseRegion(
          onExit: (_) => setState(() => _hover = null),
          onHover: (e) => setState(() => _hover = painter.nearest(e.localPosition.dx, box.maxWidth)),
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              CustomPaint(size: Size(box.maxWidth, box.maxHeight), painter: painter),
              if (_hover case (final t, final w))
                Positioned(
                  left: math.min(box.maxWidth - 170, painter.xOf(t, box.maxWidth) + 8),
                  top: 4,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(color: Tokens.navActive, borderRadius: BorderRadius.circular(6)),
                    child: Text('${pct(w)} ainda assistindo · ${mmss(t)}', style: const TextStyle(fontSize: 12)),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter(this.curve, this.duration, this.drops, this.hover)
    : top = math.max(1.0, curve.map((p) => p.$2).reduce(math.max));

  final List<(double, double)> curve;
  final double duration;
  final List<(double, double)> drops;
  final (double, double)? hover;

  /// The first points are often above 100% (rewatches): scale to the max seen.
  final double top;

  static const _l = 38.0, _r = 8.0, _t = 10.0, _b = 22.0;

  double xOf(double t, double w) => _l + (t / duration) * (w - _l - _r);
  double yOf(double v, double h) => _t + (1 - v / top) * (h - _t - _b);

  (double, double) nearest(double dx, double w) {
    final t = ((dx - _l) / (w - _l - _r) * duration).clamp(0, duration);
    return curve.reduce((a, b) => (a.$1 - t).abs() <= (b.$1 - t).abs() ? a : b);
  }

  void _text(Canvas c, String s, Offset at, {TextAlign align = TextAlign.left, Color color = Tokens.faint}) {
    final tp = TextPainter(
      text: TextSpan(
        text: s,
        style: TextStyle(fontSize: 10, color: color, fontFamily: Tokens.mono),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    final dx = switch (align) {
      TextAlign.right => at.dx - tp.width,
      TextAlign.center => at.dx - tp.width / 2,
      _ => at.dx,
    };
    tp.paint(c, Offset(dx, at.dy - tp.height / 2));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final grid = Paint()
      ..color = Tokens.borderSoft
      ..strokeWidth = 1;
    for (final g in [0, .25, .5, .75, 1.0]) {
      if (g > top) continue;
      final y = yOf(g.toDouble(), h);
      canvas.drawLine(Offset(_l, y), Offset(w - _r, y), grid);
      _text(canvas, '${(g * 100).round()}%', Offset(_l - 6, y), align: TextAlign.right);
    }
    for (final f in [0, .25, .5, .75, 1.0]) {
      _text(canvas, mmss(f * duration), Offset(xOf(f * duration, w), h - 8), align: TextAlign.center);
    }
    final band = Paint()..color = Tokens.err.withValues(alpha: .14);
    for (final (i, (a, b)) in drops.indexed) {
      final x0 = xOf(a, w), x1 = xOf(b, w);
      canvas.drawRRect(
        RRect.fromRectAndRadius(Rect.fromLTRB(x0, _t, math.max(x0 + 2, x1), h - _b), const Radius.circular(2)),
        band,
      );
      _text(canvas, '${i + 1}', Offset((x0 + x1) / 2, _t + 8), align: TextAlign.center, color: Tokens.err);
    }
    final path = Path();
    for (final (i, (t, v)) in curve.indexed) {
      final p = Offset(xOf(t, w), yOf(v, h));
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    final area = Path.from(path)
      ..lineTo(xOf(curve.last.$1, w), yOf(0, h))
      ..lineTo(xOf(curve.first.$1, w), yOf(0, h))
      ..close();
    canvas.drawPath(area, Paint()..color = Tokens.accent.withValues(alpha: .12));
    canvas.drawPath(
      path,
      Paint()
        ..color = Tokens.accent
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    if (hover case (final t, final v)) {
      final x = xOf(t, w);
      canvas.drawLine(Offset(x, _t), Offset(x, h - _b), Paint()..color = Tokens.dim);
      canvas.drawCircle(Offset(x, yOf(v, h)), 4, Paint()..color = Tokens.accent);
    }
  }

  @override
  bool shouldRepaint(_ChartPainter old) =>
      old.curve != curve || old.hover != hover || old.drops != drops || old.duration != duration;
}

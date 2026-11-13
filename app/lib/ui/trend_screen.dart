import 'dart:async';
import 'dart:math' as math;

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import 'format.dart';
import 'result/retention_panel.dart' show pct, pp;
import 'shell.dart';
import 'theme.dart';
import 'widgets.dart';

const _metrics = [
  ('at30s', 'aos 30s'),
  ('at60s', 'aos 60s'),
  ('atHalf', 'na metade'),
  ('relativeMedian', 'vs. YouTube'),
];

TrendDelta? _metric(TrendCompare c, String m) => switch (m) {
  'at30s' => c.at30s,
  'at60s' => c.at60s,
  'atHalf' => c.atHalf,
  _ => c.relativeMedian,
};

/// relative_median is a ratio (1 = typical for that length), not a share.
String _fmt(String metric, num? v) => v == null
    ? '—'
    : metric == 'relativeMedian'
    ? '${v.toStringAsFixed(2)}×'
    : pct(v);

/// Retenção do canal (`GET /api/insights/trend`): every analyzed video in
/// publish order, whether retention is going up, and the videos planned with
/// the retention lessons against the ones planned without — the loop the
/// planner closes.
class TrendScreen extends StatefulWidget {
  const TrendScreen({super.key, required this.client, required this.onOpen});

  final AutoEditClient client;

  /// A video of the list: its Resultado.
  final ValueChanged<String> onOpen;

  @override
  State<TrendScreen> createState() => _TrendScreenState();
}

class _TrendScreenState extends State<TrendScreen> {
  Trend? _t;
  String? _error;
  String _type = 'long';

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final t = await widget.client.api.retentionTrend(type: _type);
      if (mounted) setState(() => _t = t);
    } catch (e) {
      if (mounted) setState(() => _error = 'Não deu pra ler a retenção do canal: ${errorText(e)}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = _t;
    final summary = t?.summary?[_type];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TopBar(
          title: 'Retenção do canal',
          subtitle: 'Se os vídeos estão segurando mais o público, e se as lições de retenção ajudam.',
          actions: [
            SegmentedButton<String>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: 'long', label: Text('Longos')),
                ButtonSegment(value: 'short', label: Text('Shorts')),
              ],
              selected: {_type},
              onSelectionChanged: (s) {
                setState(() {
                  _type = s.first;
                  _t = null;
                });
                unawaited(_load());
              },
            ),
            const SizedBox(width: 10),
            IconButton.outlined(tooltip: 'Recarregar', onPressed: _load, icon: const Icon(Icons.refresh, size: 18)),
          ],
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
            children: [
              if (_error != null) Notice(_error!),
              if (t == null && _error == null)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(child: CircularProgressIndicator()),
                ),
              if (t != null && t.videos.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(28),
                  child: Text(
                    'Nenhum vídeo com retenção analisada ainda. Num vídeo publicado há 24–48h, abra o Resultado '
                    'e clique em "Buscar curva" (ou rode auto-edit insights retention --all).',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Tokens.dim, height: 1.5),
                  ),
                ),
              if (t != null && t.videos.isNotEmpty) ...[
                if (summary != null) _summary(summary),
                Panel(
                  title: 'Aos 30s, vídeo a vídeo',
                  subtitle: const Text('Em ordem de publicação. Ponto cheio: planejado com as lições de retenção.'),
                  children: [SizedBox(height: 170, child: _TrendChart(t.videos))],
                ),
                Panel(
                  title: 'Vídeos analisados',
                  children: [
                    for (final v in t.videos.reversed)
                      Material(
                        color: Colors.transparent,
                        child: InkWell(
                          borderRadius: BorderRadius.circular(8),
                          onTap: v.id == null ? null : () => widget.onOpen(v.id!),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 6),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        v.title ?? v.id ?? '',
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5),
                                      ),
                                      Text(
                                        [
                                          when(v.publishedAt).split(' ').first,
                                          if (v.duration != null) duration(v.duration),
                                          if ((v.drops ?? 0) > 0) '${v.drops} queda(s)',
                                        ].where((x) => x.isNotEmpty).join(' · '),
                                        style: const TextStyle(
                                          fontFamily: Tokens.mono,
                                          fontSize: 11.5,
                                          color: Tokens.faint,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                if ((v.lessons ?? 0) > 0) ...[
                                  Tooltip(
                                    message: 'Planejado com ${v.lessons} lição(ões) de retenção',
                                    child: Badge2('${v.lessons} lições', color: Tokens.info),
                                  ),
                                  const SizedBox(width: 12),
                                ],
                                for (final (m, label, value) in [
                                  ('at30s', '30s', v.at30s),
                                  ('at60s', '60s', v.at60s),
                                  ('atHalf', 'metade', v.atHalf),
                                  ('relativeMedian', 'vs. YT', v.relativeMedian),
                                ])
                                  SizedBox(
                                    width: 74,
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.end,
                                      children: [
                                        Text(
                                          _fmt(m, value),
                                          style: const TextStyle(fontFamily: Tokens.mono, fontSize: 13),
                                        ),
                                        Text(label, style: const TextStyle(fontSize: 11, color: Tokens.faint)),
                                      ],
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _summary(TrendSummary s) {
    Widget compare(String title, String sub, TrendCompare c) => Container(
      width: 400,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Tokens.panel2,
        border: Border.all(color: Tokens.borderSoft),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          Padding(
            padding: const EdgeInsets.only(top: 2, bottom: 10),
            child: Text(sub, style: const TextStyle(fontSize: 12.5, color: Tokens.dim)),
          ),
          for (final (m, label) in _metrics)
            if (_metric(c, m) case final TrendDelta d)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    SizedBox(
                      width: 90,
                      child: Text(label, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
                    ),
                    Text(
                      '${_fmt(m, d.before)} → ${_fmt(m, d.after)}',
                      style: const TextStyle(fontFamily: Tokens.mono, fontSize: 13),
                    ),
                    const SizedBox(width: 10),
                    if (d.delta != null)
                      Text(
                        m == 'relativeMedian'
                            ? '${d.delta! >= 0 ? '+' : ''}${d.delta!.toStringAsFixed(2)}'
                            : pp(d.delta),
                        style: TextStyle(
                          fontFamily: Tokens.mono,
                          fontSize: 12.5,
                          color: d.delta! >= 0 ? Tokens.ok : Tokens.err,
                        ),
                      ),
                  ],
                ),
              ),
        ],
      ),
    );
    final ovn = s.olderVsNewer, wvw = s.withVsWithoutLessons;
    return Panel(
      title: '${s.count} vídeo${s.count == 1 ? '' : 's'} analisado${s.count == 1 ? '' : 's'}',
      subtitle: Text(
        ovn == null && wvw == null
            ? 'Com mais vídeos analisados aparece se a retenção está subindo.'
            : 'Média de cada grupo; verde é melhora.',
      ),
      children: [
        Wrap(
          spacing: 14,
          runSpacing: 14,
          children: [
            if (ovn != null) compare('Mais antigos → mais novos', '${ovn.older} antigos, ${ovn.newer} novos', ovn),
            if (wvw != null) compare('Sem → com as lições de retenção', '${wvw.without} sem, ${wvw.with_} com', wvw),
          ],
        ),
      ],
    );
  }
}

class _TrendChart extends StatelessWidget {
  const _TrendChart(this.videos);
  final List<TrendVideosItem> videos;

  @override
  Widget build(BuildContext context) {
    final pts = [
      for (final v in videos)
        if (v.at30s != null) (v.at30s!, (v.lessons ?? 0) > 0),
    ];
    if (pts.isEmpty) {
      return const Center(
        child: Text('Nenhum vídeo com o número dos 30s.', style: TextStyle(color: Tokens.dim)),
      );
    }
    return CustomPaint(painter: _LinePainter(pts), size: Size.infinite);
  }
}

class _LinePainter extends CustomPainter {
  _LinePainter(this.pts);
  final List<(double, bool)> pts;

  @override
  void paint(Canvas canvas, Size size) {
    const l = 38.0, r = 12.0, t = 10.0, b = 10.0;
    final top = math.max(1.0, pts.map((p) => p.$1).reduce(math.max));
    double x(int i) => pts.length == 1 ? (size.width + l - r) / 2 : l + i / (pts.length - 1) * (size.width - l - r);
    double y(double v) => t + (1 - v / top) * (size.height - t - b);
    final grid = Paint()..color = Tokens.borderSoft;
    for (final g in [0.0, .25, .5, .75, 1.0]) {
      canvas.drawLine(Offset(l, y(g)), Offset(size.width - r, y(g)), grid);
      final tp = TextPainter(
        text: TextSpan(
          text: '${(g * 100).round()}%',
          style: const TextStyle(fontSize: 10, color: Tokens.faint, fontFamily: Tokens.mono),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(l - 6 - tp.width, y(g) - tp.height / 2));
    }
    final path = Path();
    for (final (i, (v, _)) in pts.indexed) {
      i == 0 ? path.moveTo(x(i), y(v)) : path.lineTo(x(i), y(v));
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = Tokens.accent
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    for (final (i, (v, lessons)) in pts.indexed) {
      canvas.drawCircle(Offset(x(i), y(v)), 4.5, Paint()..color = lessons ? Tokens.info : Tokens.bg);
      canvas.drawCircle(
        Offset(x(i), y(v)),
        4.5,
        Paint()
          ..color = lessons ? Tokens.info : Tokens.accent
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }
  }

  @override
  bool shouldRepaint(_LinePainter old) => old.pts != pts;
}

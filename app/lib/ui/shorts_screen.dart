import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import 'pipeline/cuts_screen.dart' show timecode;
import 'player.dart';
import 'shell.dart';
import 'theme.dart';
import 'widgets.dart';

/// Shorts (desktop/ui/js/shorts.js): stretches of a finished long that become
/// shorts. The clipper proposes, you watch each one in the player, tick and
/// cut; each ticked one becomes a `<name>_shortN` workspace that runs the
/// short pipeline in a queue. `auto-edit shorts <video> [--pick]` with a screen.
class ShortsScreen extends StatefulWidget {
  const ShortsScreen({
    super.key,
    required this.client,
    required this.id,
    required this.onBack,
    required this.onCut,
    required this.onOpen,
  });

  final AutoEditClient client;
  final String id;
  final VoidCallback onBack;

  /// After "Cortar": Edições, where the shorts show up queued.
  final VoidCallback onCut;

  /// A short already cut from a candidate: its pipeline.
  final ValueChanged<String> onOpen;

  @override
  State<ShortsScreen> createState() => _ShortsScreenState();
}

class _ShortsScreenState extends State<ShortsScreen> {
  ShortsState? _d;
  String? _error;
  final Set<int> _picked = {};
  final List<String> _lines = [];
  StreamSubscription<JobEvent>? _stream;
  bool _busy = false;
  bool _running = false;
  int? _playing;
  final _maxDur = TextEditingController(text: '90');

  AutoEditApi get _api => widget.client.api;

  double get _max {
    final v = double.tryParse(_maxDur.text.replaceAll(',', '.'));
    return v != null && v > 0 ? v : 90;
  }

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    unawaited(_stream?.cancel());
    _maxDur.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await _api.getShorts(widget.id, maxDur: _max);
      if (!mounted) return;
      setState(() {
        _d = d;
        // the selection survives a reload, with numbers that still exist
        final valid = {for (final c in d.clips) c.number};
        _picked.retainAll(valid);
        if (!valid.contains(_playing)) _playing = null;
      });
      if (d.job?.status == 'running') _openStream();
    } catch (e) {
      if (mounted) setState(() => _error = 'Não deu pra ler os shorts: ${errorText(e)}');
    }
  }

  void _openStream() {
    if (_stream != null) return;
    setState(() => _running = true);
    _stream = _api
        .videoEvents(widget.id)
        .listen(
          (ev) {
            switch (ev.type) {
              case 'log':
                setState(() {
                  _lines.add(ev.line ?? '');
                  if (_lines.length > 300) _lines.removeRange(0, _lines.length - 300);
                });
              case 'done':
                _close();
                unawaited(_load());
              case 'error':
                _close();
                setState(() => _error = ev.message ?? 'O clipper falhou — veja o log.');
                unawaited(_load());
            }
          },
          onError: (Object _) {
            _close();
            unawaited(_load());
          },
          cancelOnError: true,
        );
  }

  void _close() {
    unawaited(_stream?.cancel());
    _stream = null;
    if (mounted) setState(() => _running = false);
  }

  Future<void> _find() async {
    setState(() {
      _error = null;
      _lines.clear();
    });
    try {
      await _api.findShorts(widget.id, body: FindShortsRequest(maxDur: _max));
      _openStream();
    } catch (e) {
      setState(() => _error = errorText(e));
    }
  }

  Future<void> _cut() async {
    final pick = _picked.toList()..sort();
    if (pick.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _api.cutShorts(widget.id, CutShortsRequest(pick: pick, maxDur: _max));
      widget.onCut();
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    final body = d != null && d.eligible && d.hasPlan && !_running;
    final n = _picked.length;
    final cutDone = d?.clips.where((c) => c.short != null).length ?? 0;
    const dim = TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.dim);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TopBar(
          title: 'Shorts — ${d?.name ?? widget.id}',
          onBack: widget.onBack,
          subtitleWidget: d == null
              ? null
              : Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text(
                    !d.hasPlan
                        ? 'Ainda sem candidatos'
                        : '${d.clips.length} candidato${d.clips.length == 1 ? '' : 's'}'
                              '${cutDone > 0 ? ' · $cutDone já cortado(s)' : ''}',
                    style: dim,
                  ),
                ),
          actions: [
            if (body) ...[
              OutlinedButton(onPressed: _find, child: const Text('Propor de novo')),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: _busy || n == 0 ? null : _cut,
                child: Text(n == 0 ? 'Cortar selecionados' : 'Cortar $n selecionado${n == 1 ? '' : 's'}'),
              ),
            ],
          ],
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
            children: [
              if (_error != null) Notice(_error!),
              if (d == null && _error == null)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (d == null)
                const SizedBox.shrink()
              else if (_running)
                _runningPanel()
              else if (!d.eligible)
                Padding(
                  padding: const EdgeInsets.all(28),
                  child: Text(
                    d.reason ?? 'Este vídeo não pode gerar shorts.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Tokens.dim),
                  ),
                )
              else if (!d.hasPlan)
                _startPanel()
              else
                ..._bodyChildren(d),
            ],
          ),
        ),
      ],
    );
  }

  Widget _maxField() => SizedBox(
    width: 140,
    child: TextField(
      controller: _maxDur,
      keyboardType: TextInputType.number,
      decoration: fieldDecoration().copyWith(labelText: 'Duração máx. (s)'),
      onSubmitted: (_) => _load(),
    ),
  );

  Widget _startPanel() => Panel(
    title: 'Propor shorts',
    subtitle: const Text(
      'O agente lê a transcrição do vídeo pronto e propõe trechos que se sustentam sozinhos. '
      'Você assiste, escolhe e corta.',
    ),
    children: [
      Row(
        children: [
          _maxField(),
          const SizedBox(width: 12),
          FilledButton(onPressed: _find, child: const Text('Propor shorts')),
        ],
      ),
    ],
  );

  Widget _runningPanel() => Panel(
    title: 'O clipper está lendo o vídeo…',
    subtitle: const Text('Leva um ou dois minutos. Os candidatos aparecem aqui quando ele terminar.'),
    leading: const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
    children: [
      Container(
        height: 220,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Tokens.bg,
          border: Border.all(color: Tokens.borderSoft),
          borderRadius: BorderRadius.circular(10),
        ),
        child: ListView(
          reverse: true,
          children: [
            for (final l in _lines.reversed)
              Text(
                l,
                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.dim),
              ),
          ],
        ),
      ),
    ],
  );

  List<Widget> _bodyChildren(ShortsState d) {
    final playing = d.clips.where((c) => c.number == _playing).firstOrNull;
    return [
      Panel(
        title: 'Assistir',
        subtitle: Text(
          playing == null
              ? 'Clique em Assistir num candidato pra ver só aquele trecho.'
              : '#${playing.number} · ${timecode(playing.start)} → ${timecode(playing.end)}',
        ),
        trailing: _maxField(),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 760),
              child: AspectRatio(
                aspectRatio: 16 / 9,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: VideoPlayer(
                    PlayerSource(
                      _api.getFileUri(widget.id, ArtifactKind.video),
                      headers: widget.client.transport.headers,
                      start: playing == null ? null : Duration(milliseconds: (playing.start * 1000).round()),
                      end: playing == null ? null : Duration(milliseconds: (playing.end * 1000).round()),
                      autoplay: playing != null,
                    ),
                    key: ValueKey(_playing),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      if (d.clips.isEmpty)
        Padding(
          padding: const EdgeInsets.all(28),
          child: Text(
            'Nenhum candidato passou na validação.${d.notes.isNotEmpty ? '\n\nO clipper explicou: ${d.notes}' : ''}',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Tokens.dim),
          ),
        ),
      for (final c in d.clips)
        _Clip(
          c: c,
          on: _picked.contains(c.number),
          playing: c.number == _playing,
          onChanged: _busy ? null : (on) => setState(() => on ? _picked.add(c.number) : _picked.remove(c.number)),
          onPlay: () => setState(() => _playing = c.number),
          onOpen: widget.onOpen,
        ),
      if (d.rejected.isNotEmpty)
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
                'Descartados (${d.rejected.length})',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
              ),
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final r in d.rejected)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text('•  $r', style: const TextStyle(fontSize: 13, color: Tokens.dim)),
                  ),
              ],
            ),
          ),
        ),
    ];
  }
}

class _Clip extends StatelessWidget {
  const _Clip({
    required this.c,
    required this.on,
    required this.playing,
    required this.onChanged,
    required this.onPlay,
    required this.onOpen,
  });

  final ShortsStateClipsItem c;
  final bool on;
  final bool playing;
  final ValueChanged<bool>? onChanged;
  final VoidCallback onPlay;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    final score = c.score;
    final short = c.short;
    const mono = TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.faint);
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: on ? Tokens.navActive : Tokens.panel,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: playing ? Tokens.accent : Tokens.borderSoft),
          borderRadius: BorderRadius.circular(12),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onChanged == null ? null : () => onChanged!(!on),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(6, 8, 14, 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Checkbox(value: on, onChanged: onChanged == null ? null : (x) => onChanged!(x ?? false)),
                const SizedBox(width: 4),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Wrap(
                          spacing: 12,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              '#${c.number}',
                              style: const TextStyle(fontFamily: Tokens.mono, fontWeight: FontWeight.w700),
                            ),
                            Text(
                              '${timecode(c.start)} → ${timecode(c.end)}',
                              style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.accent),
                            ),
                            Text('${c.duration.round()}s', style: mono),
                            Tooltip(
                              message: 'nota do clipper',
                              child: Text(
                                score == null ? '–' : (score == score.roundToDouble() ? '${score.round()}' : '$score'),
                                style: TextStyle(
                                  fontFamily: Tokens.mono,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: (score ?? 0) >= 8 ? Tokens.ok : Tokens.dim,
                                ),
                              ),
                            ),
                            SmallButton(playing ? 'Tocando' : 'Assistir', onPressed: onPlay),
                          ],
                        ),
                        if (c.hook.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(c.hook, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                          ),
                        if (c.text.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(c.text, style: const TextStyle(fontSize: 13.5, height: 1.5, color: Tokens.dim)),
                          ),
                        if (c.overlaps || short != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Wrap(
                              spacing: 6,
                              runSpacing: 6,
                              children: [
                                if (c.overlaps) const Chip2('sobrepõe outro candidato', color: Tokens.run),
                                if (short?.id != null)
                                  Chip2(
                                    'já cortado · ${short!.id}',
                                    color: Tokens.info,
                                    onTap: () => onOpen(short.id!),
                                  ),
                              ],
                            ),
                          ),
                        if (short?.overwriteWarning != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(
                              'Cortar de novo sobrescreve: ${short!.overwriteWarning}',
                              style: const TextStyle(fontSize: 12.5, color: Tokens.run),
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
    );
  }
}

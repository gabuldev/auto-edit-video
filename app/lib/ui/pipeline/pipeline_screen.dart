import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../edits/edits_controller.dart' show editNameOf;
import '../edits/edits_screen.dart' show StatusChip, statusColor;
import '../shell.dart';
import '../theme.dart';
import '../widgets.dart';
import 'pipeline_controller.dart';

/// Pipeline ao vivo: where one edit is, what it is printing, and the one
/// action that unblocks it (retomar a partir de um stage).
class PipelineScreen extends StatefulWidget {
  const PipelineScreen({
    super.key,
    required this.client,
    required this.id,
    required this.onBack,
    required this.onCuts,
    required this.onResult,
    this.every,
  });

  final AutoEditClient client;
  final String id;
  final VoidCallback onBack;
  final VoidCallback onCuts;
  final VoidCallback onResult;
  final Duration? every;

  @override
  State<PipelineScreen> createState() => _PipelineScreenState();
}

class _PipelineScreenState extends State<PipelineScreen> {
  late final PipelineController c = PipelineController(
    widget.client,
    widget.id,
    every: widget.every ?? const Duration(seconds: 5),
  )..start();

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        final d = c.detail;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TopBar(
              title: d == null ? widget.id : editNameOf(d.name, d.title, d.context, d.videoName),
              onBack: widget.onBack,
              subtitleWidget: d == null ? null : _Sub(d),
              actions: [
                if (c.stoppable) ...[
                  DangerButton(
                    c.stopArmed ? 'Confirmar: parar edição' : 'Parar',
                    confirm: c.stopArmed,
                    onPressed: c.stopping ? null : c.stop,
                  ),
                  const SizedBox(width: 8),
                ],
                OutlinedButton(onPressed: widget.onCuts, child: const Text('Revisar cortes')),
                if (d != null && (d.status == VideoStatus.done || d.output != null)) ...[
                  const SizedBox(width: 8),
                  FilledButton(onPressed: widget.onResult, child: const Text('Resultado')),
                ],
              ],
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, box) {
                  final top = [if (c.error != null) Notice(c.error!)];
                  final left = [
                    if (d != null) ...[_Stages(c: c, d: d), _Facts(c: c, d: d)],
                  ];
                  if (box.maxWidth < 980) {
                    return ListView(
                      padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
                      children: [
                        ...top,
                        ...left,
                        SizedBox(height: 460, child: _Log(c: c)),
                      ],
                    );
                  }
                  return Padding(
                    padding: const EdgeInsets.fromLTRB(28, 20, 28, 22),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        ...top,
                        Expanded(
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              SizedBox(width: 440, child: ListView(children: left)),
                              const SizedBox(width: 18),
                              Expanded(child: _Log(c: c)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        );
      },
    );
  }
}

class _Sub extends StatelessWidget {
  const _Sub(this.d);
  final VideoDetail d;

  @override
  Widget build(BuildContext context) {
    const mono = TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.dim);
    final tokens = d.estimatedTokens;
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Row(
        children: [
          TypeBadge(d.type),
          const SizedBox(width: 8),
          Chip2(
            d.status == VideoStatus.interrupted ? 'Interrompido' : StatusChip.labels[d.status.value] ?? d.status.value,
            color: statusColor(d.status),
          ),
          const SizedBox(width: 10),
          Text('iteração ${d.iteration ?? 1}/${d.maxIterations ?? 3}', style: mono),
          if (tokens != null) ...[const SizedBox(width: 10), Text('~${thousands(tokens)} tokens', style: mono)],
        ],
      ),
    );
  }
}

/// 12345 → "12.345", like `toLocaleString("pt-BR")`.
String thousands(int n) => n.toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '.');

class _Stages extends StatelessWidget {
  const _Stages({required this.c, required this.d});
  final PipelineController c;
  final VideoDetail d;

  @override
  Widget build(BuildContext context) {
    final runs = stagesOf(d);
    final note = c.live
        ? 'rodando — pare ou espere terminar pra retomar'
        : d.status == VideoStatus.interrupted
        ? 'foi interrompido (o processo morreu) — retome daqui'
        : 'refaz esse stage e todos os seguintes';
    return Panel(
      title: 'Stages',
      subtitle: const Text.rich(
        TextSpan(
          children: [
            TextSpan(text: 'A fonte da verdade é o '),
            TextSpan(
              text: 'pipeline.json',
              style: TextStyle(fontFamily: Tokens.mono, fontSize: 12),
            ),
            TextSpan(text: ' do workspace.'),
          ],
        ),
      ),
      children: [
        for (final s in runs) _StageRow(name: s, state: stageState(d, s), d: d),
        const Divider(height: 28),
        Wrap(
          spacing: 10,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            const Text('Retomar a partir de', style: TextStyle(fontSize: 13, color: Tokens.dim)),
            DropdownButton<String>(
              value: c.resumeStage,
              isDense: true,
              style: const TextStyle(fontFamily: Tokens.mono, fontSize: 13, color: Tokens.text),
              items: [for (final s in runs) DropdownMenuItem(value: s, child: Text(s))],
              onChanged: c.live ? null : c.pickResume,
            ),
            OutlinedButton(
              onPressed: c.live || c.resuming ? null : c.resume,
              child: Text(c.resuming ? 'Retomando…' : 'Retomar'),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(note, style: const TextStyle(fontSize: 12, color: Tokens.faint)),
        ),
      ],
    );
  }
}

class _StageRow extends StatelessWidget {
  const _StageRow({required this.name, required this.state, required this.d});
  final String name;
  final String state;
  final VideoDetail d;

  static const _read = {'complete': 'concluído', 'running': 'rodando', 'failed': 'falhou', 'pending': 'aguardando'};

  @override
  Widget build(BuildContext context) {
    final active = name == d.currentStage && state != 'complete';
    final at = d.stageDetail[name]?['completed_at'] as String?;
    final time = at == null ? null : DateTime.tryParse(at)?.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    final right = state == 'complete' && time != null
        ? '${two(time.hour)}:${two(time.minute)}:${two(time.second)}'
        : state == 'failed'
        ? 'falhou'
        : '';
    final color = switch (state) {
      'complete' => Tokens.accent,
      'running' => Tokens.run,
      'failed' => Tokens.err,
      _ => Tokens.border,
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 4),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(color: active ? Tokens.navActive : null, borderRadius: BorderRadius.circular(8)),
      child: Row(
        children: [
          Semantics(
            label: _read[state] ?? state,
            child: SizedBox(
              width: 14,
              height: 14,
              child: state == 'running'
                  ? const CircularProgressIndicator(strokeWidth: 2, color: Tokens.run)
                  : Center(
                      child: Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3)),
                      ),
                    ),
            ),
          ),
          const SizedBox(width: 12),
          SizedBox(
            width: 84,
            child: Text(
              name,
              style: TextStyle(
                fontFamily: Tokens.mono,
                fontSize: 13,
                color: state == 'pending' ? Tokens.dim : Tokens.text,
                fontWeight: active ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
          Expanded(
            child: Text(
              stageHint[name] ?? '',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12.5, color: Tokens.faint),
            ),
          ),
          Text(
            right,
            style: TextStyle(
              fontFamily: Tokens.mono,
              fontSize: 11.5,
              color: state == 'failed' ? Tokens.err : Tokens.faint,
            ),
          ),
        ],
      ),
    );
  }
}

class _Facts extends StatelessWidget {
  const _Facts({required this.c, required this.d});
  final PipelineController c;
  final VideoDetail d;

  @override
  Widget build(BuildContext context) {
    // (label, value, the kind to show in its folder)
    final facts = <(String, String?, String?)>[
      ('vídeo original', d.videoPath, 'source'),
      ('output', d.output, 'video'),
      ('contexto', d.context, null),
      ('idioma', d.language, null),
      ('cortes mantidos', d.plan?.keptSegments?.toString(), null),
    ].where((f) => f.$2 != null && f.$2!.isNotEmpty);
    const value = TextStyle(fontFamily: Tokens.mono, fontSize: 12.5);
    return Panel(
      title: 'Vídeo',
      subtitle: const Text('O arquivo, o pedido e onde fica o resultado.'),
      children: [
        for (final (label, v, kind) in facts)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: const TextStyle(fontSize: 11.5, color: Tokens.faint, letterSpacing: .4)),
                const SizedBox(height: 2),
                if (kind == null)
                  SelectableText(v!, style: value)
                else
                  Tooltip(
                    message: 'Mostrar na pasta',
                    child: InkWell(
                      onTap: () => c.reveal(kind),
                      child: Text(v!, style: value.copyWith(color: Tokens.accent)),
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _Log extends StatefulWidget {
  const _Log({required this.c});
  final PipelineController c;

  @override
  State<_Log> createState() => _LogState();
}

class _LogState extends State<_Log> {
  final _scroll = ScrollController();

  /// Follows the bottom until the person scrolls up to read.
  bool _pinned = true;
  int _seen = -1;

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    if (c.logVersion != _seen) {
      _seen = c.logVersion;
      if (_pinned) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
        });
      }
    }
    return Panel(
      title: 'Log ao vivo',
      subtitle: const Text.rich(
        TextSpan(
          children: [
            TextSpan(text: 'Saída do '),
            TextSpan(
              text: 'ralph.sh',
              style: TextStyle(fontFamily: Tokens.mono, fontSize: 12),
            ),
            TextSpan(text: ' em tempo real.'),
          ],
        ),
      ),
      trailing: c.streaming
          ? const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(width: 10, height: 10, child: CircularProgressIndicator(strokeWidth: 1.5, color: Tokens.run)),
                SizedBox(width: 8),
                Text('ao vivo', style: TextStyle(fontSize: 12, color: Tokens.run)),
              ],
            )
          : null,
      children: [
        Expanded(
          child: Container(
            decoration: BoxDecoration(
              color: Tokens.bg,
              border: Border.all(color: Tokens.borderSoft),
              borderRadius: BorderRadius.circular(10),
            ),
            child: c.lines.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(20),
                      child: Text(
                        'Sem job ao vivo — o log aparece quando um run está em andamento.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Tokens.faint, fontSize: 13),
                      ),
                    ),
                  )
                : NotificationListener<ScrollNotification>(
                    onNotification: (n) {
                      if (n is ScrollUpdateNotification || n is ScrollEndNotification) {
                        _pinned = n.metrics.maxScrollExtent - n.metrics.pixels < 24;
                      }
                      return false;
                    },
                    child: SelectionArea(
                      child: ListView.builder(
                        controller: _scroll,
                        padding: const EdgeInsets.all(12),
                        itemCount: c.lines.length,
                        itemBuilder: (context, i) {
                          final line = c.lines[i];
                          final mark = line.startsWith('──');
                          return Text(
                            line,
                            style: TextStyle(
                              fontFamily: Tokens.mono,
                              fontSize: 12,
                              height: 1.5,
                              color: mark ? Tokens.accent : Tokens.dim,
                            ),
                          );
                        },
                      ),
                    ),
                  ),
          ),
        ),
      ],
    );
  }
}

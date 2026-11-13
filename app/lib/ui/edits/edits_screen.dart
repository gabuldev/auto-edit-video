import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../platform.dart';
import '../format.dart';
import '../shell.dart';
import '../theme.dart';
import '../video_pick.dart';
import '../widgets.dart';
import 'edits_controller.dart';

const _privacy = {'private': 'privado', 'unlisted': 'não listado', 'public': 'público'};

/// Edições — the edits, with live progress for the running ones. Empty, it is
/// a drop zone: a video picked or dropped goes to Novo edit.
class EditsScreen extends StatefulWidget {
  const EditsScreen({
    super.key,
    required this.client,
    required this.pickers,
    required this.onNewEdit,
    required this.onOpen,
    this.every,
  });

  final AutoEditClient client;
  final Pickers pickers;

  /// Novo edit, with this video already chosen (or none).
  final void Function({String? path}) onNewEdit;

  /// A row clicked: its pipeline; "Ver resultado": the result ([result] true).
  final void Function(String id, {bool result}) onOpen;
  final Duration? every;

  @override
  State<EditsScreen> createState() => _EditsScreenState();
}

class _EditsScreenState extends State<EditsScreen> {
  late final EditsController c = EditsController(widget.client, every: widget.every ?? const Duration(seconds: 5))
    ..start();
  final _search = TextEditingController();
  bool _over = false;
  String? _dropError;

  @override
  void dispose() {
    c.dispose();
    _search.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    setState(() => _dropError = null);
    String? inbox;
    try {
      inbox = (await widget.client.api.getFolders()).inbox.path;
    } catch (_) {
      // engine offline: the OS decides where the dialog opens
    }
    final path = await widget.pickers.video(initial: inbox);
    if (path != null) widget.onNewEdit(path: path);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        final videos = c.videos;
        final shown = c.shown;
        final empty = videos != null && videos.isEmpty;
        final count = videos == null
            ? 'Carregando…'
            : '${c.query.trim().isNotEmpty ? '${shown.length} de ${videos.length} edições' : '${videos.length} ${videos.length == 1 ? 'edição' : 'edições'}'}'
                  ' · ${c.running} em andamento';
        return VideoDrop(
          enabled: empty,
          onOver: (on) => setState(() => _over = on),
          onVideo: (p) => widget.onNewEdit(path: p),
          onFail: (e) => setState(() => _dropError = e),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TopBar(
                title: 'Edições',
                subtitle: count,
                actions: [
                  if (videos != null && videos.isNotEmpty) ...[
                    SizedBox(
                      width: 260,
                      child: _SearchBox(controller: _search, onChanged: c.setQuery),
                    ),
                    const SizedBox(width: 12),
                  ],
                  FilledButton.icon(
                    onPressed: () => widget.onNewEdit(),
                    icon: const Icon(Icons.add, size: 18),
                    label: const Text('Novo edit'),
                  ),
                ],
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
                  children: [
                    if (c.error != null) Notice(c.error!),
                    if (_dropError != null) Notice(_dropError!),
                    if (empty)
                      _EmptyDrop(over: _over, onPick: _pick)
                    else if (videos != null && shown.isEmpty)
                      Padding(
                        padding: const EdgeInsets.all(32),
                        child: Center(
                          child: Text(
                            'Nada encontrado pra “${c.query.trim()}”.',
                            style: const TextStyle(color: Tokens.dim),
                          ),
                        ),
                      )
                    else if (videos != null) ...[
                      _Head(c: c),
                      for (final v in shown) _Row(c: c, v: v, client: widget.client, onOpen: widget.onOpen),
                    ],
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _SearchBox extends StatelessWidget {
  const _SearchBox({required this.controller, required this.onChanged});
  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => CallbackShortcuts(
    bindings: {
      const SingleActivator(LogicalKeyboardKey.escape): () {
        controller.clear();
        onChanged('');
      },
    },
    child: TextField(
      controller: controller,
      onChanged: onChanged,
      style: const TextStyle(fontSize: 13.5),
      decoration: fieldDecoration(hint: 'Buscar').copyWith(
        prefixIcon: const Icon(Icons.search, size: 18, color: Tokens.faint),
        prefixIconConstraints: const BoxConstraints(minWidth: 36),
      ),
    ),
  );
}

class _EmptyDrop extends StatelessWidget {
  const _EmptyDrop({required this.over, required this.onPick});
  final bool over;
  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) => Material(
    color: over ? Tokens.accent.withValues(alpha: .06) : Tokens.panel,
    shape: RoundedRectangleBorder(
      side: BorderSide(color: over ? Tokens.accent : Tokens.border),
      borderRadius: BorderRadius.circular(14),
    ),
    child: InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onPick,
      child: const Padding(
        padding: EdgeInsets.symmetric(vertical: 56, horizontal: 24),
        child: Column(
          children: [
            Icon(Icons.upload_outlined, size: 34, color: Tokens.accent),
            SizedBox(height: 12),
            Text('Nenhuma edição ainda', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            SizedBox(height: 6),
            Text.rich(
              TextSpan(
                style: TextStyle(fontSize: 13.5, color: Tokens.dim),
                children: [
                  TextSpan(text: 'Arraste um vídeo pra cá ou '),
                  TextSpan(
                    text: 'escolha no computador',
                    style: TextStyle(color: Tokens.accent, decoration: TextDecoration.underline),
                  ),
                ],
              ),
            ),
            SizedBox(height: 8),
            Text(
              'mp4 · mov · mkv · webm · avi · m4v · mts',
              style: TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: Tokens.faint),
            ),
          ],
        ),
      ),
    ),
  );
}

const _cols = [52.0, null, 70.0, 230.0, 120.0, 250.0]; // select, video, type, progress, status, actions

class _Head extends StatelessWidget {
  const _Head({required this.c});
  final EditsController c;

  @override
  Widget build(BuildContext context) {
    final shown = c.shown;
    final picked = shown.where((v) => c.selected.contains(v.id)).length;
    final all = shown.isNotEmpty && picked == shown.length;
    final box = Checkbox(
      tristate: true,
      value: all ? true : (picked > 0 ? null : false),
      onChanged: c.bulkBusy != null ? null : (_) => c.selectAll(!all),
    );
    if (c.selected.isEmpty) {
      const style = TextStyle(fontSize: 11.5, color: Tokens.faint, letterSpacing: .6);
      return Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          children: [
            SizedBox(width: _cols[0], child: box),
            const Expanded(child: Text('VÍDEO', style: style)),
            SizedBox(
              width: _cols[2],
              child: const Text('TIPO', style: style),
            ),
            SizedBox(
              width: _cols[3],
              child: const Text('PROGRESSO', style: style),
            ),
            SizedBox(
              width: _cols[4],
              child: const Text('STATUS', style: style),
            ),
            SizedBox(width: _cols[5]),
          ],
        ),
      );
    }
    final n = c.selected.length;
    final running = c.selectedRunning;
    final busy = c.bulkBusy;
    final List<Widget> acts;
    String note = '';
    if (busy != null) {
      acts = [
        const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
        const SizedBox(width: 8),
        Text('Excluindo ${(busy.$1 + 1).clamp(1, busy.$2)} de ${busy.$2}…', style: const TextStyle(fontSize: 13)),
      ];
    } else if (c.bulkArmed) {
      note =
          'Apaga também os arquivos da pasta de saída; os vídeos originais ficam.'
          '${running == 0
              ? ''
              : running == 1
              ? ' Uma está rodando e vai ser cancelada.'
              : ' $running estão rodando e vão ser canceladas.'}';
      acts = [
        SmallButton('Cancelar', onPressed: () => c.armBulk(false)),
        const SizedBox(width: 6),
        DangerButton(n == 1 ? 'Excluir 1 edição' : 'Excluir $n edições', confirm: true, onPressed: c.deleteSelected),
      ];
    } else {
      acts = [
        SmallButton('Limpar seleção', onPressed: c.clearSelection),
        const SizedBox(width: 6),
        DangerButton('Excluir', icon: Icons.delete_outline, onPressed: () => c.armBulk(true)),
      ];
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(color: Tokens.navActive, borderRadius: BorderRadius.circular(10)),
      child: Row(
        children: [
          SizedBox(width: _cols[0], child: box),
          Text(
            '$n ${n == 1 ? 'selecionada' : 'selecionadas'}',
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(note, style: const TextStyle(fontSize: 12.5, color: Tokens.dim)),
          ),
          ...acts,
          const SizedBox(width: 12),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.c, required this.v, required this.client, required this.onOpen});
  final EditsController c;
  final VideoSummary v;
  final AutoEditClient client;
  final void Function(String id, {bool result}) onOpen;

  @override
  Widget build(BuildContext context) {
    final on = c.selected.contains(v.id);
    final stage = c.stageOf(v);
    final liveLine = c.live[v.id]?.line;
    final stageColor = v.status == VideoStatus.failed
        ? Tokens.err
        : v.status == VideoStatus.running
        ? Tokens.run
        : Tokens.faint;
    final meta = [
      v.videoName,
      if (v.language != null) v.language!,
      if (v.derivedFrom != null) 'short de ${v.derivedFrom}',
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: on ? Tokens.navActive : Tokens.panel,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: on ? Tokens.accent.withValues(alpha: .35) : Tokens.borderSoft),
          borderRadius: BorderRadius.circular(12),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => onOpen(v.id),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: Row(
              children: [
                SizedBox(
                  width: _cols[0],
                  child: Checkbox(value: on, onChanged: (x) => c.select(v.id, x ?? false)),
                ),
                Expanded(
                  child: Row(
                    children: [
                      VideoThumb(
                        url: v.hasThumbnail ? client.api.getFileUri(v.id, ArtifactKind.thumbnail) : null,
                        headers: client.transport.headers,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Tooltip(
                              message: editName(v),
                              child: Text(
                                editName(v),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                              ),
                            ),
                            Text(
                              meta,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: Tokens.faint),
                            ),
                            if (liveLine != null && liveLine.isNotEmpty)
                              Text(
                                liveLine,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 11, color: Tokens.dim),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  width: _cols[2],
                  child: Align(alignment: Alignment.centerLeft, child: TypeBadge(v.type)),
                ),
                SizedBox(
                  width: _cols[3],
                  child: Row(
                    children: [
                      for (final (_, state) in c.dots(v)) _Dot(state),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          stage == 'done' ? '' : stage ?? '—',
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: stageColor),
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  width: _cols[4],
                  child: Align(alignment: Alignment.centerLeft, child: StatusChip(v)),
                ),
                SizedBox(
                  width: _cols[5],
                  // never wider than its column (a long confirm in a narrow window)
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerRight,
                    child: Row(mainAxisSize: MainAxisSize.min, children: [..._acts(), const SizedBox(width: 12)]),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _acts() {
    final armed = c.armed;
    if (armed != null && armed.$1 == v.id) {
      final stop = armed.$2 == 'stop';
      return [
        SmallButton(stop ? 'Voltar' : 'Cancelar', onPressed: c.disarm),
        const SizedBox(width: 6),
        DangerButton(stop ? 'Cancelar edição' : 'Excluir', confirm: true, onPressed: () => c.act(v.id, armed.$2)),
      ];
    }
    return [
      if (v.status == VideoStatus.done) ...[
        SmallButton('Ver resultado', onPressed: () => onOpen(v.id, result: true)),
        const SizedBox(width: 6),
      ],
      if (isStoppable(v)) ...[DangerButton('Cancelar', onPressed: () => c.act(v.id, 'stop')), const SizedBox(width: 6)],
      IconButton(
        tooltip: 'Excluir vídeo',
        visualDensity: VisualDensity.compact,
        onPressed: () => c.act(v.id, 'delete'),
        icon: const Icon(Icons.delete_outline, size: 19, color: Tokens.dim),
      ),
    ];
  }
}

class _Dot extends StatelessWidget {
  const _Dot(this.state);
  final String state;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      'done' => Tokens.accent,
      'cur' => Tokens.run,
      'err' => Tokens.err,
      _ => Tokens.border,
    };
    return Container(
      width: 9,
      height: 9,
      margin: const EdgeInsets.only(right: 4),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3)),
    );
  }
}

/// The status chip (Pronto, Rodando…); a finished edit sent to YouTube says
/// "Publicado", with the details on hover.
class StatusChip extends StatelessWidget {
  const StatusChip(this.v, {super.key});
  final VideoSummary v;

  static const labels = {
    'done': 'Pronto',
    'running': 'Rodando',
    'failed': 'Falhou',
    'idle': 'Parado',
    'queued': 'Na fila',
    'interrupted': 'Interrompido',
  };

  @override
  Widget build(BuildContext context) {
    final p = v.published;
    if (v.status == VideoStatus.done && p != null) {
      final parts = [p.publishedAt != null ? 'Enviado ao YouTube em ${when(p.publishedAt)}' : 'Enviado ao YouTube'];
      if (p.publishAt != null) {
        parts.add('programado pra ${when(p.publishAt)}');
      } else if (_privacy[p.privacy] != null) {
        parts.add(_privacy[p.privacy]!);
      }
      if ((p.count ?? 0) > 1) parts.add('${p.count} envios');
      return Tooltip(
        message: parts.join(' · '),
        child: const Chip2('Publicado', color: Tokens.info),
      );
    }
    return Chip2(labels[v.status.value] ?? v.status.value, color: statusColor(v.status));
  }
}

Color statusColor(VideoStatus s) => switch (s) {
  VideoStatus.done => Tokens.ok,
  VideoStatus.running => Tokens.run,
  VideoStatus.failed => Tokens.err,
  VideoStatus.queued => Tokens.info,
  _ => Tokens.faint,
};

import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'edits/edits_screen.dart' show statusColor;
import 'format.dart';
import 'shell.dart';
import 'theme.dart';
import 'widgets.dart';

/// A short is vertical, a long horizontal: "Editar" ticks the matching type.
(String, VideoType?)? shapeOf(RecordingsRecordingsItem r) {
  final w = r.width, h = r.height;
  if (w == null || h == null || w == 0 || h == 0) return null;
  final ratio = w / h;
  if (ratio < .9) return ('Vertical', VideoType.short);
  if (ratio > 1.1) return ('Horizontal', VideoType.long);
  return ('Quadrado', null);
}

/// The edit made from a recording, by its status.
const _editLabel = {
  'done': 'Editado',
  'running': 'Editando',
  'queued': 'Na fila',
  'failed': 'Falhou',
  'idle': 'Parado',
  'interrupted': 'Parado',
};

/// Biblioteca (desktop/ui/js/recordings.js): the videos in the inbox
/// (Configurações → Pastas), subfolders included, what each one is and the
/// edits made from it; "Editar" opens Novo edit with it chosen.
class RecordingsScreen extends StatefulWidget {
  const RecordingsScreen({super.key, required this.client, required this.onEdit, required this.onSettings});

  final AutoEditClient client;
  final void Function(String path, VideoType? type) onEdit;

  /// "trocar pasta": Configurações.
  final VoidCallback onSettings;

  @override
  State<RecordingsScreen> createState() => _RecordingsScreenState();
}

class _RecordingsScreenState extends State<RecordingsScreen> {
  Recordings? _data;
  String? _error;
  String _query = '';
  final _search = TextEditingController();

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final data = await _api.listRecordings();
      if (mounted) setState(() => _data = data);
    } catch (e) {
      if (mounted) setState(() => _error = 'Não deu pra ler a pasta de entrada: ${errorText(e)}');
    }
  }

  Future<void> _openFolder() async {
    try {
      await _api.openFolder('inbox');
    } catch (e) {
      setState(() => _error = errorText(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final all = d?.recordings ?? const <RecordingsRecordingsItem>[];
    final shown = [
      for (final r in all)
        if (matchesQuery(_query, [r.name, r.folder, r.ext, shapeOf(r)?.$1, for (final e in r.edits) e.name])) r,
    ];
    final count = _query.trim().isNotEmpty
        ? '${shown.length} de ${all.length} vídeos'
        : '${all.length} vídeo${all.length == 1 ? '' : 's'}';
    final String? empty = d == null
        ? null
        : d.truncated
        ? 'Mostrando os ${all.length} vídeos mais recentes.'
        : !d.exists
        ? 'A pasta de entrada não existe mais: ${d.folder}.'
        : all.isEmpty
        ? 'Nenhum vídeo nesta pasta (nem nas subpastas). Grave ou copie seus vídeos pra cá.'
        : shown.isEmpty
        ? 'Nada encontrado pra “${_query.trim()}”.'
        : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TopBar(
          title: 'Biblioteca',
          subtitleWidget: d == null
              ? const Text('Lendo a pasta de entrada…', style: TextStyle(fontSize: 13, color: Tokens.dim))
              : Text.rich(
                  TextSpan(
                    style: const TextStyle(fontSize: 13, color: Tokens.dim),
                    children: [
                      TextSpan(text: '$count em '),
                      WidgetSpan(
                        alignment: PlaceholderAlignment.baseline,
                        baseline: TextBaseline.alphabetic,
                        child: Tooltip(
                          message: d.folder,
                          child: Text(
                            baseName(d.folder),
                            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Tokens.text),
                          ),
                        ),
                      ),
                      const TextSpan(text: ' · '),
                      link('trocar pasta', widget.onSettings),
                    ],
                  ),
                ),
          actions: [
            if (all.isNotEmpty) ...[
              SizedBox(
                width: 240,
                child: CallbackShortcuts(
                  bindings: {
                    const SingleActivator(LogicalKeyboardKey.escape): () {
                      _search.clear();
                      setState(() => _query = '');
                    },
                  },
                  child: TextField(
                    controller: _search,
                    onChanged: (q) => setState(() => _query = q),
                    style: const TextStyle(fontSize: 13.5),
                    decoration: fieldDecoration(hint: 'Buscar').copyWith(
                      prefixIcon: const Icon(Icons.search, size: 18, color: Tokens.faint),
                      prefixIconConstraints: const BoxConstraints(minWidth: 36),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
            ],
            IconButton.outlined(
              tooltip: 'Abrir a pasta',
              onPressed: _openFolder,
              icon: const Icon(Icons.folder_open_outlined, size: 18),
            ),
            const SizedBox(width: 6),
            IconButton.outlined(tooltip: 'Recarregar', onPressed: _load, icon: const Icon(Icons.refresh, size: 18)),
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
                ),
              for (final r in shown) _RecordingRow(r: r, client: widget.client, onEdit: widget.onEdit),
              if (empty != null)
                Padding(
                  padding: const EdgeInsets.all(28),
                  child: Column(
                    children: [
                      Text(
                        empty,
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Tokens.dim),
                      ),
                      if (d != null && (!d.exists || all.isEmpty))
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: TextButton(
                            onPressed: widget.onSettings,
                            child: Text(!d.exists ? 'Escolher outra em Configurações' : 'Escolher outra pasta'),
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _RecordingRow extends StatelessWidget {
  const _RecordingRow({required this.r, required this.client, required this.onEdit});
  final RecordingsRecordingsItem r;
  final AutoEditClient client;
  final void Function(String path, VideoType? type) onEdit;

  @override
  Widget build(BuildContext context) {
    final shape = shapeOf(r);
    final dims = r.width != null ? '${r.width}×${r.height} · ' : '';
    final edit = r.edits.firstOrNull;
    const mono = TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.dim);
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: Tokens.panel,
        border: Border.all(color: Tokens.borderSoft),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          VideoThumb(
            url: client.api.recordingThumbUri(path: r.path),
            headers: client.transport.headers,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Tooltip(
                  message: r.path,
                  child: Text(
                    r.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                  ),
                ),
                Text(
                  r.folder.isNotEmpty ? 'Pasta: ${r.folder}' : 'Pasta principal',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: Tokens.faint),
                ),
              ],
            ),
          ),
          SizedBox(width: 70, child: Text(duration(r.duration), style: mono)),
          SizedBox(
            width: 230,
            child: Row(
              children: [
                if (shape != null)
                  Badge2(
                    shape.$1,
                    color: shape.$2 == VideoType.short
                        ? const Color(0xFFC084FC)
                        : shape.$2 == VideoType.long
                        ? Tokens.accent
                        : Tokens.dim,
                  ),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(
                    '$dims${r.ext.toUpperCase()}',
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: Tokens.faint),
                  ),
                ),
              ],
            ),
          ),
          SizedBox(width: 80, child: Text(humanSize(r.size), style: mono)),
          SizedBox(width: 130, child: Text(when(r.modified), style: mono)),
          SizedBox(
            width: 190,
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerRight,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (edit != null)
                    Tooltip(
                      message: '${edit.name ?? edit.id}${r.edits.length > 1 ? ' (+${r.edits.length - 1})' : ''}',
                      child: Chip2(
                        '${_editLabel[edit.status.value] ?? edit.status.value}'
                        '${r.edits.length > 1 ? ' ×${r.edits.length}' : ''}',
                        color: statusColor(edit.status),
                      ),
                    ),
                  const SizedBox(width: 8),
                  SmallButton('Editar', primary: true, onPressed: () => onEdit(r.path, shape?.$2)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

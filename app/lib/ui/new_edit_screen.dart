import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../platform.dart';
import 'format.dart';
import 'shell.dart';
import 'theme.dart';
import 'video_pick.dart';
import 'widgets.dart';

/// Novo edit (desktop/ui/js/new-edit.js): pick a video, describe it, start
/// the pipeline. Everything `auto-edit short|long` takes is here; the extras
/// under "Opções", filled from Configurações.
class NewEditScreen extends StatefulWidget {
  const NewEditScreen({
    super.key,
    required this.client,
    required this.pickers,
    required this.onStarted,
    required this.onCancel,
    this.path,
    this.type,
  });

  final AutoEditClient client;
  final Pickers pickers;

  /// The video already chosen (Biblioteca, a drop on Edições) and, when the
  /// caller knows its shape, the matching type.
  final String? path;
  final VideoType? type;

  /// The edit is running: its id.
  final ValueChanged<String> onStarted;
  final VoidCallback onCancel;

  @override
  State<NewEditScreen> createState() => _NewEditScreenState();
}

class _NewEditScreenState extends State<NewEditScreen> {
  AutoEditApi get _api => widget.client.api;

  VideoFile? _video;
  VideoType? _type;
  final _name = TextEditingController();
  final _context = TextEditingController();
  final _iterations = TextEditingController(text: '3');
  final _overlays = TextEditingController();
  String _language = 'pt';
  String _whisper = 'small';
  bool _coldOpen = true;
  bool _reorder = true;
  bool _dryRun = false;
  bool _busy = false;
  bool _picking = false;
  bool _over = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _type = widget.type;
    unawaited(_defaults());
    if (widget.path != null) unawaited(_use(widget.path!));
  }

  @override
  void dispose() {
    for (final t in [_name, _context, _iterations, _overlays]) {
      t.dispose();
    }
    super.dispose();
  }

  /// The defaults from Configurações (engine offline: the form's own).
  Future<void> _defaults() async {
    try {
      final s = await _api.getSettings();
      if (!mounted) return;
      setState(() {
        _language = s.language ?? _language;
        _whisper = s.whisperModel ?? _whisper;
        _coldOpen = s.coldOpen ?? _coldOpen;
        _reorder = s.reorder ?? _reorder;
        if (s.overlaysDir != null && _overlays.text.isEmpty) _overlays.text = s.overlaysDir!;
      });
    } catch (_) {}
  }

  /// A path from the dialog or a drop: the engine checks it's a video and
  /// fills in the size.
  Future<void> _use(String path) async {
    setState(() => _error = null);
    if (!isVideo(path)) {
      setState(() => _error = notVideo);
      return;
    }
    try {
      final v = await _api.videoFileInfo(path: path);
      if (mounted) setState(() => _video = v);
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    }
  }

  Future<void> _pick() async {
    if (_picking) return;
    setState(() {
      _picking = true;
      _error = null;
    });
    try {
      String? inbox;
      try {
        inbox = (await _api.getFolders()).inbox.path;
      } catch (_) {}
      final path = await widget.pickers.video(initial: inbox);
      if (path != null) await _use(path);
    } finally {
      if (mounted) setState(() => _picking = false);
    }
  }

  bool get _ready => _video != null && _type != null && !_busy;

  Future<void> _start() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final name = _name.text.trim();
      final context = _context.text.trim();
      final r = await _api.startEdit(
        EditRequest(
          videoPath: _video!.path,
          type: _type!,
          context: context,
          language: _language,
          whisperModel: _whisper,
          maxIterations: int.tryParse(_iterations.text) ?? 3,
          dryRun: _dryRun,
          coldOpen: _coldOpen,
          reorder: _reorder,
          overlaysDir: _type == VideoType.long && _overlays.text.trim().isNotEmpty ? _overlays.text.trim() : null,
          name: name.isEmpty ? null : name,
        ),
      );
      widget.onStarted(r.videoId);
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _step(int n) => Container(
    width: 28,
    height: 28,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      border: Border.all(color: Tokens.border),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Text(
      '$n',
      style: const TextStyle(fontFamily: Tokens.mono, fontSize: 13, color: Tokens.dim),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final v = _video;
    return VideoDrop(
      onOver: (on) => setState(() => _over = on),
      onVideo: _use,
      onFail: (e) => setState(() => _error = e),
      child: FormScreen(
        top: TopBar(
          title: 'Novo edit',
          subtitle: 'Escolha o vídeo, diga do que ele trata e o pipeline assume',
          actions: [
            OutlinedButton(onPressed: widget.onCancel, child: const Text('Cancelar')),
            const SizedBox(width: 8),
            FilledButton(onPressed: _ready ? _start : null, child: Text(_busy ? 'Iniciando…' : 'Iniciar edição')),
          ],
        ),
        children: [
          if (_error != null) Notice(_error!),
          Panel(
            leading: _step(1),
            title: 'Vídeo',
            subtitle: const Text('O arquivo que vai ser editado.'),
            children: [
              if (v == null)
                _DropZone(over: _over, busy: _picking, onTap: _pick)
              else
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Tokens.panel2,
                    border: Border.all(color: _over ? Tokens.accent : Tokens.border),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.movie_outlined, color: Tokens.accent),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Flexible(
                                  child: Text(
                                    v.name,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(fontWeight: FontWeight.w600),
                                  ),
                                ),
                                const SizedBox(width: 10),
                                Text(
                                  humanSize(v.size),
                                  style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.faint),
                                ),
                              ],
                            ),
                            Tooltip(
                              message: v.path,
                              child: Text(
                                v.path,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: Tokens.faint),
                              ),
                            ),
                          ],
                        ),
                      ),
                      SmallButton('Trocar', onPressed: _pick),
                    ],
                  ),
                ),
              const SizedBox(height: 14),
              const Text.rich(
                TextSpan(
                  text: 'Nome da edição ',
                  style: TextStyle(fontSize: 13, color: Tokens.dim),
                  children: [
                    TextSpan(
                      text: 'opcional',
                      style: TextStyle(fontStyle: FontStyle.italic, color: Tokens.faint, fontSize: 12),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 6),
              TextField(
                controller: _name,
                maxLength: 120,
                decoration: fieldDecoration(
                  // Left blank, the edit keeps the file's name: show which one.
                  hint: v == null
                      ? 'Sem nome, usa o nome do arquivo'
                      : 'Sem nome, usa “${v.name.replaceFirst(RegExp(r'\.[^.]+$'), '')}”',
                ).copyWith(counterText: ''),
              ),
            ],
          ),
          Panel(
            leading: _step(2),
            title: 'Tipo',
            subtitle: const Text('Define o formato do corte e quais stages rodam.'),
            children: [
              RadioGroup<VideoType>(
                groupValue: _type,
                onChanged: (t) => setState(() => _type = t),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: _Choice(
                        value: VideoType.short,
                        selected: _type == VideoType.short,
                        title: 'Short',
                        desc: 'Pra Reels, Shorts e TikTok',
                        items: const [
                          'Vertical 9:16 (recorta o centro se gravou na horizontal)',
                          'Corta pausas, repetições e tropeços',
                          'Legenda animada na tela, estilo CapCut',
                          'Capa, título, gancho e hashtags',
                        ],
                        skip: 'lower third e CTA na tela',
                        onTap: () => setState(() => _type = VideoType.short),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: _Choice(
                        value: VideoType.long,
                        selected: _type == VideoType.long,
                        title: 'Long',
                        desc: 'Pra vídeo no YouTube',
                        items: const [
                          'Mantém o formato original (horizontal)',
                          'Curadoria: tira os blocos que não rendem e acha a duração certa',
                          'Lower third com seu nome e CTA animados',
                          'Thumbnail, título (3 opções) e descrição',
                        ],
                        skip: 'legenda na tela (vai como .srt ao publicar)',
                        onTap: () => setState(() => _type = VideoType.long),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          Panel(
            leading: _step(3),
            title: 'Contexto',
            subtitle: const Text('O que o planner precisa saber pra cortar bem — tema, tom, o que não pode sumir.'),
            children: [
              TextField(
                controller: _context,
                minLines: 3,
                maxLines: 6,
                decoration: fieldDecoration(hint: 'review de produto tech, tom direto, manter as comparações de preço'),
              ),
            ],
          ),
          Panel(children: [_options()]),
        ],
      ),
    );
  }

  Widget _options() {
    Widget select(String label, String value, List<String> options, ValueChanged<String> onChanged) => Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
        const SizedBox(height: 6),
        DropdownButtonFormField<String>(
          key: ValueKey('$label-$value'),
          initialValue: options.contains(value) ? value : options.first,
          decoration: fieldDecoration(),
          dropdownColor: Tokens.panel,
          style: const TextStyle(fontFamily: Tokens.font, fontSize: 13.5, color: Tokens.text),
          items: [for (final o in options) DropdownMenuItem(value: o, child: Text(o))],
          onChanged: (v) {
            if (v != null) setState(() => onChanged(v));
          },
        ),
      ],
    );
    Widget check(String text, bool value, ValueChanged<bool> onChanged) => CheckboxListTile(
      value: value,
      onChanged: (v) => setState(() => onChanged(v ?? false)),
      controlAffinity: ListTileControlAffinity.leading,
      contentPadding: EdgeInsets.zero,
      dense: true,
      title: Text(text, style: const TextStyle(fontSize: 13.5)),
    );
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        title: const Text('Opções', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
        expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: select('Idioma', _language, const ['pt', 'en', 'es'], (v) => _language = v)),
              const SizedBox(width: 14),
              Expanded(
                child: select('Modelo Whisper', _whisper, const [
                  'tiny',
                  'base',
                  'small',
                  'medium',
                  'large',
                ], (v) => _whisper = v),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Máx. iterações', style: TextStyle(fontSize: 13, color: Tokens.dim)),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _iterations,
                      keyboardType: TextInputType.number,
                      decoration: fieldDecoration(),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (_type == VideoType.long) ...[
            const SizedBox(height: 12),
            const Text('Pasta de overlays', style: TextStyle(fontSize: 13, color: Tokens.dim)),
            const SizedBox(height: 6),
            TextField(
              controller: _overlays,
              style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5),
              decoration: fieldDecoration(hint: '(padrão do projeto)'),
            ),
          ],
          const SizedBox(height: 8),
          check('Cold open — abre o vídeo com o melhor momento antes da abertura', _coldOpen, (v) => _coldOpen = v),
          check(
            'Reordenar — o agente pode mudar a ordem dos blocos (ex.: demo antes da explicação)',
            _reorder,
            (v) => _reorder = v,
          ),
          check('Dry-run — planeja e mostra os cortes sem renderizar', _dryRun, (v) => _dryRun = v),
        ],
      ),
    );
  }
}

class _DropZone extends StatelessWidget {
  const _DropZone({required this.over, required this.busy, required this.onTap});
  final bool over;
  final bool busy;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: over ? Tokens.accent.withValues(alpha: .06) : Tokens.panel2,
    shape: RoundedRectangleBorder(
      side: BorderSide(color: over ? Tokens.accent : Tokens.border),
      borderRadius: BorderRadius.circular(12),
    ),
    child: InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: busy ? null : onTap,
      child: const Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Column(
          children: [
            Icon(Icons.upload_outlined, size: 28, color: Tokens.accent),
            SizedBox(height: 8),
            Text('Arraste o vídeo pra cá', style: TextStyle(fontWeight: FontWeight.w600)),
            SizedBox(height: 4),
            Text.rich(
              TextSpan(
                style: TextStyle(fontSize: 13, color: Tokens.dim),
                children: [
                  TextSpan(text: 'ou '),
                  TextSpan(
                    text: 'escolha no computador',
                    style: TextStyle(decoration: TextDecoration.underline),
                  ),
                ],
              ),
            ),
            SizedBox(height: 6),
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

class _Choice extends StatelessWidget {
  const _Choice({
    required this.value,
    required this.selected,
    required this.title,
    required this.desc,
    required this.items,
    required this.skip,
    required this.onTap,
  });

  final VideoType value;
  final bool selected;
  final String title;
  final String desc;
  final List<String> items;
  final String skip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: selected ? Tokens.accent.withValues(alpha: .06) : Tokens.panel2,
    shape: RoundedRectangleBorder(
      side: BorderSide(color: selected ? Tokens.accent : Tokens.border),
      borderRadius: BorderRadius.circular(12),
    ),
    child: InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(6, 12, 14, 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Radio<VideoType>(value: value),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                      TypeBadge(value),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(desc, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
                  const SizedBox(height: 8),
                  for (final i in items)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Text('• $i', style: const TextStyle(fontSize: 12.5, color: Tokens.dim, height: 1.4)),
                    ),
                  Text.rich(
                    TextSpan(
                      style: const TextStyle(fontSize: 12.5, color: Tokens.faint, height: 1.4),
                      children: [
                        const TextSpan(text: '• '),
                        const TextSpan(
                          text: 'Pula',
                          style: TextStyle(fontWeight: FontWeight.w600),
                        ),
                        TextSpan(text: ' $skip'),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

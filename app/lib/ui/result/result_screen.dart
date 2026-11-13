import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../edits/edits_screen.dart' show StatusChip, statusColor;
import '../format.dart';
import '../player.dart';
import '../shell.dart';
import '../theme.dart';
import '../widgets.dart';
import 'caption_adjust.dart';
import 'publish_card.dart';

/// What metadata wrote, in the order the Tauri screen shows it.
const metaFields = [
  ('short_title', 'Título do short'),
  ('hook', 'Gancho'),
  ('youtube_title', 'Título do YouTube'),
  ('youtube_description', 'Descrição'),
  ('hashtags', 'Hashtags'),
  ('tags', 'Tags'),
  ('pinned_comment', 'Comentário pra fixar'),
];

const fileLabels = {
  'video': 'Vídeo final',
  'thumbnail': 'Thumbnail A',
  'thumbnail_b': 'Thumbnail B',
  'thumbnail_c': 'Thumbnail C',
  'captions': 'Legendas (.srt)',
  'notes': 'Metadata (.txt)',
};

const _qa = {
  'aprovada': ('QA aprovou', Tokens.ok),
  'reprovada': ('QA reprovou', Tokens.err),
  'parcial': ('QA parcial', Tokens.faint),
};

/// Resultado (desktop/ui/js/result.js): the finished video playing, its
/// thumbnail(s), the files and the text to post; a short's caption is
/// adjusted on the video, and the Publicar card sends it to YouTube.
class ResultScreen extends StatefulWidget {
  const ResultScreen({
    super.key,
    required this.client,
    required this.id,
    required this.onBack,
    required this.onPipeline,
    required this.onSettings,
    this.onShorts,
  });

  final AutoEditClient client;
  final String id;
  final VoidCallback onBack;

  /// After "Regravar legenda": the pipeline, running it.
  final VoidCallback onPipeline;

  /// Configurações → YouTube (no Google credential yet).
  final VoidCallback onSettings;

  /// "Gerar shorts" on a finished long (#142); null: no button.
  final VoidCallback? onShorts;

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  Result? _r;
  String? _error;
  String? _thumbView;
  bool _choosing = false;
  bool _adjusting = false;

  /// Cache-buster: a re-rendered file has the same URL.
  final _stamp = DateTime.now().millisecondsSinceEpoch;
  final _publishKey = GlobalKey<PublishCardState>();

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final r = await _api.getResult(widget.id);
      if (!mounted) return;
      setState(() {
        _r = r;
        _error = null;
        if (!r.thumbnails.any((t) => t.id == _thumbView)) {
          _thumbView = (r.thumbnails.where((t) => t.chosen).firstOrNull ?? r.thumbnails.firstOrNull)?.id;
        }
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'Não deu pra ler o resultado: ${errorText(e)}');
    }
  }

  Uri _file(ArtifactKind kind) => _api.getFileUri(widget.id, kind).replace(queryParameters: {'t': '$_stamp'});

  Future<void> _use(String variant) async {
    setState(() => _choosing = true);
    try {
      final res = await _api.chooseThumbnail(widget.id, ChooseThumbnailRequest(variant: variant));
      final r = _r!;
      setState(
        () => _r = Result(
          id: r.id,
          name: r.name,
          videoName: r.videoName,
          type: r.type,
          status: r.status,
          metadata: r.metadata,
          files: r.files,
          thumbnails: res.thumbnails,
          tokenStats: r.tokenStats,
        ),
      );
      _publishKey.currentState?.thumbnailChosen(variant);
    } catch (e) {
      setState(() => _error = 'Não deu pra escolher a thumbnail: ${errorText(e)}');
    } finally {
      if (mounted) setState(() => _choosing = false);
    }
  }

  Future<void> _reveal(String kind) async {
    try {
      await _api.openFile(widget.id, kind, body: const OpenFileRequest(reveal: true));
    } catch (e) {
      setState(() => _error = 'Não deu pra abrir: ${errorText(e)}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _r;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TopBar(
          title: r == null ? widget.id : (r.name ?? r.videoName),
          onBack: widget.onBack,
          subtitleWidget: r == null
              ? null
              : Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Row(
                    children: [
                      TypeBadge(r.type),
                      const SizedBox(width: 8),
                      Chip2(
                        r.status == VideoStatus.interrupted
                            ? 'Interrompido'
                            : StatusChip.labels[r.status.value] ?? r.status.value,
                        color: statusColor(r.status),
                      ),
                    ],
                  ),
                ),
          actions: [
            if (r != null && r.type == VideoType.long && r.status == VideoStatus.done && widget.onShorts != null)
              FilledButton(onPressed: widget.onShorts, child: const Text('Gerar shorts')),
          ],
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
            children: [
              if (_error != null) Notice(_error!),
              if (r == null && _error == null)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(child: CircularProgressIndicator()),
                ),
              if (r != null) ...[
                if (r.files.containsKey('video')) _watch(r),
                _filesAndMeta(r),
                PublishCard(key: _publishKey, client: widget.client, id: widget.id, onSettings: widget.onSettings),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _watch(Result r) {
    final short = r.type == VideoType.short;
    final ratio = short ? 9 / 16 : 16 / 9;
    final canAdjust = short && r.status == VideoStatus.done;
    final player = AspectRatio(
      aspectRatio: ratio,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: VideoPlayer(PlayerSource(_file(ArtifactKind.video), headers: widget.client.transport.headers)),
      ),
    );
    final thumbs = r.thumbnails.isEmpty ? null : _thumbs(r);
    final stage = canAdjust
        ? CaptionAdjuster(
            client: widget.client,
            id: widget.id,
            player: player,
            ratio: ratio,
            onAdjusting: (on) => setState(() => _adjusting = on),
            onRecorded: widget.onPipeline,
          )
        : player;
    return Panel(
      title: 'Vídeo final',
      subtitle: Text(_adjusting ? 'Ajustando a legenda: arraste a faixa no vídeo.' : 'Do jeito que vai ser publicado.'),
      children: [
        LayoutBuilder(
          builder: (context, box) {
            final wide = box.maxWidth > 820;
            // A short is tall: it never takes the whole width.
            final watch = ConstrainedBox(
              constraints: BoxConstraints(maxHeight: short ? 560 : double.infinity),
              child: stage,
            );
            if (thumbs == null) return watch;
            if (!wide) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [thumbs, const SizedBox(height: 18), watch],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: short ? 300 : box.maxWidth * .36, child: thumbs),
                const SizedBox(width: 20),
                Expanded(child: watch),
              ],
            );
          },
        ),
      ],
    );
  }

  Widget _thumbs(Result r) {
    final view = r.thumbnails.firstWhere((t) => t.id == _thumbView, orElse: () => r.thumbnails.first);
    final many = r.thumbnails.length > 1;
    final qa = _qa[view.qa];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: 8),
          child: Text('Thumbnail', style: TextStyle(fontSize: 12, color: Tokens.faint, letterSpacing: .4)),
        ),
        if (many)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: SegmentedButton<String>(
              showSelectedIcon: false,
              segments: [
                for (final t in r.thumbnails)
                  ButtonSegment(
                    value: t.id,
                    label: Text(t.id),
                    icon: t.chosen ? const Icon(Icons.check, size: 15) : null,
                    tooltip: t.chosen ? '${t.layout} · vai na publicação' : t.layout,
                  ),
              ],
              selected: {view.id},
              onSelectionChanged: (s) => setState(() => _thumbView = s.first),
            ),
          ),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: AspectRatio(
            aspectRatio: 16 / 9,
            child: Image.network(
              _file(view.kind).toString(),
              headers: widget.client.transport.headers,
              fit: BoxFit.cover,
              semanticLabel: 'thumbnail ${view.id}: ${view.layout}',
              errorBuilder: (_, _, _) => const ColoredBox(color: Tokens.panel2),
            ),
          ),
        ),
        if (many) ...[
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: Text('${view.id} · ${view.layout}', style: const TextStyle(fontSize: 13, color: Tokens.dim)),
              ),
              if (qa != null) Chip2(qa.$1, color: qa.$2),
            ],
          ),
          for (final why in view.qaReasons)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('•  $why', style: const TextStyle(fontSize: 12.5, color: Tokens.dim)),
            ),
          const SizedBox(height: 10),
          if (view.chosen)
            const Row(
              children: [
                Icon(Icons.check, size: 16, color: Tokens.ok),
                SizedBox(width: 6),
                Text('vai na publicação', style: TextStyle(fontSize: 13, color: Tokens.ok)),
              ],
            )
          else if (r.type != VideoType.short)
            Align(
              alignment: Alignment.centerLeft,
              child: SmallButton('Usar esta na publicação', onPressed: _choosing ? null : () => _use(view.id)),
            ),
          const SizedBox(height: 8),
          const Text(
            'A API do YouTube envia uma só. Pra rodar o Testar e comparar, suba as outras no Studio '
            '(estão na pasta, em Arquivos).',
            style: TextStyle(fontSize: 12, color: Tokens.faint, height: 1.4),
          ),
        ],
      ],
    );
  }

  Widget _filesAndMeta(Result r) {
    final kinds = [
      for (final k in fileLabels.keys)
        if (r.files.containsKey(k)) k,
    ];
    final meta = r.metadata ?? const <String, Object?>{};
    final rows = [
      for (final (key, label) in metaFields)
        if (meta[key] != null && _text(meta[key]).trim().isNotEmpty) (label, meta[key]!),
    ];
    return Panel(
      title: 'Arquivos',
      subtitle: const Text('O que ficou na pasta de saída.'),
      children: [
        if (kinds.isEmpty)
          const Text(
            'Nada na pasta de saída ainda — o vídeo aparece aqui quando o pipeline termina.',
            style: TextStyle(color: Tokens.dim, fontSize: 13),
          ),
        for (final k in kinds)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              children: [
                Expanded(child: Text(fileLabels[k]!, style: const TextStyle(fontSize: 13.5))),
                Text(
                  humanSize(r.files[k]!.size),
                  style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.faint),
                ),
                const SizedBox(width: 6),
                IconButton(
                  tooltip: 'Mostrar ${fileLabels[k]} na pasta',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => _reveal(k),
                  icon: const Icon(Icons.folder_open_outlined, size: 18, color: Tokens.dim),
                ),
              ],
            ),
          ),
        const Divider(height: 32),
        const Text('Dados para publicação', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const Padding(
          padding: EdgeInsets.only(top: 4, bottom: 14),
          child: Text('Gerado no stage metadata — copie e poste.', style: TextStyle(fontSize: 13, color: Tokens.dim)),
        ),
        if (rows.isEmpty)
          const Text(
            'Sem metadata ainda — ela sai no fim do pipeline.',
            style: TextStyle(color: Tokens.dim, fontSize: 13),
          ),
        for (final (label, value) in rows) _MetaField(label: label, value: value),
      ],
    );
  }
}

String _text(Object? v) => v is List ? v.join(', ') : '$v';

class _MetaField extends StatefulWidget {
  const _MetaField({required this.label, required this.value});
  final String label;
  final Object value;

  @override
  State<_MetaField> createState() => _MetaFieldState();
}

class _MetaFieldState extends State<_MetaField> {
  bool _copied = false;
  Timer? _t;

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _copy() async {
    final v = widget.value;
    await Clipboard.setData(ClipboardData(text: v is List ? v.map((t) => '#$t').join(' ') : '$v'));
    setState(() => _copied = true);
    _t?.cancel();
    _t = Timer(const Duration(milliseconds: 1600), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.value;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(widget.label, style: const TextStyle(fontSize: 12, color: Tokens.faint, letterSpacing: .4)),
              const SizedBox(width: 4),
              IconButton(
                tooltip: _copied ? 'Copiado' : 'Copiar ${widget.label}',
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                onPressed: _copy,
                icon: Icon(_copied ? Icons.check : Icons.copy_outlined, color: _copied ? Tokens.ok : Tokens.dim),
              ),
            ],
          ),
          if (v is List)
            Wrap(spacing: 6, runSpacing: 6, children: [for (final t in v) Badge2('$t', color: Tokens.dim)])
          else
            SelectableText('$v', style: const TextStyle(fontSize: 14, height: 1.5)),
        ],
      ),
    );
  }
}

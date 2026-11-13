import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../format.dart';
import '../theme.dart';
import '../widgets.dart';

const privacyLabel = {'private': 'Privado', 'unlisted': 'Não listado', 'public': 'Público'};

/// What metadata couldn't write comes marked "[REVISAR] …": the field starts
/// empty with the instruction as its hint, never sent.
final _review = RegExp(r'\[REVISAR\]\s*', caseSensitive: false);
bool needsReview(String? text) => RegExp(r'^\s*\[REVISAR\]', caseSensitive: false).hasMatch(text ?? '');

/// (value, hint) for a field filled from metadata.
(String, String?) reviewed(String? text) {
  if (needsReview(text)) return ('', text!.replaceAll(_review, '').trim());
  return ((text ?? '').replaceAll(_review, ''), null);
}

/// How a sent video stands now: YouTube's word when it could be asked (a
/// scheduled one goes public by itself), else what was sent.
sealed class Standing {
  const Standing();
}

class Gone extends Standing {
  const Gone();
}

class Live extends Standing {
  const Live(this.privacy, this.status, this.tone);
  final String privacy;
  final String status;
  final Color tone;
}

Standing standingOf(PublishStatePublishedItem p, GetPublishLiveResponse? live, {DateTime? now}) {
  final l = live != null && live.checked ? live.videos[p.videoId] : null;
  final gone = live != null && live.checked ? l == null : (p.removed ?? false);
  if (gone) return const Gone();
  final raw = l?.privacy ?? p.privacy;
  final privacy = privacyLabel.containsKey(raw) ? raw! : 'private';
  final at = l != null ? l.publishAt : p.publishAt;
  if (['rejected', 'failed', 'deleted'].contains(l?.uploadStatus)) {
    return Live(privacy, 'Recusado pelo YouTube', Tokens.err);
  }
  final date = at == null ? null : DateTime.tryParse(at);
  if (privacy == 'private' && date != null && (l != null || date.isAfter(now ?? DateTime.now()))) {
    return Live(privacy, 'Programado pra ${when(at)}', Tokens.info);
  }
  if (privacy == 'private') return Live(privacy, 'Enviado', Tokens.dim);
  return Live(privacy, 'Publicado', Tokens.ok);
}

/// Publicar no YouTube (desktop/ui/js/publish.js), the card at the foot of
/// Resultado: connect the account, a form filled from metadata, sending
/// with progress (SSE), and what was already sent with where it stands.
class PublishCard extends StatefulWidget {
  const PublishCard({
    super.key,
    required this.client,
    required this.id,
    required this.onSettings,
    this.pollEvery = const Duration(seconds: 2),
  });

  final AutoEditClient client;
  final String id;
  final VoidCallback onSettings;
  final Duration pollEvery;

  @override
  State<PublishCard> createState() => PublishCardState();
}

class PublishCardState extends State<PublishCard> {
  PublishState? _d;
  GetPublishLiveResponse? _live;
  bool _liveAsked = false;
  String? _error;
  bool _tried = false;
  bool _again = false;
  bool _filled = false;
  bool _sending = false;

  /// Upload progress while a publish job runs.
  int? _pct;
  StreamSubscription<JobEvent>? _stream;
  Timer? _poll;

  final _title = TextEditingController();
  final _desc = TextEditingController();
  final _tags = TextEditingController();
  final _comment = TextEditingController();
  String? _titleHint, _descHint, _commentHint;
  String _privacy = 'private';
  DateTime? _at;
  bool _captions = false;
  bool _commentOn = false;

  AutoEditApi get _api => widget.client.api;

  @override
  void initState() {
    super.initState();
    _title.addListener(() => setState(() {}));
    unawaited(_load());
  }

  @override
  void dispose() {
    unawaited(_stream?.cancel());
    _poll?.cancel();
    for (final c in [_title, _desc, _tags, _comment]) {
      c.dispose();
    }
    super.dispose();
  }

  /// Resultado picked another A/B/C: the note under the form follows.
  void thumbnailChosen(String variant) {
    final d = _d;
    if (d == null) return;
    setState(() => _d = _withVariant(d, variant));
  }

  Future<void> _load() async {
    final PublishState d;
    try {
      d = await _api.getPublish(widget.id);
    } catch (_) {
      if (mounted) setState(() => _d = null);
      return;
    }
    if (!mounted) return;
    setState(() => _d = d);
    if (d.job?.status == 'running') _openStream();
    if (d.published.isNotEmpty && d.account.connected && !_liveAsked) {
      _liveAsked = true;
      try {
        final live = await _api.getPublishLive(widget.id);
        if (mounted) setState(() => _live = live);
      } catch (_) {
        // offline: the card keeps what publish.json says
      }
    }
  }

  void _fill(PublishState d) {
    final t = reviewed(d.defaults.title);
    final desc = reviewed(d.defaults.description);
    final c = reviewed(d.pinnedComment);
    _title.text = t.$1;
    _titleHint = t.$2;
    _desc.text = desc.$1;
    _descHint = desc.$2;
    _tags.text = (d.defaults.tags ?? const []).join(', ');
    _privacy = privacyLabel.containsKey(d.defaults.privacy) ? d.defaults.privacy! : 'private';
    _at = null;
    _captions = d.captions;
    _commentOn = false;
    _comment.text = c.$1;
    _commentHint = c.$2;
    _filled = true;
  }

  bool _gone(PublishStatePublishedItem p) => standingOf(p, _live) is Gone;

  void _openStream() {
    if (_stream != null) return;
    _pct ??= 0;
    _stream = _api
        .videoEvents(widget.id)
        .listen(
          (ev) {
            switch (ev.type) {
              case 'progress':
                setState(() => _pct = ev.pct);
              case 'done':
                _closeStream();
                _again = false;
                _liveAsked = false;
                unawaited(_load());
              case 'error':
                _closeStream();
                setState(() => _error = (ev.message ?? 'o envio falhou').replaceFirst(RegExp('^PublishError: '), ''));
                unawaited(_load());
            }
          },
          onError: (Object _) {
            _closeStream();
            unawaited(_load());
          },
          cancelOnError: true,
        );
  }

  void _closeStream() {
    unawaited(_stream?.cancel());
    _stream = null;
    if (mounted) setState(() => _pct = null);
  }

  Future<void> _connect() async {
    setState(() {
      _error = null;
      _tried = true;
    });
    try {
      final a = await _api.youtubeConnect();
      setState(() => _d = _withAccount(_d!, a));
    } catch (e) {
      setState(() => _error = errorText(e));
      return;
    }
    // The OAuth happens in the browser: follow it until it ends.
    _poll?.cancel();
    _poll = Timer.periodic(widget.pollEvery, (_) async {
      final YouTubeAccount a;
      try {
        a = await _api.youtubeAccount();
      } catch (_) {
        return;
      }
      if (!mounted) return;
      if (!a.connecting) {
        _poll?.cancel();
        _poll = null;
        unawaited(_load());
      } else {
        setState(() => _d = _withAccount(_d!, a));
      }
    });
  }

  Future<void> _cancelConnect() async {
    _poll?.cancel();
    _poll = null;
    try {
      await _api.youtubeConnectCancel();
    } catch (e) {
      setState(() => _error = errorText(e));
    }
    unawaited(_load());
  }

  Future<void> _publish() async {
    final d = _d!;
    setState(() {
      _error = null;
      _sending = true;
    });
    try {
      await _api.publishYoutube(
        widget.id,
        PublishRequest(
          title: _title.text.trim(),
          description: _desc.text,
          tags: [
            for (final t in _tags.text.split(','))
              if (t.trim().isNotEmpty) t.trim(),
          ],
          privacy: _privacy,
          publishAt: _at?.toUtc().toIso8601String(),
          force: d.published.isNotEmpty,
          captions: d.captions && _captions,
          comment: _commentOn ? _comment.text.trim() : null,
        ),
      );
      setState(() => _pct = 0);
      _openStream();
    } catch (e) {
      setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _pickWhen() async {
    final now = DateTime.now();
    final day = await showDatePicker(
      context: context,
      initialDate: _at ?? now.add(const Duration(days: 1)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
    );
    if (day == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: _at != null ? TimeOfDay.fromDateTime(_at!) : const TimeOfDay(hour: 18, minute: 0),
    );
    if (time == null) return;
    setState(() {
      _at = DateTime(day.year, day.month, day.day, time.hour, time.minute);
      _privacy = 'private'; // YouTube only schedules a private video
    });
  }

  Future<void> _open(String url) async {
    try {
      await _api.openUrl(OpenUrlRequest(url: url));
    } catch (e) {
      setState(() => _error = errorText(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    if (d == null || !d.eligible) return const SizedBox.shrink();
    final a = d.account;
    final line = a.connecting
        ? 'Aguardando você autorizar no navegador… Fechou a página? Cancele e conecte de novo.'
        : a.needsReconnect == true
        ? 'Reconecte pra liberar retenção e legendas (permissões novas)'
        : !a.connected
        ? (a.hasClientSecret ? 'Conta não conectada' : 'YouTube não configurado')
        : a.channel != null
        ? 'Conectado como ${a.channel}'
        : 'Conta conectada';
    final onYoutube = d.published.where((p) => !_gone(p)).toList();
    final running = _pct != null;
    final showForm = a.connected && !running && (onYoutube.isEmpty || _again);
    if (showForm && !_filled) _fill(d);
    return Panel(
      title: 'Publicar no YouTube',
      subtitle: Text(line),
      children: [
        if (_error != null) Notice(_error!),
        if (d.published.isNotEmpty) ...[
          for (final p in d.published.reversed) _Sent(p: p, standing: standingOf(p, _live), onOpen: _open),
          const SizedBox(height: 8),
        ],
        if (running)
          _Progress(pct: _pct!)
        else if (!a.connected)
          _connectBox(a)
        else if (!showForm)
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 10,
            children: [
              TextButton(
                onPressed: () => setState(() {
                  _again = true;
                  _filled = false;
                }),
                child: const Text('Enviar de novo'),
              ),
              const Text(
                'Cria outro vídeo no canal; o que já foi enviado continua lá.',
                style: TextStyle(fontSize: 13, color: Tokens.dim),
              ),
            ],
          )
        else
          _form(d, resend: onYoutube.isNotEmpty),
      ],
    );
  }

  Widget _connectBox(YouTubeAccount a) {
    final note = a.hasClientSecret
        ? (_tried && a.error != null
              ? 'Não conectou: ${a.error}'
              : 'Abre o navegador pra você autorizar o envio de vídeos pro seu canal.')
        : 'O YouTube ainda não está configurado neste computador. O passo a passo pra conectar está em '
              'Configurações → YouTube (é uma vez só).';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(note, style: const TextStyle(fontSize: 13.5, color: Tokens.dim, height: 1.45)),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          children: [
            if (a.hasClientSecret)
              FilledButton(
                onPressed: a.connecting ? null : _connect,
                child: Text(
                  a.connecting
                      ? 'Esperando autorização…'
                      : a.needsReconnect == true
                      ? 'Reconectar YouTube'
                      : 'Conectar YouTube',
                ),
              )
            else
              FilledButton(onPressed: widget.onSettings, child: const Text('Abrir Configurações')),
            if (a.connecting) OutlinedButton(onPressed: _cancelConnect, child: const Text('Cancelar')),
          ],
        ),
      ],
    );
  }

  Widget _form(PublishState d, {required bool resend}) {
    final len = _title.text.trim().length;
    final max = d.limits.title;
    final options = [
      for (final t in d.titleOptions ?? const <String>[])
        if (!needsReview(t)) t,
    ];
    final scheduled = _at != null;
    final notes = <String>[
      if (d.type == VideoType.short)
        'Short: o YouTube não aceita thumbnail personalizada pela API — ele escolhe o frame.'
      else if (d.thumbnail)
        d.thumbnailVariant != null && d.thumbnailVariant != 'A'
            ? 'A thumbnail ${d.thumbnailVariant} vai junto (escolhida no card do vídeo).'
            : 'A thumbnail gerada vai junto.',
      if (_commentOn && _privacy == 'private')
        'Vídeo privado não aceita comentário: escolha não listado/público ou poste depois pelo Studio.',
      if (d.nextVideo case {'title': final String t}) 'Tela final (últimos 20s, no Studio): indique "$t".',
      if (options.length > 1) 'Os outros títulos dá pra testar no Studio (Testar e comparar).',
      'Projeto do Google sem auditoria: o YouTube trava o vídeo como privado — aí é só liberar no Studio.',
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (resend)
          const Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: 'Enviar de novo  ',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  TextSpan(
                    text: 'Cria outro vídeo no canal; o que já foi enviado continua lá.',
                    style: TextStyle(color: Tokens.dim),
                  ),
                ],
              ),
              style: TextStyle(fontSize: 13),
            ),
          ),
        _label('Título', trailing: '$len/$max', bad: len > max),
        TextField(
          controller: _title,
          maxLength: 100,
          decoration: fieldDecoration(hint: _titleHint).copyWith(counterText: ''),
        ),
        if (options.length > 1)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in options)
                  ChoiceChip(
                    label: Text(t, style: const TextStyle(fontSize: 12.5)),
                    selected: _title.text.trim() == t,
                    onSelected: (_) => _title.text = t,
                  ),
              ],
            ),
          ),
        const SizedBox(height: 14),
        _label('Descrição'),
        TextField(
          controller: _desc,
          minLines: 4,
          maxLines: 10,
          decoration: fieldDecoration(hint: _descHint),
        ),
        const SizedBox(height: 14),
        _label('Tags (separadas por vírgula)'),
        TextField(controller: _tags, decoration: fieldDecoration()),
        const SizedBox(height: 14),
        Wrap(
          spacing: 18,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            SizedBox(
              width: 220,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _label('Visibilidade'),
                  DropdownButtonFormField<String>(
                    isExpanded: true,
                    initialValue: _privacy,
                    key: ValueKey('privacy-$_privacy-$scheduled'),
                    decoration: fieldDecoration(),
                    items: [for (final e in privacyLabel.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                    onChanged: scheduled ? null : (v) => setState(() => _privacy = v ?? 'private'),
                  ),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _label('Agendar'),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    OutlinedButton.icon(
                      onPressed: _pickWhen,
                      icon: const Icon(Icons.event_outlined, size: 18),
                      label: Text(_at == null ? 'Escolher data' : when(_at!.toIso8601String())),
                    ),
                    if (scheduled)
                      IconButton(
                        tooltip: 'Limpar agendamento',
                        onPressed: () => setState(() => _at = null),
                        icon: const Icon(Icons.close, size: 18),
                      ),
                  ],
                ),
              ],
            ),
          ],
        ),
        if (scheduled)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              'Agendado: fica privado até ${when(_at!.toIso8601String())} e vira público sozinho. '
              'Pra escolher outra visibilidade, limpe o agendamento.',
              style: const TextStyle(fontSize: 12.5, color: Tokens.dim),
            ),
          ),
        if (d.captions)
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            dense: true,
            value: _captions,
            onChanged: (v) => setState(() => _captions = v ?? false),
            title: const Text('Enviar a legenda (.srt da transcrição)', style: TextStyle(fontSize: 13.5)),
          ),
        if (d.pinnedComment != null) ...[
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            dense: true,
            value: _commentOn,
            onChanged: (v) => setState(() => _commentOn = v ?? false),
            title: const Text('Postar o comentário pra fixar', style: TextStyle(fontSize: 13.5)),
          ),
          if (_commentOn)
            TextField(
              controller: _comment,
              minLines: 2,
              maxLines: 5,
              decoration: fieldDecoration(hint: _commentHint),
            ),
        ],
        const SizedBox(height: 12),
        Text(notes.join(' '), style: const TextStyle(fontSize: 12.5, color: Tokens.faint, height: 1.45)),
        const SizedBox(height: 14),
        Row(
          children: [
            if (resend)
              OutlinedButton(
                onPressed: len == 0 || len > max || _sending ? null : _publish,
                child: const Text('Enviar de novo'),
              )
            else
              FilledButton(
                onPressed: len == 0 || len > max || _sending ? null : _publish,
                child: const Text('Enviar pro YouTube'),
              ),
            if (resend) ...[
              const SizedBox(width: 8),
              TextButton(
                onPressed: () => setState(() {
                  _again = false;
                  _error = null;
                }),
                child: const Text('Cancelar'),
              ),
            ],
          ],
        ),
      ],
    );
  }

  Widget _label(String text, {String? trailing, bool bad = false}) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Row(
      children: [
        Text(text, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
        if (trailing != null) ...[
          const SizedBox(width: 8),
          Text(
            trailing,
            style: TextStyle(fontFamily: Tokens.mono, fontSize: 11.5, color: bad ? Tokens.err : Tokens.faint),
          ),
        ],
      ],
    ),
  );
}

PublishState _copy(PublishState d, {YouTubeAccount? account, String? variant}) => PublishState(
  id: d.id,
  type: d.type,
  eligible: d.eligible,
  reason: d.reason,
  defaults: d.defaults,
  thumbnail: d.thumbnail,
  thumbnailVariant: variant ?? d.thumbnailVariant,
  captions: d.captions,
  pinnedComment: d.pinnedComment,
  titleOptions: d.titleOptions,
  nextVideo: d.nextVideo,
  limits: d.limits,
  published: d.published,
  account: account ?? d.account,
  job: d.job,
);

PublishState _withAccount(PublishState d, YouTubeAccount a) => _copy(d, account: a);
PublishState _withVariant(PublishState d, String v) => _copy(d, variant: v);

class _Progress extends StatelessWidget {
  const _Progress({required this.pct});
  final int pct;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Row(
        children: [
          const Expanded(child: Text('Enviando pro YouTube…', style: TextStyle(fontSize: 13.5))),
          Text(
            '$pct%',
            style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5, color: Tokens.dim),
          ),
        ],
      ),
      const SizedBox(height: 8),
      LinearProgressIndicator(value: pct / 100, minHeight: 6, borderRadius: BorderRadius.circular(3)),
    ],
  );
}

class _Sent extends StatelessWidget {
  const _Sent({required this.p, required this.standing, required this.onOpen});
  final PublishStatePublishedItem p;
  final Standing standing;
  final void Function(String url) onOpen;

  @override
  Widget build(BuildContext context) {
    final s = standing;
    final sub = [
      if (p.publishedAt != null) 'Enviado em ${when(p.publishedAt)}',
      if (p.captions == true) 'com legenda',
      if (p.commentId != null) 'com comentário',
    ].join(' · ');
    return Opacity(
      opacity: s is Gone ? .6 : 1,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Tokens.panel2,
          border: Border.all(color: Tokens.borderSoft),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        p.title ?? p.videoId ?? '',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                      ),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 6,
                        children: switch (s) {
                          Gone() => [const Chip2('Não está mais no YouTube', color: Tokens.err)],
                          Live(:final privacy, :final status, :final tone) => [
                            Chip2(privacyLabel[privacy]!, color: Tokens.dim),
                            Chip2(status, color: tone),
                          ],
                        },
                      ),
                      if (sub.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(sub, style: const TextStyle(fontSize: 12, color: Tokens.faint)),
                        ),
                    ],
                  ),
                ),
                if (s is! Gone && p.url != null) ...[
                  FilledButton.icon(
                    onPressed: () => onOpen(p.url!),
                    icon: const Icon(Icons.play_arrow, size: 18),
                    label: const Text('Ver no YouTube'),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton.icon(
                    onPressed: () =>
                        onOpen('https://studio.youtube.com/video/${Uri.encodeComponent(p.videoId ?? '')}/edit'),
                    icon: const Icon(Icons.open_in_new, size: 16),
                    label: const Text('Abrir no Studio'),
                  ),
                ],
              ],
            ),
            if (s is! Gone)
              for (final w in p.warnings ?? const <String>[]) _Warning(w),
          ],
        ),
      ),
    );
  }
}

/// "comentário não postado: `why`" → the what first, capitalized, in bold.
class _Warning extends StatelessWidget {
  const _Warning(this.w);
  final String w;

  @override
  Widget build(BuildContext context) {
    final at = w.indexOf(': ');
    final what = at > 0 ? w.substring(0, at) : w;
    final why = at > 0 ? w.substring(at + 2) : '';
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.warning_amber_rounded, size: 16, color: Tokens.run),
          const SizedBox(width: 8),
          Expanded(
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: what.isEmpty ? '' : what[0].toUpperCase() + what.substring(1),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  if (why.isNotEmpty) TextSpan(text: ': $why'),
                ],
              ),
              style: const TextStyle(fontSize: 12.5, color: Tokens.dim),
            ),
          ),
        ],
      ),
    );
  }
}

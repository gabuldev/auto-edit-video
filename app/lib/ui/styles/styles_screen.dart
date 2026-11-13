import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../platform.dart';
import '../shell.dart';
import '../theme.dart';
import '../widgets.dart';
import 'styles_controller.dart';

const _iconLabels = {'like': 'like', 'subscribe': 'inscrever', 'bell': 'sino', 'comment': 'comentar'};
const _previewLabels = {
  'thumbnail': 'Thumbnail',
  'lower_third': 'Nome na tela',
  'cta': 'Chamada pra se inscrever',
  'caption': 'Legenda',
};

/// "#2ee6c6" → Color (null if it isn't one).
Color? parseHex(Object? v) {
  if (v is! String) return null;
  final h = v.replaceFirst('#', '');
  if (!RegExp(r'^[0-9a-fA-F]{6}$').hasMatch(h)) return null;
  return Color(int.parse('ff$h', radix: 16));
}

/// Estilos — the brand, the gallery and the editor.
class StylesScreen extends StatefulWidget {
  const StylesScreen({super.key, required this.client, required this.pickers});

  final AutoEditClient client;
  final Pickers pickers;

  @override
  State<StylesScreen> createState() => _StylesScreenState();
}

class _StylesScreenState extends State<StylesScreen> {
  late final StylesController c = StylesController(widget.client)..load();
  final _name = TextEditingController();
  final _handle = TextEditingController();
  final _overlays = TextEditingController();
  final _draftName = TextEditingController();
  final _html = TextEditingController();
  bool _filled = false;

  @override
  void dispose() {
    c.dispose();
    for (final t in [_name, _handle, _overlays, _draftName, _html]) {
      t.dispose();
    }
    super.dispose();
  }

  Future<void> _pickLogo() async {
    final img = await widget.pickers.image();
    if (img != null) await c.uploadLogo(img.$1, img.$2);
  }

  Future<void> _import() async {
    final text = await widget.pickers.styleFile();
    if (text != null) await c.import(text);
  }

  Future<void> _pickOverlays() async {
    final dir = await widget.pickers.folder(initial: c.settings?.overlaysDir);
    if (dir == null) return;
    _overlays.text = dir;
    await c.saveOverlaysDir(dir);
  }

  void _zoom(Uint8List png) => showDialog<void>(
    context: context,
    builder: (context) => GestureDetector(
      onTap: () => Navigator.of(context).pop(),
      child: Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(40),
        child: InteractiveViewer(child: Image.memory(png)),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        final d = c.data;
        if (d != null && !_filled) {
          _filled = true;
          _name.text = c.name;
          _handle.text = c.handle;
          _overlays.text = c.settings?.overlaysDir ?? '';
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TopBar(
              title: 'Estilos',
              subtitle: 'A cara dos seus vídeos: thumbnail, nome na tela, chamada e legenda.',
              actions: [
                OutlinedButton.icon(
                  onPressed: _import,
                  icon: const Icon(Icons.file_open_outlined, size: 18),
                  label: const Text('Importar estilo'),
                ),
              ],
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(28, 20, 28, 40),
                children: [
                  if (c.error != null) Notice(c.error!),
                  if (d == null && c.error == null)
                    const Padding(
                      padding: EdgeInsets.all(32),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                  if (d != null) ...[
                    _brand(d),
                    const Padding(
                      padding: EdgeInsets.only(bottom: 12),
                      child: Text('Escolha um estilo', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                    ),
                    _gallery(d),
                    const SizedBox(height: 18),
                    if (c.current != null) _detail(d, c.current!),
                    _overlaysPanel(),
                  ],
                ],
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _brand(Styles d) {
    final b = d.brand;
    final accent = parseHex(getTok(c.shown ?? const {}, 'colors.accent')) ?? Tokens.accent;
    final own = parseHex(c.logoBg);
    final initial = ((c.name.trim().isNotEmpty ? c.name : b.name ?? '?').trim().characters.firstOrNull ?? '?')
        .toUpperCase();
    final logoUri = widget.client.api.getLogoUri().replace(queryParameters: {'v': '${c.logoVersion}'});
    return Panel(
      title: 'Sua marca',
      subtitle: const Text(
        'Aparece no nome na tela (lower third). Clique no círculo pra escolher a logo; ela substitui a inicial.',
      ),
      trailing: c.brandNote == null
          ? null
          : Text(c.brandNote!, style: const TextStyle(fontSize: 12.5, color: Tokens.ok)),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Stack(
              clipBehavior: Clip.none,
              children: [
                Tooltip(
                  message: 'Escolher a logo',
                  child: InkWell(
                    customBorder: const CircleBorder(),
                    onTap: _pickLogo,
                    child: Container(
                      width: 76,
                      height: 76,
                      clipBehavior: Clip.antiAlias,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: b.logo != null ? own ?? accent : Tokens.panel2,
                        border: Border.all(color: Tokens.border),
                      ),
                      alignment: Alignment.center,
                      child: b.logo != null
                          ? Image.network(
                              logoUri.toString(),
                              headers: widget.client.transport.headers,
                              fit: BoxFit.contain,
                              errorBuilder: (_, _, _) => Text(initial),
                            )
                          : Text(initial, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700)),
                    ),
                  ),
                ),
                Positioned(
                  right: -4,
                  bottom: -4,
                  child: IconButton.filledTonal(
                    tooltip: b.logo != null ? 'Remover a logo' : 'Escolher a logo',
                    visualDensity: VisualDensity.compact,
                    iconSize: 16,
                    onPressed: b.logo != null ? c.deleteLogo : _pickLogo,
                    icon: Icon(b.logo != null ? Icons.close : Icons.add),
                  ),
                ),
              ],
            ),
            const SizedBox(width: 22),
            Expanded(
              child: Wrap(
                spacing: 18,
                runSpacing: 14,
                children: [
                  SizedBox(
                    width: 280,
                    child: _field(
                      'Nome',
                      'O texto em destaque no nome na tela.',
                      TextField(
                        controller: _name,
                        maxLength: 40,
                        onChanged: c.setName,
                        decoration: fieldDecoration(
                          hint: b.name != null && c.name.isEmpty
                              ? 'padrão: ${b.name} (canal do YouTube)'
                              : 'seu nome ou do canal',
                        ).copyWith(counterText: ''),
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: _field(
                      '@ do canal',
                      'Aparece menor, embaixo do nome.',
                      TextField(
                        controller: _handle,
                        maxLength: 40,
                        onChanged: c.setHandle,
                        style: const TextStyle(fontFamily: Tokens.mono, fontSize: 13.5),
                        decoration: fieldDecoration(hint: '@seucanal').copyWith(counterText: ''),
                      ),
                    ),
                  ),
                  if (b.logo != null)
                    _field(
                      'Fundo da logo',
                      'Atrás da logo no vídeo (uma transparente mostra a cor).',
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          ChoiceChip(
                            label: const Text('Cor do estilo'),
                            avatar: CircleAvatar(backgroundColor: accent, radius: 7),
                            selected: c.logoBg == null,
                            onSelected: (_) => c.setLogoBg(null),
                          ),
                          const SizedBox(width: 8),
                          ColorButton(
                            color: own,
                            label: 'Outra cor',
                            selected: c.logoBg != null,
                            onChanged: (hex) => c.setLogoBg(hex),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _field(String label, String? desc, Widget child) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
      if (desc != null)
        Padding(
          padding: const EdgeInsets.only(top: 2, bottom: 6),
          child: Text(desc, style: const TextStyle(fontSize: 12, color: Tokens.faint)),
        )
      else
        const SizedBox(height: 6),
      child,
    ],
  );

  Widget _gallery(Styles d) => Wrap(
    spacing: 12,
    runSpacing: 12,
    children: [
      for (final s in d.styles)
        SizedBox(
          width: 220,
          child: Material(
            color: Tokens.panel,
            shape: RoundedRectangleBorder(
              side: BorderSide(
                color: s.id == c.selected ? Tokens.accent : Tokens.border,
                width: s.id == c.selected ? 2 : 1,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: () => c.select(s.id),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AspectRatio(
                    aspectRatio: 16 / 9,
                    child: switch (c.thumbs[s.id]) {
                      final Uint8List png => Image.memory(png, fit: BoxFit.cover, gaplessPlayback: true),
                      _ when c.thumbs.containsKey(s.id) => const ColoredBox(color: Tokens.panel2),
                      _ => const ColoredBox(
                        color: Tokens.panel2,
                        child: Center(
                          child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                        ),
                      ),
                    },
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
                    child: Row(
                      children: [
                        Container(
                          width: 12,
                          height: 12,
                          decoration: BoxDecoration(
                            color: parseHex(getTok(s.tokens, 'colors.accent')) ?? Tokens.accent,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            s.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5),
                          ),
                        ),
                        if (s.id == d.active)
                          const Badge2('em uso')
                        else if (!c.builtin(s))
                          const Badge2('seu', color: Tokens.dim),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
    ],
  );

  Widget _detail(Styles d, Style s) {
    final editing = c.editing;
    return Panel(
      title: editing ? 'Personalizando: ${s.name}' : s.name,
      subtitle: Text(c.detailNote ?? (editing ? 'As prévias atualizam enquanto você mexe.' : s.description ?? '')),
      trailing: editing
          ? null
          : Wrap(
              spacing: 8,
              children: [
                SmallButton('Exportar', onPressed: c.export),
                if (!c.builtin(s))
                  DangerButton(
                    c.deleteArmed ? 'Confirmar exclusão' : 'Excluir',
                    confirm: c.deleteArmed,
                    onPressed: c.delete,
                  ),
                SmallButton(
                  'Personalizar',
                  onPressed: () {
                    c.startEditing();
                    _draftName.text = c.draftName;
                    _html.text = (getTok(c.draft!, 'thumbnail.html') as String?) ?? '';
                  },
                ),
                if (s.id != d.active) SmallButton('Usar este estilo', primary: true, onPressed: c.use),
              ],
            ),
      children: [
        _previews(),
        if (editing) ...[const SizedBox(height: 20), _editor(d, s)],
      ],
    );
  }

  Widget _previews() => LayoutBuilder(
    builder: (context, box) {
      final w = (box.maxWidth - 3 * 12 - 90) / 3;
      Widget shot(String kind, double width, double ratio) {
        final png = c.previews[kind];
        return SizedBox(
          width: width,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Tooltip(
                message: 'Clique pra ver grande',
                child: InkWell(
                  onTap: png == null ? null : () => _zoom(png),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: AspectRatio(
                      aspectRatio: ratio,
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          const ColoredBox(color: Tokens.panel2),
                          if (png != null) Image.memory(png, fit: BoxFit.cover, gaplessPlayback: true),
                          if (c.previewing)
                            const Positioned(
                              right: 8,
                              top: 8,
                              child: SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(_previewLabels[kind]!, style: const TextStyle(fontSize: 12, color: Tokens.dim)),
              ),
            ],
          ),
        );
      }

      return Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          shot('thumbnail', w, 16 / 9),
          shot('lower_third', w, 16 / 9),
          shot('cta', w, 16 / 9),
          shot('caption', 90, 9 / 16),
        ],
      );
    },
  );

  Widget _editor(Styles d, Style s) {
    final t = c.draft!;
    final fonts = [for (final f in d.fonts) DropdownMenuItem(value: f.id, child: Text(f.label))];
    String pct(Object? v) => '${((v as num? ?? 0) * 100).round()}%';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Material(
          color: Tokens.panel2,
          shape: RoundedRectangleBorder(
            side: const BorderSide(color: Tokens.borderSoft),
            borderRadius: BorderRadius.circular(10),
          ),
          clipBehavior: Clip.antiAlias,
          child: ExpansionTile(
            title: const Text('Avançado: editar o HTML da thumbnail', style: TextStyle(fontSize: 13.5)),
            childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
            children: [
              TextField(
                controller: _html,
                minLines: 6,
                maxLines: 16,
                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5),
                onChanged: c.setHtml,
                decoration: fieldDecoration(hint: 'sem layout próprio: a thumbnail usa o layout padrão'),
              ),
              if (_html.text.trim().isNotEmpty)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: () {
                      _html.clear();
                      c.setHtml('');
                    },
                    child: const Text('voltar pro layout padrão'),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 18,
          runSpacing: 18,
          children: [
            _group('Cores', [
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final (k, label) in [('accent', 'Destaque'), ('panel', 'Painel'), ('text', 'Texto')])
                    ColorButton(
                      color: parseHex(getTok(t, 'colors.$k')),
                      label: label,
                      onChanged: (hex) => c.set('colors.$k', hex),
                    ),
                ],
              ),
              if (d.brand.logo != null)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(onPressed: c.useLogoColors, child: const Text('usar cores do logo')),
                ),
              _slider('Opacidade do painel', t, 'panel_opacity', .3, 1, 14, pct),
              _select('Cor da thumbnail', t, 'thumbnail.accent_from', const {
                'topic': 'muda conforme o assunto do vídeo',
                'style': 'sempre a cor de destaque',
              }),
            ]),
            _group('Forma', [
              _dropdown('Fonte do título (thumbnail)', t, 'fonts.title', fonts),
              _dropdown('Fonte dos overlays', t, 'fonts.text', fonts),
              _slider('Cantos', t, 'radius', 0, 60, 60, (v) => '${(v as num?)?.round() ?? 0}px'),
              _slider('Velocidade da animação', t, 'speed', .5, 2, 30, pct),
            ]),
            _group('Nome na tela', [
              _select('Posição', t, 'lower_third.position', const {
                'bottom-left': 'embaixo, à esquerda',
                'bottom-right': 'embaixo, à direita',
                'top-left': 'em cima, à esquerda',
              }),
              _check('Mostrar logo / inicial', t, 'lower_third.avatar'),
            ]),
            _group('Chamada pra se inscrever', [
              _select('Posição', t, 'cta.position', const {
                'bottom-center': 'embaixo, no centro',
                'bottom-right': 'embaixo, à direita',
                'top-right': 'em cima, à direita',
              }),
              for (final (i, st) in c.steps.indexed) _step(d, i, st, accent: parseHex(getTok(t, 'colors.accent'))),
              if (c.steps.length < 3)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(onPressed: c.addStep, child: const Text('+ adicionar passo')),
                ),
            ]),
            _group('Legenda', [
              _select('Posição', t, 'captions.position', const {'top': 'topo', 'middle': 'meio', 'bottom': 'embaixo'}),
              _slider(
                'Altura da margem',
                t,
                'captions.offset',
                0,
                40,
                40,
                (v) => '${(v as num?)?.round() ?? 0}%',
                enabled: getTok(t, 'captions.position') != 'middle',
              ),
              _slider('Tamanho', t, 'captions.size', 50, 200, 30, (v) => '${(v as num?)?.round() ?? 0}%'),
              _dropdown('Fonte', t, 'captions.font', fonts),
              Wrap(
                spacing: 8,
                children: [
                  ColorButton(
                    color: parseHex(getTok(t, 'captions.color')),
                    label: 'Texto',
                    onChanged: (hex) => c.set('captions.color', hex),
                  ),
                  ColorButton(
                    color: parseHex(getTok(t, 'captions.highlight')),
                    label: 'Destaque',
                    onChanged: (hex) => c.set('captions.highlight', hex),
                  ),
                ],
              ),
              _select('Destaque da palavra', t, 'captions.highlight_mode', const {
                'outline': 'contorno colorido',
                'fill': 'letra colorida',
                'box': 'caixa atrás da palavra',
              }),
              _slider('Contorno', t, 'captions.outline', 0, 6, 12, (v) => '${v ?? 0}'),
              _select('Fundo', t, 'captions.background', const {'none': 'nenhum', 'box': 'caixa'}),
              _numSelect('Palavras por vez', t, 'captions.words', const [1, 2, 3, 4]),
              _check('TUDO EM MAIÚSCULAS', t, 'captions.uppercase'),
            ]),
          ],
        ),
        const SizedBox(height: 18),
        Row(
          children: [
            SizedBox(
              width: 260,
              child: TextField(
                controller: _draftName,
                maxLength: 40,
                onChanged: (v) => c.draftName = v,
                decoration: fieldDecoration(hint: 'nome do estilo').copyWith(counterText: ''),
              ),
            ),
            const Spacer(),
            SmallButton(c.discardArmed ? 'Clique de novo pra descartar' : 'Descartar', onPressed: c.cancelEditing),
            if (!c.builtin(s)) ...[
              const SizedBox(width: 8),
              SmallButton('Salvar como novo', onPressed: () => c.save(asNew: true)),
            ],
            const SizedBox(width: 8),
            SmallButton('Salvar e usar', primary: true, onPressed: c.save),
          ],
        ),
      ],
    );
  }

  Widget _group(String title, List<Widget> children) => SizedBox(
    width: 330,
    // a Material (not a decorated box): the checkbox tiles inside show their ink
    child: Material(
      color: Tokens.panel2,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: Tokens.borderSoft),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            for (final w in children) Padding(padding: const EdgeInsets.only(bottom: 10), child: w),
          ],
        ),
      ),
    ),
  );

  Widget _label(String text, [String? value]) => Padding(
    padding: const EdgeInsets.only(bottom: 4),
    child: Text.rich(
      TextSpan(
        children: [
          TextSpan(text: text),
          if (value != null)
            TextSpan(
              text: '  $value',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
        ],
      ),
      style: const TextStyle(fontSize: 12.5, color: Tokens.dim),
    ),
  );

  Widget _slider(
    String label,
    Map<String, Object?> t,
    String path,
    double min,
    double max,
    int divisions,
    String Function(Object?) fmt, {
    bool enabled = true,
  }) {
    final v = ((getTok(t, path) as num?)?.toDouble() ?? min).clamp(min, max);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _label(label, fmt(getTok(t, path))),
        Slider(
          value: v,
          min: min,
          max: max,
          divisions: divisions,
          onChanged: enabled
              ? (x) {
                  // ints stay ints (radius, offset, size)
                  final step = (max - min) / divisions;
                  c.set(path, step >= 1 ? x.round() : double.parse(x.toStringAsFixed(2)));
                }
              : null,
        ),
      ],
    );
  }

  Widget _select(String label, Map<String, Object?> t, String path, Map<String, String> options) {
    final v = getTok(t, path);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _label(label),
        DropdownButtonFormField<String>(
          key: ValueKey('$path=$v'),
          isExpanded: true,
          initialValue: options.containsKey(v) ? v as String : null,
          decoration: fieldDecoration(),
          items: [for (final e in options.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
          onChanged: (x) => c.set(path, x),
        ),
      ],
    );
  }

  Widget _numSelect(String label, Map<String, Object?> t, String path, List<int> options) {
    final v = (getTok(t, path) as num?)?.toInt();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _label(label),
        DropdownButtonFormField<int>(
          key: ValueKey('$path=$v'),
          isExpanded: true,
          initialValue: options.contains(v) ? v : null,
          decoration: fieldDecoration(),
          items: [for (final o in options) DropdownMenuItem(value: o, child: Text('$o'))],
          onChanged: (x) => c.set(path, x),
        ),
      ],
    );
  }

  Widget _dropdown(String label, Map<String, Object?> t, String path, List<DropdownMenuItem<String>> items) {
    final v = getTok(t, path);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _label(label),
        DropdownButtonFormField<String>(
          key: ValueKey('$path=$v'),
          isExpanded: true,
          initialValue: items.any((i) => i.value == v) ? v as String : null,
          decoration: fieldDecoration(),
          items: items,
          onChanged: (x) => c.set(path, x),
        ),
      ],
    );
  }

  Widget _check(String label, Map<String, Object?> t, String path) => CheckboxListTile(
    contentPadding: EdgeInsets.zero,
    controlAffinity: ListTileControlAffinity.leading,
    dense: true,
    value: getTok(t, path) == true,
    onChanged: (v) => c.set(path, v ?? false),
    title: Text(label, style: const TextStyle(fontSize: 13.5)),
  );

  Widget _step(Styles d, int i, Map<String, Object?> st, {Color? accent}) {
    final own = parseHex(st['color']);
    return Row(
      children: [
        SizedBox(
          width: 110,
          child: DropdownButtonFormField<String>(
            key: ValueKey('step$i=${st['icon']}'),
            isExpanded: true,
            initialValue: d.icons.contains(st['icon']) ? st['icon'] as String : null,
            decoration: fieldDecoration(),
            items: [for (final ic in d.icons) DropdownMenuItem(value: ic, child: Text(_iconLabels[ic] ?? ic))],
            onChanged: (x) => c.setStep(i, 'icon', x),
          ),
        ),
        const SizedBox(width: 6),
        Expanded(
          child: _StepText(text: (st['text'] as String?) ?? '', onChanged: (v) => c.setStep(i, 'text', v)),
        ),
        const SizedBox(width: 4),
        ColorButton(
          color: own ?? accent,
          compact: true,
          tooltip: own == null
              ? 'Cor própria (sem: a de destaque)'
              : 'Cor própria — clique com o direito pra voltar à de destaque',
          onChanged: (hex) => c.setStep(i, 'color', hex),
          onClear: own == null ? null : () => c.setStep(i, 'color', null),
        ),
        if (c.steps.length > 1)
          IconButton(
            tooltip: 'Remover passo',
            visualDensity: VisualDensity.compact,
            onPressed: () => c.removeStep(i),
            icon: const Icon(Icons.close, size: 16),
          ),
      ],
    );
  }

  Widget _overlaysPanel() => Panel(
    title: 'Overlays em MP4 (opcional)',
    subtitle: const Text(
      'Se você tiver vídeos próprios de lower third e CTA com fundo verde (lowerthid_gabul.mp4 e ctas.mp4), '
      'eles substituem os overlays do estilo.',
    ),
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              _overlays.text.isEmpty ? 'padrão: assets/overlays/' : _overlays.text,
              style: TextStyle(
                fontFamily: Tokens.mono,
                fontSize: 13,
                color: _overlays.text.isEmpty ? Tokens.faint : Tokens.text,
              ),
            ),
          ),
          SmallButton('Escolher pasta', onPressed: _pickOverlays),
          if (_overlays.text.isNotEmpty) ...[
            const SizedBox(width: 8),
            SmallButton(
              'Usar a padrão',
              onPressed: () {
                setState(_overlays.clear);
                unawaited(c.saveOverlaysDir(null));
              },
            ),
          ],
        ],
      ),
    ],
  );
}

class _StepText extends StatefulWidget {
  const _StepText({required this.text, required this.onChanged});
  final String text;
  final ValueChanged<String> onChanged;

  @override
  State<_StepText> createState() => _StepTextState();
}

class _StepTextState extends State<_StepText> {
  late final _c = TextEditingController(text: widget.text);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
    controller: _c,
    maxLength: 24,
    onChanged: widget.onChanged,
    decoration: fieldDecoration().copyWith(counterText: ''),
  );
}

/// A color swatch that opens a small picker (presets + #hex).
class ColorButton extends StatelessWidget {
  const ColorButton({
    super.key,
    required this.color,
    required this.onChanged,
    this.label,
    this.selected = false,
    this.compact = false,
    this.tooltip,
    this.onClear,
  });

  final Color? color;
  final ValueChanged<String> onChanged;
  final String? label;
  final bool selected;
  final bool compact;
  final String? tooltip;

  /// Right-click: back to no color of its own.
  final VoidCallback? onClear;

  Future<void> _pick(BuildContext context) async {
    final hex = await showDialog<String>(
      context: context,
      builder: (context) => _ColorDialog(initial: color),
    );
    if (hex != null) onChanged(hex);
  }

  @override
  Widget build(BuildContext context) {
    final swatch = Container(
      width: compact ? 22 : 18,
      height: compact ? 22 : 18,
      decoration: BoxDecoration(
        color: color ?? Colors.transparent,
        shape: BoxShape.circle,
        border: Border.all(color: Tokens.border),
      ),
    );
    final Widget button = compact
        ? GestureDetector(
            onSecondaryTap: onClear,
            child: IconButton(onPressed: () => _pick(context), icon: swatch, visualDensity: VisualDensity.compact),
          )
        : ChoiceChip(avatar: swatch, label: Text(label ?? ''), selected: selected, onSelected: (_) => _pick(context));
    return tooltip == null ? button : Tooltip(message: tooltip, child: button);
  }
}

class _ColorDialog extends StatefulWidget {
  const _ColorDialog({this.initial});
  final Color? initial;

  @override
  State<_ColorDialog> createState() => _ColorDialogState();
}

String hexOf(Color c) => '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';

class _ColorDialogState extends State<_ColorDialog> {
  static const _presets = [
    0xFF2EE6C6, 0xFF1AA6D6, 0xFF5B9DFF, 0xFF8B5CF6, 0xFFC084FC, 0xFFF472B6, //
    0xFFF87171, 0xFFF5B544, 0xFFFACC15, 0xFF4ADE80, 0xFF22C55E, 0xFFFFFFFF,
    0xFFE7EBF2, 0xFF9AA4B2, 0xFF151A22, 0xFF0D1015, 0xFF000000, 0xFFFF0000,
  ];
  late final _hex = TextEditingController(text: widget.initial == null ? '' : hexOf(widget.initial!));

  @override
  void dispose() {
    _hex.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final typed = parseHex(_hex.text);
    return AlertDialog(
      title: const Text('Cor'),
      content: SizedBox(
        width: 300,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final p in _presets)
                  InkWell(
                    customBorder: const CircleBorder(),
                    onTap: () => Navigator.of(context).pop(hexOf(Color(p))),
                    child: Container(
                      width: 32,
                      height: 32,
                      decoration: BoxDecoration(
                        color: Color(p),
                        shape: BoxShape.circle,
                        border: Border.all(color: Tokens.border),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: typed ?? Colors.transparent,
                    shape: BoxShape.circle,
                    border: Border.all(color: Tokens.border),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: _hex,
                    autofocus: true,
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(RegExp('[#0-9a-fA-F]')),
                      LengthLimitingTextInputFormatter(7),
                    ],
                    style: const TextStyle(fontFamily: Tokens.mono),
                    onChanged: (_) => setState(() {}),
                    onSubmitted: (_) {
                      if (typed != null) Navigator.of(context).pop(hexOf(typed));
                    },
                    decoration: fieldDecoration(hint: '#RRGGBB'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancelar')),
        FilledButton(
          onPressed: typed == null ? null : () => Navigator.of(context).pop(hexOf(typed)),
          child: const Text('Usar'),
        ),
      ],
    );
  }
}

import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../../platform.dart';
import '../shell.dart';
import '../theme.dart';
import '../widgets.dart';
import 'settings_controller.dart';

const _modelHint = {
  'claude': 'padrão da CLI (ex.: claude-opus-5-5)',
  'cursor': 'auto',
  'agy': 'padrão da CLI',
  'opencode': 'ex.: opencode/big-pickle',
  'codex': 'padrão da CLI (ex.: gpt-5-codex)',
  'openrouter': 'openrouter/auto, ou ex.: openai/gpt-5',
};

// A 7B local model took ~5 min on a 10-min long's plan alone (an edit calls
// the agent 6+ times) and filled it with the prompt's example.
const ollamaSlow =
    'modelo local é lento (minutos por etapa) e modelos pequenos (7B) erram em vídeo longo — '
    'prefira um de 14B+ ou use o Ollama como fallback';

/// Configurações — which AI agent edits (and with which model), the accounts,
/// the folders and the defaults of a new edit. Saved by the engine in
/// ~/.auto-edit/settings.json; environment variables still win over it.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.client, required this.pickers, this.debounce});

  final AutoEditClient client;
  final Pickers pickers;
  final Duration? debounce;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final SettingsController c;

  @override
  void initState() {
    super.initState();
    c = SettingsController(widget.client, debounce: widget.debounce ?? const Duration(milliseconds: 600));
    unawaited(c.load());
  }

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) => FormScreen(
        top: TopBar(
          title: 'Configurações',
          subtitle: 'Agente de IA, contas e padrões das edições',
          actions: [_SaveStatus(c.saveState)],
        ),
        children: [
          if (c.error != null) Notice(c.error!),
          _FoldersCard(c: c, pickers: widget.pickers),
          _YoutubeCard(c: c, pickers: widget.pickers),
          _AgentsCard(c: c),
          if (c.agentNamed('ollama') != null) _OllamaCard(c: c),
          if (c.loaded) _DefaultsCard(c: c),
        ],
      ),
    );
  }
}

class _SaveStatus extends StatelessWidget {
  const _SaveStatus(this.state);
  final SaveState state;

  @override
  Widget build(BuildContext context) {
    final (text, color) = switch (state) {
      SaveState.idle => ('Salvo automaticamente', Tokens.faint),
      SaveState.saving => ('Salvando…', Tokens.dim),
      SaveState.saved => ('Salvo', Tokens.ok),
      SaveState.failed => ('Não salvo', Tokens.err),
    };
    return Text(text, style: TextStyle(fontSize: 12.5, color: color));
  }
}

// ── Pastas ──────────────────────────────────────────────────────────────────

class _FoldersCard extends StatelessWidget {
  const _FoldersCard({required this.c, required this.pickers});
  final SettingsController c;
  final Pickers pickers;

  @override
  Widget build(BuildContext context) {
    final f = c.folders;
    return Panel(
      title: 'Pastas',
      subtitle: const Text('O seletor de vídeos abre na pasta de entrada; os vídeos prontos vão pra pasta de saída.'),
      children: [
        _FolderRow(c: c, pickers: pickers, which: 'inbox', label: 'Pasta de entrada (gravações)', folder: f?.inbox),
        const SizedBox(height: 14),
        _FolderRow(
          c: c,
          pickers: pickers,
          which: 'output',
          label: 'Pasta de saída (vídeos prontos)',
          folder: f?.output,
        ),
      ],
    );
  }
}

class _FolderRow extends StatelessWidget {
  const _FolderRow({
    required this.c,
    required this.pickers,
    required this.which,
    required this.label,
    required this.folder,
  });

  final SettingsController c;
  final Pickers pickers;
  final String which;
  final String label;
  final Folder? folder;

  @override
  Widget build(BuildContext context) {
    final f = folder;
    final missing = f != null && !f.exists;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(label, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
            if (f != null && !f.custom)
              const Text(
                'padrão',
                style: TextStyle(fontSize: 12, color: Tokens.faint, fontStyle: FontStyle.italic),
              ),
            if (f != null && f.custom)
              InkWell(
                onTap: () => c.saveFolder(which, null),
                child: const Text('usar a padrão', style: TextStyle(fontSize: 12, color: Tokens.accent)),
              ),
          ],
        ),
        const SizedBox(height: 6),
        Row(
          children: [
            Expanded(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: Tokens.panel2,
                  border: Border.all(color: missing ? Tokens.err : Tokens.border),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Tooltip(
                  message: f?.path ?? '',
                  child: Text(
                    f?.path ?? '…',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontFamily: Tokens.mono,
                      fontSize: 12.5,
                      color: missing ? Tokens.err : Tokens.text,
                      decoration: missing ? TextDecoration.lineThrough : null,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.outlined(
              tooltip: 'Abrir a pasta',
              onPressed: () => c.openFolder(which),
              icon: const Icon(Icons.folder_open_outlined, size: 18),
            ),
            const SizedBox(width: 6),
            OutlinedButton(
              onPressed: () async {
                final path = await pickers.folder(initial: f?.path);
                if (path != null) await c.saveFolder(which, path);
              },
              child: const Text('Trocar'),
            ),
          ],
        ),
        // A chosen inbox can be deleted later: say so, Trocar fixes it.
        if (missing)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Meta('Essa pasta não existe mais. Clique em Trocar ou em “usar a padrão”.', bad: true),
          ),
      ],
    );
  }
}

// ── YouTube ─────────────────────────────────────────────────────────────────

class _YoutubeCard extends StatefulWidget {
  const _YoutubeCard({required this.c, required this.pickers});
  final SettingsController c;
  final Pickers pickers;

  @override
  State<_YoutubeCard> createState() => _YoutubeCardState();
}

class _YoutubeCardState extends State<_YoutubeCard> {
  final _guide = ExpansibleController();
  bool? _ready;

  SettingsController get c => widget.c;

  Future<void> _pickJson() async {
    final content = await widget.pickers.jsonFile(title: 'Escolher o JSON da credencial do Google');
    if (content != null) await c.setYoutubeClient(content);
  }

  @override
  Widget build(BuildContext context) {
    final a = c.youtube;
    final ready = a?.hasClientSecret ?? false;
    // Open while there's no credential; once that changes, follow it (in
    // between it stays as the person left it).
    if (a != null && _ready != ready) {
      _ready = ready;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        ready ? _guide.collapse() : _guide.expand();
      });
    }
    final (Color dot, String status) = a == null
        ? (Tokens.faint, '—')
        : a.connecting
        ? (Tokens.run, 'Aguardando você autorizar no navegador… Fechou a página? Cancele e conecte de novo.')
        : a.connected
        ? (Tokens.ok, 'Conectado como ${a.channel ?? '?'}')
        : (a.needsReconnect ?? false)
        ? (Tokens.run, 'Precisa reconectar pra liberar as permissões novas')
        : a.hasClientSecret
        ? (Tokens.faint, 'Não conectado')
        : (Tokens.faint, 'Não configurado: falta a credencial do Google (passo a passo abaixo)');
    final connected = a?.connected ?? false;
    final connecting = a?.connecting ?? false;
    final label = connecting
        ? 'Esperando autorização…'
        : connected
        ? 'Desconectar'
        : (a?.needsReconnect ?? false)
        ? 'Reconectar YouTube'
        : 'Conectar YouTube';
    final canPress = a != null && !connecting && (ready || connected);
    final button = ready && !connected && !connecting
        ? FilledButton(onPressed: canPress ? c.connectOrDisconnect : null, child: Text(label))
        : OutlinedButton(onPressed: canPress ? c.connectOrDisconnect : null, child: Text(label));

    void docs(String url) => unawaited(c.openUrl(url));
    return Panel(
      title: 'YouTube',
      subtitle: const Text('Publicar, legenda, comentário e retenção usam uma conexão só.'),
      children: [
        Row(
          children: [
            Container(
              width: 9,
              height: 9,
              decoration: BoxDecoration(color: dot, shape: BoxShape.circle),
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(status, style: const TextStyle(fontSize: 13.5))),
            if (connecting) ...[
              OutlinedButton(onPressed: c.cancelConnect, child: const Text('Cancelar')),
              const SizedBox(width: 8),
            ],
            Tooltip(
              message: ready || connected ? '' : 'Primeiro escolha o JSON da credencial (passo 5)',
              child: button,
            ),
          ],
        ),
        if (c.youtubeError != null) Padding(padding: const EdgeInsets.only(top: 12), child: Notice(c.youtubeError!)),
        if (ready)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text.rich(
              TextSpan(
                style: const TextStyle(fontSize: 12.5, color: Tokens.dim),
                children: [
                  const TextSpan(text: 'Credencial do Google: '),
                  TextSpan(
                    text: a?.clientId ?? 'configurada',
                    style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12),
                  ),
                  const TextSpan(text: ' · '),
                  link('trocar arquivo', _pickJson),
                ],
              ),
            ),
          ),
        const SizedBox(height: 8),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            controller: _guide,
            tilePadding: EdgeInsets.zero,
            childrenPadding: const EdgeInsets.only(bottom: 4),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            title: const Text.rich(
              TextSpan(
                text: 'Como conectar ',
                style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
                children: [
                  TextSpan(
                    text: '(uma vez só, uns 5 minutos)',
                    style: TextStyle(color: Tokens.faint, fontWeight: FontWeight.w400),
                  ),
                ],
              ),
            ),
            children: [
              const Text(
                'O YouTube só aceita vídeos enviados por um app registrado no Google Cloud. Você cria o seu '
                '(é grátis), baixa um arquivo de credencial e escolhe ele aqui.',
                style: TextStyle(fontSize: 13, color: Tokens.dim, height: 1.5),
              ),
              const SizedBox(height: 10),
              _Step(1, [
                const TextSpan(text: 'Crie um projeto', style: _bold),
                const TextSpan(text: ' no Google Cloud, com a conta Google do seu canal. '),
                link('Abrir o Google Cloud', () => docs('https://console.cloud.google.com/projectcreate')),
              ]),
              _Step(2, [
                const TextSpan(text: 'Ative as duas APIs do YouTube', style: _bold),
                const TextSpan(
                  text: ': a Data API v3 (envio) e a Analytics API (retenção). Em cada uma, clique em Ativar. ',
                ),
                link(
                  'YouTube Data API v3',
                  () => docs('https://console.cloud.google.com/apis/library/youtube.googleapis.com'),
                ),
                const TextSpan(text: ' · '),
                link(
                  'YouTube Analytics API',
                  () => docs('https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com'),
                ),
              ]),
              _Step(3, [
                const TextSpan(text: 'Configure o acesso', style: _bold),
                const TextSpan(
                  text: ': no Google Auth Platform, clique em Primeiros passos, dê um nome ao app e escolha ',
                ),
                const TextSpan(text: 'Externo', style: _bold),
                const TextSpan(text: '. Depois, em Público-alvo, adicione o seu e-mail como '),
                const TextSpan(text: 'usuário de teste', style: _bold),
                const TextSpan(text: '. '),
                link('Abrir o Google Auth Platform', () => docs('https://console.cloud.google.com/auth/overview')),
              ]),
              _Step(4, [
                const TextSpan(text: 'Crie a credencial', style: _bold),
                const TextSpan(text: ': em Clientes → Criar cliente, escolha o tipo '),
                const TextSpan(text: 'App para computador', style: _bold),
                const TextSpan(text: ' e baixe o JSON. '),
                link('Criar cliente', () => docs('https://console.cloud.google.com/auth/clients/create')),
              ]),
              _Step(5, [
                const TextSpan(text: 'Escolha o JSON aqui', style: _bold),
                const TextSpan(text: '. '),
              ], trailing: SmallButton('Escolher arquivo JSON', onPressed: _pickJson)),
              const _Step(6, [
                TextSpan(text: 'Conecte', style: _bold),
                TextSpan(
                  text:
                      ': clique em Conectar YouTube. O navegador abre pra você escolher o canal e autorizar. Se o '
                      'Google avisar que o app não foi verificado, é o seu próprio app: clique em Avançado e continue.',
                ),
              ]),
              const SizedBox(height: 6),
              const Text.rich(
                TextSpan(
                  style: TextStyle(fontSize: 12.5, color: Tokens.faint, height: 1.5),
                  children: [
                    TextSpan(text: 'Em modo de teste, o Google desconecta a cada 7 dias. Pra não expirar, clique em '),
                    TextSpan(text: 'Publicar app', style: _bold),
                    TextSpan(
                      text:
                          ' em Público-alvo (pra uso próprio não precisa de verificação). E enquanto o projeto não '
                          'passa pela auditoria do YouTube, os vídeos enviados ficam privados: é só liberar no Studio.',
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

const _dropdownText = TextStyle(fontFamily: Tokens.font, fontSize: 13.5, color: Tokens.text);

const _bold = TextStyle(fontWeight: FontWeight.w600, color: Tokens.text);

class _Step extends StatelessWidget {
  const _Step(this.n, this.spans, {this.trailing});
  final int n;
  final List<InlineSpan> spans;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 9),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 22,
          child: Text(
            '$n.',
            style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5, color: Tokens.faint),
          ),
        ),
        Expanded(
          child: Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text.rich(
                TextSpan(
                  style: const TextStyle(fontSize: 13, color: Tokens.dim, height: 1.5),
                  children: spans,
                ),
              ),
              ?trailing,
            ],
          ),
        ),
      ],
    ),
  );
}

// ── Agente de IA ────────────────────────────────────────────────────────────

class _AgentsCard extends StatelessWidget {
  const _AgentsCard({required this.c});
  final SettingsController c;

  @override
  Widget build(BuildContext context) {
    final installed = c.agents.where((a) => a.installed && a.name != c.primary).toList();
    return Panel(
      title: 'Agente de IA',
      subtitle: const Text.rich(
        TextSpan(
          children: [
            TextSpan(text: 'Quem planeja, revisa e avalia os cortes. O '),
            TextSpan(text: 'principal', style: _bold),
            TextSpan(text: ' roda sempre; o '),
            TextSpan(text: 'fallback', style: _bold),
            TextSpan(text: ' entra se ele falhar.'),
          ],
        ),
      ),
      children: [
        if (c.agentsLoading && c.agents.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: Row(
              children: [
                SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Verificando os agentes de IA instalados no seu computador… leva alguns segundos.',
                    style: TextStyle(fontSize: 13, color: Tokens.dim),
                  ),
                ),
              ],
            ),
          )
        else if (c.agents.isEmpty)
          const Meta('Não deu pra verificar os agentes de IA.', bad: true),
        RadioGroup<String>(
          groupValue: c.primary,
          onChanged: (v) {
            if (v != null) c.setPrimary(v);
          },
          child: Column(
            children: [for (final a in c.agents) _AgentRow(c: c, a: a)],
          ),
        ),
        const SizedBox(height: 12),
        const Text('Fallback', style: TextStyle(fontSize: 13, color: Tokens.dim)),
        const SizedBox(height: 6),
        DropdownButtonFormField<String?>(
          key: ValueKey('fallback-${c.primary}-${c.fallback}-${installed.length}'),
          initialValue: installed.any((a) => a.name == c.fallback) ? c.fallback : null,
          decoration: fieldDecoration(),
          dropdownColor: Tokens.panel,
          style: _dropdownText,
          items: [
            const DropdownMenuItem<String?>(value: null, child: Text('sem fallback')),
            for (final a in installed) DropdownMenuItem<String?>(value: a.name, child: Text(a.label)),
          ],
          onChanged: c.agents.isEmpty ? null : c.setFallback,
        ),
      ],
    );
  }
}

class _AgentRow extends StatelessWidget {
  const _AgentRow({required this.c, required this.a});
  final SettingsController c;
  final AgentStatus a;

  @override
  Widget build(BuildContext context) {
    final isPrimary = a.name == c.primary;
    final busy = c.testing.contains(a.name);
    final note = c.notes[a.name];
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(6, 10, 12, 10),
      decoration: BoxDecoration(
        color: isPrimary ? Tokens.accent.withValues(alpha: .05) : Tokens.panel2,
        border: Border.all(color: isPrimary ? Tokens.accent.withValues(alpha: .4) : Tokens.borderSoft),
        borderRadius: BorderRadius.circular(11),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Tooltip(
                message: 'usar como principal',
                child: Radio<String>(value: a.name, enabled: a.installed),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Flexible(
                          child: Text(a.label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                        ),
                        if (isPrimary) const Badge2('principal'),
                        if (a.name == c.fallback) const Badge2('fallback', color: Tokens.info),
                      ],
                    ),
                    const SizedBox(height: 3),
                    ..._meta(),
                    if (a.installed) ...[const SizedBox(height: 8), _ModelField(c: c, a: a)],
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Wrap(
                  spacing: 6,
                  children: [
                    if (a.installed)
                      SmallButton(busy ? 'testando…' : 'Testar', onPressed: busy ? null : () => c.test(a.name)),
                    if (a.installed && a.loginCommand != null)
                      SmallButton('Fazer login', onPressed: () => c.login(a.name)),
                  ],
                ),
              ),
            ],
          ),
          if (busy)
            const _Result('testando… (um prompt mínimo de verdade, pode levar até 1 min)')
          else if (note != null)
            _Result(
              note.answer == null ? note.text : '${note.text}\nresposta: ${note.answer}',
              ok: note.ok,
              bad: !note.ok && note.text.startsWith('✗'),
            ),
        ],
      ),
    );
  }

  List<Widget> _meta() {
    if (a.apiKey ?? false) {
      if (!a.installed) {
        return [
          const Meta('sem chave da API', bad: true),
          const SizedBox(height: 8),
          _KeyForm(onSave: c.saveOpenrouterKey),
          const SizedBox(height: 4),
          Text.rich(
            TextSpan(
              style: const TextStyle(fontSize: 12, color: Tokens.faint),
              children: [
                const TextSpan(text: 'crie uma em '),
                link('openrouter.ai/settings/keys', () => c.openUrl(a.docs ?? 'https://openrouter.ai/settings/keys')),
                const TextSpan(text: ' — fica só no seu computador.'),
              ],
            ),
          ),
        ];
      }
      if (a.keySource == 'env') return [Meta('chave ${a.keyHint ?? ''} (da variável OPENROUTER_API_KEY)')];
      return [
        Text.rich(
          TextSpan(
            style: const TextStyle(fontSize: 12, color: Tokens.faint),
            children: [
              TextSpan(text: 'chave ${a.keyHint ?? ''} · '),
              link('remover', c.removeOpenrouterKey),
            ],
          ),
        ),
      ];
    }
    if (!a.installed) {
      return [
        Text.rich(
          TextSpan(
            style: const TextStyle(fontSize: 12, color: Color(0xFFE59A9A)),
            children: [
              const TextSpan(text: 'não instalado · '),
              if (a.docs != null) link('como instalar', () => c.openUrl(a.docs!)),
            ],
          ),
        ),
      ];
    }
    if (a.name == 'ollama') {
      if (!(a.server ?? false)) {
        return [const Meta('instalado, mas o servidor não está rodando (abra o app do Ollama)', bad: true)];
      }
      return [Meta('${a.version ?? ''} · ${a.models?.length ?? 0} modelo(s)'), const Meta(ollamaSlow)];
    }
    return [Meta(a.version ?? 'instalado')];
  }
}

class _Result extends StatelessWidget {
  const _Result(this.text, {this.ok = false, this.bad = false});
  final String text;
  final bool ok;
  final bool bad;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(48, 8, 0, 0),
    child: SelectableText(
      text,
      style: TextStyle(
        fontFamily: Tokens.mono,
        fontSize: 12,
        height: 1.5,
        color: ok
            ? Tokens.ok
            : bad
            ? const Color(0xFFE59A9A)
            : Tokens.dim,
      ),
    ),
  );
}

/// The model of one agent: typed (saved a moment after the last key) or, for
/// Ollama, picked from what is downloaded.
class _ModelField extends StatefulWidget {
  const _ModelField({required this.c, required this.a});
  final SettingsController c;
  final AgentStatus a;

  @override
  State<_ModelField> createState() => _ModelFieldState();
}

class _ModelFieldState extends State<_ModelField> {
  late final TextEditingController _text = TextEditingController(text: widget.c.models[widget.a.name] ?? '');
  final _focus = FocusNode();

  @override
  void dispose() {
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final name = widget.a.name;
    final value = widget.c.models[name];
    if (name == 'ollama') {
      final models = widget.a.models ?? const <String>[];
      return SizedBox(
        width: 320,
        child: DropdownButtonFormField<String?>(
          key: ValueKey('ollama-model-$value-${models.length}'),
          initialValue: models.contains(value) ? value : null,
          decoration: fieldDecoration(),
          dropdownColor: Tokens.panel,
          style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5, color: Tokens.text),
          items: [
            const DropdownMenuItem<String?>(value: null, child: Text('primeiro instalado')),
            for (final m in models) DropdownMenuItem<String?>(value: m, child: Text(m)),
          ],
          onChanged: (v) => widget.c.setModel(name, v ?? ''),
        ),
      );
    }
    // Saving brings the value back: don't fight the person typing.
    if (!_focus.hasFocus && (_text.text.trim().isEmpty ? null : _text.text.trim()) != value) {
      _text.text = value ?? '';
    }
    return SizedBox(
      width: 320,
      child: TextField(
        controller: _text,
        focusNode: _focus,
        style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5),
        decoration: fieldDecoration(hint: 'modelo: ${_modelHint[name] ?? 'padrão'}'),
        onChanged: (t) => widget.c.setModel(name, t),
      ),
    );
  }
}

/// OpenRouter: no CLI, an API key pasted here (it never comes back whole).
class _KeyForm extends StatefulWidget {
  const _KeyForm({required this.onSave});
  final Future<void> Function(String key) onSave;

  @override
  State<_KeyForm> createState() => _KeyFormState();
}

class _KeyFormState extends State<_KeyForm> {
  final _key = TextEditingController();

  @override
  void dispose() {
    _key.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Expanded(
        child: TextField(
          controller: _key,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5),
          decoration: fieldDecoration(hint: 'cole a chave: sk-or-…'),
        ),
      ),
      const SizedBox(width: 8),
      SmallButton('Salvar chave', primary: true, onPressed: () => widget.onSave(_key.text)),
    ],
  );
}

// ── Ollama ──────────────────────────────────────────────────────────────────

class _OllamaCard extends StatefulWidget {
  const _OllamaCard({required this.c});
  final SettingsController c;

  @override
  State<_OllamaCard> createState() => _OllamaCardState();
}

class _OllamaCardState extends State<_OllamaCard> {
  final _model = TextEditingController();

  @override
  void dispose() {
    _model.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final o = widget.c.agentNamed('ollama')!;
    final models = o.models ?? const <String>[];
    final pulling = (o.pulling ?? const <String, String>{}).entries.toList();
    return Panel(
      title: 'Ollama (modelo local)',
      subtitle: const Text(
        'Roda na sua máquina, sem conta. Modelos pequenos cortam pior que os de nuvem e são mais lentos '
        '(minutos por etapa); vídeo longo funciona, mas um fallback na nuvem ajuda se o modelo errar o formato.',
      ),
      children: [
        if (!o.installed)
          Text.rich(
            TextSpan(
              style: const TextStyle(fontSize: 13, color: Tokens.dim),
              children: [
                const TextSpan(text: 'Ollama não instalado — '),
                link('ollama.com', () => widget.c.openUrl('https://ollama.com')),
              ],
            ),
          )
        else ...[
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: models.isEmpty
                ? const [Meta('nenhum modelo ainda — baixe um abaixo (ex.: qwen2.5:7b, ~4,7 GB)')]
                : [
                    for (final m in models)
                      Chip(
                        label: Text(m, style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12)),
                        visualDensity: VisualDensity.compact,
                      ),
                  ],
          ),
          for (final p in pulling)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                '${p.key}: ${p.value == 'downloading' ? 'baixando…' : p.value}',
                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12, color: Tokens.dim),
              ),
            ),
        ],
        const SizedBox(height: 12),
        Row(
          children: [
            SizedBox(
              width: 240,
              child: TextField(
                controller: _model,
                style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5),
                decoration: fieldDecoration(hint: 'qwen2.5:7b'),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton(
              onPressed: o.installed && (o.server ?? false) ? () => widget.c.pullOllama(_model.text) : null,
              child: const Text('Baixar modelo'),
            ),
          ],
        ),
      ],
    );
  }
}

// ── Padrões das edições ─────────────────────────────────────────────────────

class _DefaultsCard extends StatelessWidget {
  const _DefaultsCard({required this.c});
  final SettingsController c;

  @override
  Widget build(BuildContext context) {
    Widget select(String label, String value, List<String> options, ValueChanged<String> onChanged) => Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
          const SizedBox(height: 6),
          DropdownButtonFormField<String>(
            key: ValueKey('$label-$value'),
            initialValue: options.contains(value) ? value : options.first,
            decoration: fieldDecoration(),
            dropdownColor: Tokens.panel,
            style: _dropdownText,
            items: [for (final o in options) DropdownMenuItem(value: o, child: Text(o))],
            onChanged: (v) {
              if (v != null) onChanged(v);
            },
          ),
        ],
      ),
    );
    return Panel(
      title: 'Padrões das edições',
      subtitle: const Text('Vêm preenchidos no Novo edit.'),
      children: [
        Row(
          children: [
            select('Idioma', c.language, const ['pt', 'en', 'es'], c.setLanguage),
            const SizedBox(width: 14),
            select('Modelo do Whisper', c.whisperModel, const [
              'tiny',
              'base',
              'small',
              'medium',
              'large',
            ], c.setWhisperModel),
          ],
        ),
        const SizedBox(height: 10),
        CheckboxListTile(
          value: c.coldOpen,
          onChanged: (v) => c.setColdOpen(v ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          dense: true,
          title: const Text('Cold open — abrir com o melhor momento', style: TextStyle(fontSize: 13.5)),
        ),
        CheckboxListTile(
          value: c.reorder,
          onChanged: (v) => c.setReorder(v ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          dense: true,
          title: const Text('Reordenar blocos quando ajudar a reter', style: TextStyle(fontSize: 13.5)),
        ),
      ],
    );
  }
}

import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import 'theme.dart';
import 'widgets.dart';

/// What is missing to edit, in words ("um agente de IA funcionando e o
/// modelo de transcrição"), or null when nothing is.
String? missingForSetup(Setup s) {
  final missing = [if (!s.agentReady) 'um agente de IA funcionando', if (!s.whisper.ready) 'o modelo de transcrição'];
  return missing.isEmpty ? null : 'Falta ${missing.join(' e ')}.';
}

/// First run (desktop/ui/js/welcome.js): on a computer with nothing, what is
/// missing to edit: an AI agent installed, logged in and tested, and the
/// Whisper model downloaded. Keeps checking by itself while the person
/// installs or logs in in the Terminal.
class WelcomeController extends ChangeNotifier {
  WelcomeController(this.client, {this.every = const Duration(seconds: 3)});

  final AutoEditClient client;
  final Duration every;
  AutoEditApi get _api => client.api;

  Setup? setup;
  String? error;
  final Map<String, String> notes = {};
  final Set<String> testing = {};
  Timer? _poll;
  bool _disposed = false;

  void start() {
    unawaited(load());
    _poll = Timer.periodic(every, (_) => load());
  }

  Future<void> load() async {
    try {
      setup = await _api.getSetup();
      final w = setup!.whisper;
      if (w.error != null) error = 'não deu pra baixar o Whisper: ${w.error}';
    } catch (e) {
      error = 'o motor não respondeu: ${errorText(e)}';
    }
    _notify();
  }

  Future<void> _act(String name, Future<void> Function() action) async {
    error = null;
    try {
      await action();
    } catch (e) {
      error = errorText(e);
    }
    testing.remove(name);
    await load();
  }

  Future<void> install(String name) => _act(name, () async {
    final r = await _api.installAgent(name);
    notes[name] = r.command != null
        ? 'Abri o Terminal com o instalador oficial. Quando terminar, volte aqui — esta tela detecta sozinha.'
        : name == 'openrouter'
        ? 'Abri o OpenRouter no navegador. Crie uma chave, cole aqui embaixo e clique em Salvar chave.'
        : 'Abri a página de download no navegador. Instale, volte aqui e clique em Testar.';
  });

  Future<void> login(String name) => _act(name, () async {
    final r = await _api.loginAgent(name);
    notes[name] =
        'Abri o Terminal com `${r.command}`. Faça o login lá (no Claude Code: digite /login) e depois clique em Testar.';
  });

  Future<void> test(String name) {
    testing.add(name);
    _notify();
    return _act(name, () async {
      final r = await _api.testAgent(name);
      notes[name] = r.ok
          ? 'Respondeu em ${r.seconds?.toStringAsFixed(1).replaceAll('.', ',') ?? '—'}s — este agente vai editar seus vídeos.'
          : '✗ ${r.error ?? 'não respondeu'} — se ainda não fez login, clique em Fazer login.';
    });
  }

  Future<void> saveKey(String name, String key) => _act(name, () async {
    await _api.saveOpenrouterKey(SaveOpenrouterKeyRequest(key: key));
    notes[name] = 'Chave salva. Agora clique em Testar.';
  });

  Future<void> downloadWhisper() =>
      _act('whisper', () => _api.downloadWhisper(body: DownloadWhisperRequest(model: setup?.whisper.model)));

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    super.dispose();
  }
}

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key, required this.client, required this.onDone, required this.onLater, this.every});

  final AutoEditClient client;

  /// "Começar a editar" (everything is ready).
  final VoidCallback onDone;

  /// "configurar depois": don't open by itself on the next launches.
  final VoidCallback onLater;
  final Duration? every;

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  late final WelcomeController c = WelcomeController(widget.client, every: widget.every ?? const Duration(seconds: 3))
    ..start();

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
        final s = c.setup;
        return FormScreen(
          maxWidth: 720,
          children: [
            const SizedBox(height: 12),
            const Text('Vamos deixar o Auto-Edit pronto', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            const Text(
              'O app já vem com tudo pra editar — falta só o agente de IA que planeja os cortes e o modelo que '
              'transcreve o áudio. Leva uns minutos, uma vez só.',
              style: TextStyle(fontSize: 14.5, color: Tokens.dim, height: 1.5),
            ),
            const SizedBox(height: 24),
            if (s == null && c.error == null)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (s != null) ...[_agentStep(s), _whisperStep(s)],
            if (c.error != null) Notice(c.error!),
            Row(
              children: [
                TextButton(
                  onPressed: widget.onLater,
                  child: const Text('configurar depois', style: TextStyle(color: Tokens.faint)),
                ),
                const Spacer(),
                FilledButton(
                  onPressed: s?.ready ?? false ? widget.onDone : null,
                  child: const Text('Começar a editar'),
                ),
              ],
            ),
          ],
        );
      },
    );
  }

  Widget _stepNumber(int n) => Container(
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

  Widget _agentStep(Setup s) {
    final claude = s.agents.where((a) => a.name == 'claude').firstOrNull;
    final others = s.agents.where((a) => a.name != 'claude').toList();
    return Panel(
      leading: _stepNumber(1),
      title: 'Agente de IA',
      subtitle: const Text.rich(
        TextSpan(
          children: [
            TextSpan(text: 'Recomendado: '),
            TextSpan(
              text: 'Claude Code',
              style: TextStyle(fontWeight: FontWeight.w600, color: Tokens.text),
            ),
            TextSpan(text: '. Precisa de uma conta Claude (Pro ou Max) ou de API.'),
          ],
        ),
      ),
      trailing: StatePill(s.agentReady ? 'pronto' : 'pendente', ok: s.agentReady),
      children: [
        if (claude != null) _AgentLine(c: c, a: claude, setup: s, recommended: true),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text(
              'Usar outro agente (Codex, OpenRouter, Cursor, Antigravity, OpenCode, Ollama)',
              style: TextStyle(fontSize: 13, color: Tokens.dim),
            ),
            children: [for (final a in others) _AgentLine(c: c, a: a, setup: s)],
          ),
        ),
      ],
    );
  }

  Widget _whisperStep(Setup s) {
    final w = s.whisper;
    final pct = ((w.progress) * 100).round();
    return Panel(
      leading: _stepNumber(2),
      title: 'Modelo de transcrição',
      subtitle: Text(
        'O Whisper "${w.model}" (~${w.sizeMb ?? '?'} MB) transcreve o áudio no seu computador, sem enviar nada.',
      ),
      trailing: StatePill(
        w.ready
            ? 'pronto'
            : w.downloading
            ? 'baixando'
            : 'pendente',
        ok: w.ready,
      ),
      children: [
        if (w.downloading)
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(99),
                  child: LinearProgressIndicator(value: w.progress, minHeight: 6, backgroundColor: Tokens.panel2),
                ),
              ),
              const SizedBox(width: 12),
              Text('$pct%', style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5)),
            ],
          )
        else if (!w.ready)
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(onPressed: c.downloadWhisper, child: const Text('Baixar')),
          ),
      ],
    );
  }
}

class _AgentLine extends StatefulWidget {
  const _AgentLine({required this.c, required this.a, required this.setup, this.recommended = false});

  final WelcomeController c;
  final AgentStatus a;
  final Setup setup;
  final bool recommended;

  @override
  State<_AgentLine> createState() => _AgentLineState();
}

class _AgentLineState extends State<_AgentLine> {
  // Lives across the polls' rebuilds: a key being typed stays.
  final _key = TextEditingController();

  @override
  void dispose() {
    _key.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.a;
    final c = widget.c;
    final rec = widget.recommended;
    final verified = widget.setup.verifiedAgent == a.name;
    final apiKey = a.apiKey ?? false;
    final ollamaEmpty = a.name == 'ollama' && (a.models ?? const []).isEmpty;
    final usable = a.installed && !ollamaEmpty;
    final testing = c.testing.contains(a.name);
    final String meta;
    if (verified) {
      meta = 'funcionando';
    } else if (!a.installed && apiKey) {
      meta = 'precisa de uma chave da API';
    } else if (!a.installed) {
      meta = 'não instalado';
    } else if (ollamaEmpty) {
      meta = 'instalado — falta baixar um modelo (Configurações)';
    } else {
      meta =
          'instalado ${a.version ?? ''} — falta testar'
          '${a.name == 'ollama' ? ' · lento e impreciso em vídeo longo com modelo pequeno' : ''}';
    }
    final note = c.notes[a.name];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Flexible(
                child: Text(a.label, style: const TextStyle(fontWeight: FontWeight.w600)),
              ),
              if (rec) const Badge2('recomendado'),
              const SizedBox(width: 10),
              Expanded(
                flex: 3,
                child: Text(
                  meta,
                  overflow: TextOverflow.ellipsis,
                  maxLines: 2,
                  style: TextStyle(fontSize: 12.5, color: verified ? Tokens.ok : Tokens.faint),
                ),
              ),
              const SizedBox(width: 8),
              Wrap(
                spacing: 6,
                children: [
                  if (!a.installed && !apiKey)
                    SmallButton('Instalar', primary: rec, onPressed: () => c.install(a.name)),
                  if (!a.installed && apiKey) SmallButton('Criar chave', onPressed: () => c.install(a.name)),
                  if (a.installed && a.loginCommand != null && !verified)
                    SmallButton('Fazer login', onPressed: () => c.login(a.name)),
                  if (usable && !verified)
                    SmallButton(
                      testing ? 'testando…' : 'Testar',
                      primary: rec,
                      onPressed: testing ? null : () => c.test(a.name),
                    ),
                ],
              ),
            ],
          ),
          if (!a.installed && apiKey)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
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
                  SmallButton('Salvar chave', primary: true, onPressed: () => c.saveKey(a.name, _key.text)),
                ],
              ),
            ),
          if (note != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: SelectableText(note, style: const TextStyle(fontSize: 12.5, color: Tokens.dim, height: 1.5)),
            ),
        ],
      ),
    );
  }
}

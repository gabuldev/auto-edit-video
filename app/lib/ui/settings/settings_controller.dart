import 'dart:async';
import 'dart:convert';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';

import '../widgets.dart';

/// How a "Testar" (or a key, or a login) went, shown under the agent.
class AgentNote {
  const AgentNote(this.text, {this.ok = false, this.answer});
  final String text;
  final bool ok;
  final String? answer;
}

enum SaveState { idle, saving, saved, failed }

/// The state of Configurações (desktop/ui/js/settings.js): the settings this
/// screen edits save themselves a moment after the last change; agents,
/// folders and YouTube are read from (and acted on through) the engine.
class SettingsController extends ChangeNotifier {
  SettingsController(this.client, {this.debounce = const Duration(milliseconds: 600)});

  final AutoEditClient client;
  final Duration debounce;
  AutoEditApi get _api => client.api;

  // ── the settings ──────────────────────────────────────────────────────────
  bool loaded = false;
  String? error;
  SaveState saveState = SaveState.idle;

  String primary = 'claude';
  String? fallback;
  Map<String, String?> models = {};
  String language = 'pt';
  String whisperModel = 'small';
  bool coldOpen = true;
  bool reorder = true;
  String _saved = '';

  // ── agents, folders, YouTube ──────────────────────────────────────────────
  List<AgentStatus> agents = [];
  bool agentsLoading = true;
  final Map<String, AgentNote> notes = {};
  final Set<String> testing = {};
  Folders? folders;
  YouTubeAccount? youtube;
  String? youtubeError;

  /// Conectar was clicked here: only then the engine's last error is shown.
  bool _youtubeTried = false;

  Timer? _saveTimer, _statusTimer, _ollamaPoll, _youtubePoll;
  bool _disposed = false;

  /// Only the keys this screen edits: the engine merges them into the rest
  /// (verified_agent, the brand and the style change elsewhere meanwhile).
  Map<String, Object?> get _body => {
    'agent': {'primary': primary, 'fallback': fallback, 'models': models},
    'language': language,
    'whisper_model': whisperModel,
    'cold_open': coldOpen,
    'reorder': reorder,
  };

  bool get dirty => jsonEncode(_body) != _saved;

  void _adopt(Settings s) {
    final agent = s.agent;
    primary = agent?.primary ?? 'claude';
    fallback = agent?.fallback;
    models = {...?agent?.models};
    language = s.language ?? 'pt';
    whisperModel = s.whisperModel ?? 'small';
    coldOpen = s.coldOpen ?? true;
    reorder = s.reorder ?? true;
    _saved = jsonEncode(_body);
  }

  Future<void> load() async {
    error = null;
    try {
      _adopt(await _api.getSettings());
      loaded = true;
    } catch (e) {
      error = 'não deu pra ler as configurações: ${errorText(e)}';
      _notify();
      return;
    }
    _notify();
    await Future.wait([loadFolders(), loadYoutube(), loadAgents()]);
  }

  // ── editing ───────────────────────────────────────────────────────────────

  void setPrimary(String name) {
    primary = name;
    if (fallback == name) fallback = null;
    _changed();
  }

  void setFallback(String? name) {
    fallback = name;
    _changed();
  }

  void setModel(String agent, String text) {
    final value = text.trim();
    models = {...models, agent: value.isEmpty ? null : value};
    _changed();
  }

  void setLanguage(String v) => _set(() => language = v);
  void setWhisperModel(String v) => _set(() => whisperModel = v);
  void setColdOpen(bool v) => _set(() => coldOpen = v);
  void setReorder(bool v) => _set(() => reorder = v);

  void _set(void Function() change) {
    change();
    _changed();
  }

  void _changed() {
    _notify();
    if (!dirty) return;
    _saveTimer?.cancel();
    _status(SaveState.saving);
    _saveTimer = Timer(debounce, save);
  }

  Future<void> save() async {
    _saveTimer?.cancel();
    final sent = jsonEncode(_body);
    try {
      final raw = await client.transport.json('PUT', '/api/settings', body: jsonDecode(sent));
      final s = Settings.fromJson((raw as Map).cast<String, Object?>());
      if (jsonEncode(_body) != sent) {
        // changed meanwhile: save that too
        _saveTimer = Timer(debounce, save);
        return;
      }
      _adopt(s); // e.g. a fallback equal to the primary comes back cleared
      error = null;
      _status(SaveState.saved);
    } catch (e) {
      error = errorText(e);
      _status(SaveState.failed);
    }
  }

  void _status(SaveState s) {
    _statusTimer?.cancel();
    saveState = s;
    if (s == SaveState.saved) {
      _statusTimer = Timer(const Duration(milliseconds: 2500), () {
        saveState = SaveState.idle;
        _notify();
      });
    }
    _notify();
  }

  // ── agents ────────────────────────────────────────────────────────────────

  Future<void> loadAgents() async {
    try {
      agents = (await _api.listAgents()).agents;
    } catch (e) {
      error = errorText(e);
    }
    agentsLoading = false;
    final ollama = agentNamed('ollama');
    _ollamaPoll?.cancel();
    // Keep refreshing while a model downloads.
    if (ollama?.pulling?.values.contains('downloading') ?? false) {
      _ollamaPoll = Timer(const Duration(seconds: 4), loadAgents);
    }
    _notify();
  }

  AgentStatus? agentNamed(String name) {
    for (final a in agents) {
      if (a.name == name) return a;
    }
    return null;
  }

  Future<void> test(String name) async {
    testing.add(name);
    _notify();
    try {
      final r = await _api.testAgent(name, body: TestAgentRequest(model: models[name]));
      notes[name] = r.ok
          ? AgentNote('respondeu em ${_seconds(r.seconds)}', ok: true)
          : AgentNote('✗ ${r.error ?? 'falhou'}', answer: r.answer);
      // The first agent that works becomes the primary: show it.
      if (r.ok && !dirty) _adopt(await _api.getSettings());
    } catch (e) {
      notes[name] = AgentNote('✗ ${errorText(e)}');
    }
    testing.remove(name);
    _notify();
  }

  Future<void> login(String name) async {
    try {
      final r = await _api.loginAgent(name);
      notes[name] = AgentNote('abri o Terminal com `${r.command}` — termine o login lá e clique em Testar');
    } catch (e) {
      notes[name] = AgentNote('✗ ${errorText(e)}');
    }
    _notify();
  }

  Future<void> saveOpenrouterKey(String key) async {
    try {
      await _api.saveOpenrouterKey(SaveOpenrouterKeyRequest(key: key));
      notes['openrouter'] = const AgentNote('chave salva — clique em Testar', ok: true);
    } catch (e) {
      notes['openrouter'] = AgentNote('✗ ${errorText(e)}');
    }
    await loadAgents();
  }

  Future<void> removeOpenrouterKey() async {
    try {
      await _api.deleteOpenrouterKey();
    } catch (e) {
      error = errorText(e);
    }
    notes.remove('openrouter');
    await loadAgents();
  }

  Future<void> pullOllama(String model) async {
    try {
      await _api.pullOllama(PullOllamaRequest(model: model.trim().isEmpty ? 'qwen2.5:7b' : model.trim()));
    } catch (e) {
      error = errorText(e);
    }
    await loadAgents();
  }

  Future<void> openUrl(String url) async {
    try {
      await _api.openUrl(OpenUrlRequest(url: url));
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  // ── folders ───────────────────────────────────────────────────────────────

  Future<void> loadFolders() async {
    try {
      folders = await _api.getFolders();
      _notify();
    } catch (_) {
      // the card keeps what it had
    }
  }

  /// Saves just this folder (null: back to the default); the engine checks it exists.
  Future<void> saveFolder(String which, String? path) async {
    error = null;
    try {
      await client.transport.json('PUT', '/api/settings', body: {which == 'inbox' ? 'inbox' : 'output_dir': path});
      await loadFolders();
      _status(SaveState.saved);
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  Future<void> openFolder(String which) async {
    try {
      await _api.openFolder(which);
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  // ── YouTube ───────────────────────────────────────────────────────────────

  Future<void> loadYoutube() async {
    try {
      youtube = await _api.youtubeAccount();
    } catch (_) {
      return;
    }
    if (_youtubeTried && !youtube!.connecting && youtube!.error != null) {
      youtubeError = 'Não conectou: ${youtube!.error}';
    }
    _youtubePoll?.cancel();
    // The consent happens in the browser: follow it until it ends.
    if (youtube!.connecting) _youtubePoll = Timer(const Duration(seconds: 2), loadYoutube);
    _notify();
  }

  Future<void> connectOrDisconnect() async {
    youtubeError = null;
    final connected = youtube?.connected ?? false;
    _youtubeTried = !connected;
    try {
      youtube = connected ? await _api.youtubeDisconnect() : await _api.youtubeConnect();
    } catch (e) {
      youtubeError = errorText(e);
    }
    await loadYoutube();
  }

  Future<void> cancelConnect() async {
    try {
      youtube = await _api.youtubeConnectCancel();
    } catch (e) {
      youtubeError = errorText(e);
    }
    await loadYoutube();
  }

  /// The OAuth client JSON downloaded from Google Cloud.
  Future<void> setYoutubeClient(String content) async {
    youtubeError = null;
    try {
      youtube = await _api.youtubeClient(YoutubeClientRequest(content: content));
    } catch (e) {
      youtubeError = errorText(e);
    }
    _notify();
  }

  // ──────────────────────────────────────────────────────────────────────────

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    // A change still waiting its moment is saved on the way out.
    if (dirty && loaded) unawaited(save());
    _disposed = true;
    for (final t in [_saveTimer, _statusTimer, _ollamaPoll, _youtubePoll]) {
      t?.cancel();
    }
    super.dispose();
  }
}

String _seconds(double? s) => s == null ? '—' : '${s.toStringAsFixed(1).replaceAll('.', ',')}s';

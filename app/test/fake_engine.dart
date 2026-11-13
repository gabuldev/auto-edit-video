import 'dart:convert';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const healthBody = {'ok': true, 'api_version': '1.1.0', 'version': '0.48.0', 'repo_root': '/src/auto-edit-video'};

Map<String, Object?> agent(
  String name,
  String label, {
  bool installed = false,
  String? version,
  String? login,
  Map<String, Object?> extra = const {},
}) => {
  'name': name,
  'label': label,
  'installed': installed,
  'path': installed ? '/bin/$name' : null,
  'version': version,
  'login_command': login,
  'docs': 'https://example.com/$name',
  ...extra,
};

/// The engine's answers, as `auto-edit serve` gives them (trimmed), with
/// every request recorded. Change the fields to change what it says.
class FakeEngine {
  bool up = true;
  final requests = <http.Request>[];

  List<Map<String, Object?>> agents = [
    agent('claude', 'Claude Code', installed: true, version: '2.1 (Claude Code)', login: 'claude'),
    agent('cursor', 'Cursor Agent', installed: true, version: '1.0', login: 'cursor-agent login'),
    agent('codex', 'Codex (OpenAI)', login: 'codex login'),
    agent('openrouter', 'OpenRouter', extra: {'api_key': true, 'key_hint': null, 'key_source': null}),
    agent('ollama', 'Ollama (local)', extra: {'models': <String>[], 'pulling': <String, String>{}, 'server': false}),
  ];

  Map<String, Object?> whisper = {
    'model': 'small',
    'ready': false,
    'downloading': false,
    'progress': 0.0,
    'size_mb': 466,
    'error': null,
  };
  String? verifiedAgent;

  Map<String, Object?> settings = {
    'agent': {
      'primary': 'claude',
      'fallback': null,
      'models': {'claude': null, 'cursor': null, 'codex': null, 'openrouter': null, 'ollama': null},
    },
    'language': 'pt',
    'whisper_model': 'small',
    'cold_open': true,
    'reorder': true,
    'inbox': null,
    'output_dir': null,
    'overlays_dir': null,
    'verified_agent': null,
    'brand': {'name': null, 'handle': null, 'logo': null, 'logo_bg': null},
    'style': 'padrao',
  };

  Map<String, Object?> youtube = {
    'connected': false,
    'connecting': false,
    'needs_reconnect': false,
    'channel': null,
    'error': null,
    'has_client_secret': false,
    'client_id': null,
  };

  /// What `POST /api/agents/<name>/test` answers.
  Map<String, Object?> Function(String name) testResult = (name) => {
    'name': name,
    'ok': true,
    'seconds': 2.4,
    'answer': '{"ok": true}',
  };

  Map<String, Object?> get setup {
    final installed = [
      for (final a in agents)
        if (a['installed'] == true) a['name'],
    ];
    final agentReady = verifiedAgent != null && installed.contains(verifiedAgent);
    return {
      'agents': agents,
      'primary': (settings['agent'] as Map)['primary'],
      'installed': installed,
      'agent_ready': agentReady,
      'verified_agent': verifiedAgent,
      'whisper': whisper,
      'ready': agentReady && whisper['ready'] == true,
      'install_commands': <String, Object?>{},
      'platform': 'linux',
    };
  }

  Map<String, Object?> get folders => {
    'inbox': {
      'path': settings['inbox'] ?? '/src/auto-edit-video/workspace/input',
      'custom': settings['inbox'] != null,
      'exists': true,
    },
    'output': {
      'path': settings['output_dir'] ?? '/src/auto-edit-video/workspace/output',
      'custom': settings['output_dir'] != null,
      'exists': true,
    },
  };

  /// The bodies sent to `PUT /api/settings`.
  List<Map<String, Object?>> get settingsPuts => [
    for (final r in requests)
      if (r.method == 'PUT' && r.url.path == '/api/settings') (jsonDecode(r.body) as Map).cast<String, Object?>(),
  ];

  List<String> get calls => [for (final r in requests) '${r.method} ${r.url.path}'];

  Object? _handle(http.Request req) {
    final path = req.url.path;
    final body = req.body.isEmpty ? null : jsonDecode(req.body);
    switch ((req.method, path)) {
      case ('GET', '/api/health'):
        return healthBody;
      case ('GET', '/api/setup'):
        return setup;
      case ('POST', '/api/setup/whisper'):
        whisper = {...whisper, 'downloading': true, 'progress': 0.25};
        return whisper;
      case ('GET', '/api/agents'):
        return {'agents': agents};
      case ('GET', '/api/settings'):
        return settings;
      case ('PUT', '/api/settings'):
        final data = (body as Map).cast<String, Object?>();
        settings = {...settings, ...data};
        final a = (settings['agent'] as Map).cast<String, Object?>();
        if (a['fallback'] == a['primary']) settings['agent'] = {...a, 'fallback': null};
        return settings;
      case ('GET', '/api/folders'):
        return folders;
      case ('POST', '/api/folders/inbox/open' || '/api/folders/output/open'):
        return {'opened': path};
      case ('GET', '/api/publish/youtube'):
        return youtube;
      case ('PUT', '/api/publish/youtube/client'):
        youtube = {...youtube, 'has_client_secret': true, 'client_id': '123-abc.apps.googleusercontent.com'};
        return youtube;
      case ('POST', '/api/publish/youtube/connect'):
        youtube = {...youtube, 'connecting': true};
        return youtube;
      case ('POST', '/api/open-url'):
        return {'opened': (body as Map)['url']};
      case ('PUT', '/api/agents/openrouter/key'):
        final i = agents.indexWhere((a) => a['name'] == 'openrouter');
        agents[i] = {...agents[i], 'installed': true, 'key_hint': 'sk-or-…abcd', 'key_source': 'settings'};
        return agents[i];
    }
    final m = RegExp(r'^/api/agents/(\w+)/(test|login|install)$').firstMatch(path);
    if (m != null && req.method == 'POST') {
      final name = m[1]!;
      return switch (m[2]) {
        'test' => () {
          final r = testResult(name);
          if (r['ok'] == true) verifiedAgent = name;
          return r;
        }(),
        'login' => {'command': name},
        _ => {'command': 'curl -fsSL https://example.com/install.sh | bash'},
      };
    }
    return null;
  }

  AutoEditClient client() {
    final config = EngineConfig.local();
    final mock = MockClient((req) async {
      if (!up) throw http.ClientException('connection refused');
      requests.add(req);
      final out = _handle(req);
      if (out == null) return http.Response(jsonEncode({'error': 'not_found'}), 404);
      return http.Response(jsonEncode(out), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    });
    return AutoEditClient(config, transport: Transport(config, client: mock));
  }
}

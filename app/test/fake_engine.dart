import 'dart:convert';
import 'dart:typed_data';

import 'package:auto_edit/platform.dart';
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

/// A 1×1 transparent PNG.
final pngPixel = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
);

class FakePickers implements Pickers {
  String? nextFolder;
  String? nextJson;
  String? nextVideo;
  @override
  Future<String?> folder({String? initial}) async => nextFolder;
  @override
  Future<String?> jsonFile({String? title}) async => nextJson;
  @override
  Future<String?> video({String? initial}) async => nextVideo;
  (Uint8List, String)? nextImage;
  String? nextStyleFile;
  @override
  Future<(Uint8List, String)?> image() async => nextImage;
  @override
  Future<String?> styleFile() async => nextStyleFile;
}

Map<String, Object?> summary(
  String id, {
  String type = 'long',
  String status = 'done',
  String? stage = 'done',
  String? name,
  String? title,
  Map<String, Object?>? published,
}) => {
  'id': id,
  'name': name,
  'video_name': '$id.mp4',
  'video_path': '/inbox/$id.mp4',
  'type': type,
  'language': 'pt',
  'current_stage': stage,
  'status': status,
  'title': title,
  'has_thumbnail': false,
  'stages': {
    for (final s in ['extract', 'plan', 'review', 'evaluate', 'execute', 'overlay', 'caption', 'metadata', 'thumbnail'])
      s: (type == 'long' && s == 'caption') || (type == 'short' && s == 'overlay')
          ? 'skip'
          : status == 'done'
          ? 'complete'
          : 'pending',
  },
  'published': published,
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

  List<Map<String, Object?>> library = [];

  Map<String, Object?> recordings = {
    'folder': '/home/me/Gravações',
    'exists': true,
    'truncated': false,
    'recordings': <Object?>[],
  };

  /// `GET /api/videos/<id>`: the summary in [library] plus this (stage_detail…).
  Map<String, Map<String, Object?>> details = {};

  /// `GET /api/videos/<id>/plan` (absent: 404 no_plan).
  Map<String, Map<String, Object?>> plans = {};

  /// `GET /api/videos/<id>/result`, `/publish`, `/publish/live`, `/captions`.
  Map<String, Map<String, Object?>> results = {};
  Map<String, Map<String, Object?>> publishes = {};
  Map<String, Map<String, Object?>> lives = {};
  Map<String, Map<String, Object?>> captions = {};

  /// `GET /api/videos/<id>/shorts`.
  Map<String, Map<String, Object?>> shorts = {};

  /// `GET /api/styles` (null: 404).
  Map<String, Object?>? styles;

  /// The SSE history of `/api/videos/<id>/events` (lines of `data:`).
  Map<String, List<Map<String, Object?>>> events = {};

  /// The bodies sent to `POST /api/edit`.
  List<Map<String, Object?>> get edits => [
    for (final r in requests)
      if (r.method == 'POST' && r.url.path == '/api/edit') (jsonDecode(r.body) as Map).cast<String, Object?>(),
  ];

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
      case ('GET', '/api/library'):
        return {'videos': library};
      case ('POST', '/api/publish/youtube/refresh'):
        return {'checked': true, 'changed': false};
      case ('GET', '/api/recordings'):
        return recordings;
      case ('GET', '/api/video-file'):
        final p = req.url.queryParameters['path']!;
        return {'name': p.split('/').last, 'path': p, 'size': 734003200, 'modified': '2026-11-10T10:00:00+00:00'};
      case ('POST', '/api/edit'):
        final id = ((body as Map)['video_path'] as String).split('/').last.split('.').first;
        library = [...library, summary(id, type: body['type'] as String, status: 'running', stage: 'extract')];
        return {'job_id': 'job-$id', 'video_id': id};
      case ('POST', '/api/open-url'):
        return {'opened': (body as Map)['url']};
      case ('PUT', '/api/agents/openrouter/key'):
        final i = agents.indexWhere((a) => a['name'] == 'openrouter');
        agents[i] = {...agents[i], 'installed': true, 'key_hint': 'sk-or-…abcd', 'key_source': 'settings'};
        return agents[i];
    }
    final sh = RegExp(r'^/api/videos/([\w-]+)/shorts(/cut)?$').firstMatch(path);
    if (sh != null) {
      final id = sh[1]!;
      if (req.method == 'GET') return shorts[id];
      if (sh[2] == null) {
        shorts[id] = {
          ...shorts[id]!,
          'job': {'id': 'clip-$id', 'status': 'running'},
        };
        return {'job_id': 'clip-$id', 'video_id': id};
      }
      final pick = ((body as Map)['pick'] as List).cast<int>();
      return {
        'shorts': [for (final n in pick) '${id}_short$n'],
      };
    }
    if (path.startsWith('/api/styles') || path.startsWith('/api/brand')) return _styles(req, path, body);
    final r = RegExp(
      r'^/api/videos/([\w-]+)/(result|thumbnail|publish|publish/live|publish/youtube|captions|captions/preview)$',
    ).firstMatch(path);
    if (r != null) {
      final id = r[1]!;
      switch ((req.method, r[2])) {
        case ('GET', 'result'):
          return results[id];
        case ('PUT', 'thumbnail'):
          final v = (body as Map)['variant'];
          final thumbs = [
            for (final t in (results[id]!['thumbnails'] as List).cast<Map>()) {...t, 'chosen': t['id'] == v},
          ];
          results[id] = {...results[id]!, 'thumbnails': thumbs};
          return {'thumbnails': thumbs};
        case ('GET', 'publish'):
          return publishes[id];
        case ('GET', 'publish/live'):
          return lives[id] ?? {'checked': false, 'videos': <String, Object?>{}};
        case ('POST', 'publish/youtube'):
          publishes[id] = {
            ...publishes[id]!,
            'job': {'id': 'pub-$id', 'status': 'running'},
          };
          return {'job_id': 'pub-$id', 'video_id': id};
        case ('GET', 'captions'):
          return captions[id];
        case ('PUT', 'captions'):
          captions[id] = {...captions[id]!, 'adjust': body};
          return captions[id];
        case ('POST', 'captions/preview'):
          return {'__png': true};
      }
      return null;
    }
    final d = RegExp(r'^/api/videos/([\w-]+)(/plan|/resume|/open/\w+)?$').firstMatch(path);
    if (d != null) {
      final id = d[1]!;
      final sub = d[2];
      if (req.method == 'GET' && sub == null) {
        final base = library.where((x) => x['id'] == id).firstOrNull;
        if (base == null) return null;
        return {'stage_detail': <String, Object?>{}, ...base, ...?details[id]};
      }
      if (sub == '/plan' && req.method == 'GET') return plans[id] ?? {'__error': 'no_plan'};
      if (sub == '/plan' && req.method == 'PUT') {
        final kept = ((body as Map)['kept_segments'] as List).cast<Map>();
        final old = (plans[id]!['kept_segments'] as List).cast<Map>();
        final next = [
          for (final (i, k) in kept.indexed)
            {...old.firstWhere((o) => o['start'] == k['start']).cast<String, Object?>(), 'index': i},
        ];
        plans[id] = {...plans[id]!, 'kept_segments': next, 'editable': true, 'source': 'reviewed_plan.json'};
        return plans[id];
      }
      if (sub == '/resume' && req.method == 'POST') {
        library = [
          for (final x in library) x['id'] == id ? {...x, 'status': 'running'} : x,
        ];
        return {'job_id': 'job-$id', 'video_id': id};
      }
      if (sub != null && sub.startsWith('/open/') && req.method == 'POST') return {'opened': sub};
    }
    final v = RegExp(r'^/api/videos/([\w-]+)(/stop)?$').firstMatch(path);
    if (v != null && (req.method == 'DELETE' || (req.method == 'POST' && v[2] != null))) {
      final id = v[1]!;
      if (req.method == 'DELETE') {
        library = [...library.where((x) => x['id'] != id)];
        return {'id': id, 'removed': <String>[]};
      }
      library = [
        for (final x in library) x['id'] == id ? {...x, 'status': 'failed'} : x,
      ];
      return {
        'id': id,
        'stopped': <String>['job'],
        'reset_stages': <String>[],
      };
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

  Object? _styles(http.Request req, String path, Object? body) {
    final st = styles;
    if (st == null) return null;
    final list = (st['styles'] as List).cast<Map<String, Object?>>();
    switch ((req.method, path)) {
      case ('GET', '/api/styles'):
        return st;
      case ('PUT', '/api/styles/active'):
        st['active'] = (body as Map)['id'];
        return {'active': st['active']};
      case ('POST', '/api/styles'):
        final b = (body as Map).cast<String, Object?>();
        final id = (b['id'] as String?) ?? (b['name'] as String).toLowerCase().replaceAll(' ', '-');
        final saved = {'id': id, 'name': b['name'], 'description': '', 'builtin': false, 'tokens': b['tokens']};
        st['styles'] = [...list.where((s) => s['id'] != id), saved];
        if (b['activate'] == true) st['active'] = id;
        return saved;
      case ('POST', '/api/styles/import'):
        final f = ((body as Map)['file'] as Map).cast<String, Object?>();
        final saved = {
          'id': 'importado',
          'name': f['name'],
          'description': '',
          'builtin': false,
          'tokens': f['tokens'],
        };
        st['styles'] = [...list, saved];
        return saved;
      case ('POST', '/api/styles/palette'):
        return {
          'colors': ['#ff0000'],
          'suggested': {'accent': '#ff0000'},
        };
      case ('PUT', '/api/brand/logo'):
        st['brand'] = {...(st['brand'] as Map).cast<String, Object?>(), 'logo': '/home/me/.auto-edit/logo.png'};
        settings = {
          ...settings,
          'brand': {...(settings['brand'] as Map).cast<String, Object?>(), 'logo': '/home/me/.auto-edit/logo.png'},
        };
        return st['brand'];
      case ('DELETE', '/api/brand/logo'):
        st['brand'] = {...(st['brand'] as Map).cast<String, Object?>(), 'logo': null};
        return st['brand'];
    }
    if (path.startsWith('/api/styles/preview/')) return {'__png': true};
    final m = RegExp(r'^/api/styles/([\w-]+)(/export)?$').firstMatch(path);
    if (m != null && req.method == 'POST' && m[2] != null) {
      return {'path': '/home/me/Downloads/${m[1]}.autoedit-style.json'};
    }
    if (m != null && req.method == 'DELETE') {
      st['styles'] = [...list.where((s) => s['id'] != m[1])];
      return {'active': st['active']};
    }
    return null;
  }

  AutoEditClient client() {
    final config = EngineConfig.local();
    final mock = MockClient((req) async {
      if (!up) throw http.ClientException('connection refused');
      requests.add(req);
      final sse = RegExp(r'^/api/videos/([\w-]+)/events$').firstMatch(req.url.path);
      if (sse != null) {
        final history = events[sse[1]];
        if (history == null) return http.Response(jsonEncode({'error': 'not_found'}), 404);
        return http.Response(
          history.map((e) => 'data: ${jsonEncode(e)}\n\n').join(),
          200,
          headers: {'content-type': 'text/event-stream; charset=utf-8'},
        );
      }
      final out = _handle(req);
      if (out == null) return http.Response(jsonEncode({'error': 'not_found'}), 404);
      if (out is Map && out['__png'] == true) {
        return http.Response.bytes(pngPixel, 200, headers: {'content-type': 'image/png'});
      }
      if (out is Map && out['__error'] != null) return http.Response(jsonEncode({'error': out['__error']}), 404);
      return http.Response(jsonEncode(out), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    });
    return AutoEditClient(config, transport: Transport(config, client: mock));
  }
}

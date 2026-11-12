// Starts a real `auto-edit serve` over a throwaway workspace and drives it
// through the generated client: every response has to parse into the models.
//
//   dart test --tags integration
//
// AUTO_EDIT_BIN points at the executable (default: `auto-edit` on the PATH).
@Tags(['integration'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:test/test.dart';

late Directory root;
late Process engine;
late AutoEditClient client;
final log = StringBuffer();

void main() {
  setUpAll(() async {
    root = await Directory.systemTemp.createTemp('auto_edit_client_');
    seed(root);
    final port = await freePort();
    final bin = Platform.environment['AUTO_EDIT_BIN'] ?? 'auto-edit';
    engine = await Process.start(
      bin,
      ['serve', '--port', '$port'],
      environment: {
        'AUTO_EDIT_WORKSPACE': '${root.path}/ws',
        'AUTO_EDIT_HOME': '${root.path}/home',
        'AUTO_EDIT_INBOX': '${root.path}/inbox',
        'AUTO_EDIT_OUTPUT': '${root.path}/out',
      },
    );
    engine.stdout.transform(utf8.decoder).listen(log.write);
    engine.stderr.transform(utf8.decoder).listen(log.write);
    client = AutoEditClient(EngineConfig.local(port: port));
    await waitUp(client);
  });

  tearDownAll(() async {
    client.close();
    engine.kill();
    await engine.exitCode.timeout(
      const Duration(seconds: 5),
      onTimeout: () {
        engine.kill(ProcessSignal.sigkill);
        return -1;
      },
    );
    await root.delete(recursive: true);
  });

  test('health speaks this contract', () async {
    final health = await client.api.health();
    expect(health.ok, isTrue);
    expect(health.apiVersion, AutoEditApi.contractVersion);
    expect(await client.isCompatible(), isTrue);
  });

  test('library lists the seeded workspaces', () async {
    final library = await client.api.listLibrary();
    final byId = {for (final v in library.videos) v.id: v};
    expect(byId.keys, containsAll(['vid', 'clip']));
    expect(byId['vid']!.status, VideoStatus.done);
    expect(byId['vid']!.type, VideoType.long);
  });

  test('the read endpoints parse into the models', () async {
    final api = client.api;
    expect((await api.getVideo('vid')).id, 'vid');
    expect((await api.getPlan('vid')).keptSegments, hasLength(2));
    expect((await api.getResult('vid')).metadata, isNotNull);
    expect((await api.listEffects('vid')).effects, isEmpty);
    await api.getPublish('vid');
    await api.getRetention('vid');
    await api.getShorts('vid');
    await api.getFolders();
    await api.browse();
    await api.listRecordings();
    await api.listStyles();
    await api.getSettings();
    await api.getSetup();
    await api.listAgents();
    await api.youtubeAccount();
    await api.retentionTrend(type: 'long');
    expect(await api.getFile('vid', ArtifactKind.video), hasLength(64));
  });

  test('an unknown video is an ApiException 404', () async {
    await expectLater(
      client.api.getVideo('nope'),
      throwsA(isA<ApiException>().having((e) => e.isNotFound, 'isNotFound', isTrue)),
    );
  });

  test('follows a job to the end over SSE', () async {
    final started = await client.api.resumeVideo('clip', const ResumeVideoRequest(fromStage: 'done'));
    expect(started.videoId, 'clip');
    final events = await client.api.jobEvents(started.jobId).toList().timeout(const Duration(seconds: 60));
    expect(events.first.type, 'log');
    expect(events.map((e) => e.stage), contains('done'));
    final lines = events.map((e) => e.line ?? e.toJson().toString()).join('\n');
    expect(events.last.type, 'done', reason: lines);
    expect(events.last.output, endsWith('clip_final.mp4'));
    expect(File(events.last.output!).existsSync(), isTrue);
  });
}

Future<int> freePort() async {
  final socket = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
  final port = socket.port;
  await socket.close();
  return port;
}

Future<void> waitUp(AutoEditClient client) async {
  final deadline = DateTime.now().add(const Duration(seconds: 30));
  while (true) {
    try {
      await client.api.health();
      return;
    } on Exception {
      if (DateTime.now().isAfter(deadline)) {
        fail('auto-edit serve did not come up:\n$log');
      }
      await Future<void>.delayed(const Duration(milliseconds: 200));
    }
  }
}

void write(String path, Object data) {
  File(path)
    ..parent.createSync(recursive: true)
    ..writeAsStringSync(jsonEncode(data));
}

/// A finished long (`vid`) and a short (`clip`) that only lacks the final copy.
void seed(Directory root) {
  final r = root.path;
  for (final d in ['home', 'inbox', 'out']) {
    Directory('$r/$d').createSync(recursive: true);
  }
  write('$r/ws/vid/pipeline.json', {
    'video_name': 'vid',
    'type': 'long',
    'language': 'pt',
    'current_stage': 'done',
    'created_at': '2026-01-01T00:00:00+00:00',
    'video_path': '$r/inbox/vid.mp4',
    'output_dir': '$r/out',
    'stages': {
      'extract': {'status': 'done'},
      'plan': {'status': 'done'},
    },
  });
  write('$r/ws/vid/transcription.json', {
    'duration': 30.0,
    'segments': [
      {'start': 0.0, 'end': 10.0, 'text': 'oi'},
      {'start': 10.0, 'end': 30.0, 'text': 'tudo bem'},
    ],
  });
  write('$r/ws/vid/reviewed_plan.json', {
    'kept_segments': [
      {'start': 0.0, 'end': 10.0, 'summary': 'abertura'},
      {'start': 12.0, 'end': 30.0},
    ],
    'cuts': [
      {'start': 10.0, 'end': 12.0, 'reason': 'pausa', 'type': 'silence'},
    ],
  });
  write('$r/ws/vid/metadata.json', {
    'youtube_title': 'Título',
    'youtube_description': 'Desc',
    'tags': ['a'],
  });
  File('$r/out/vid_final.mp4').writeAsBytesSync(List.filled(64, 0));

  write('$r/ws/clip/pipeline.json', {
    'video_name': 'clip',
    'type': 'short',
    'language': 'pt',
    'current_stage': 'done',
    'created_at': '2026-01-02T00:00:00+00:00',
    'stages': {},
  });
  File('$r/ws/clip/edited_video.mp4').writeAsBytesSync(List.filled(64, 0));
}

import 'dart:convert';
import 'dart:io';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

/// An engine that keeps one upload in memory, as auto_edit/uploads.py does.
class FakeUploads {
  FakeUploads(this.size);
  final int size;
  final received = <int>[];
  int puts = 0;

  /// Throw (a dropped connection) on these PUT numbers, after the engine wrote the chunk.
  Set<int> dropAnswerOn = {};

  Map<String, Object?> get state => {
    'id': 'u1',
    'name': 'a.mp4',
    'size': size,
    'offset': received.length,
    'done': received.length == size,
    'path': received.length == size ? '/inbox/Celular/a.mp4' : null,
  };

  late final client = MockClient((req) async {
    if (req.method == 'POST') return http.Response(jsonEncode(state), 201);
    if (req.method == 'GET') return http.Response(jsonEncode(state), 200);
    puts++;
    final offset = int.parse(req.url.queryParameters['offset']!);
    if (offset != received.length) {
      return http.Response(jsonEncode({'error': 'offset errado', 'upload': state}), 409);
    }
    received.addAll(req.bodyBytes);
    if (dropAnswerOn.contains(puts)) throw const SocketException('Wi-Fi caiu');
    return http.Response(jsonEncode(state), 200);
  });
}

void main() {
  final data = List<int>.generate(10000, (i) => i % 251);
  Future<List<int>> read(int offset, int length) async => data.sublist(offset, offset + length);

  test('sends in chunks and reports progress', () async {
    final engine = FakeUploads(data.length);
    final api = AutoEditClient(
      EngineConfig.local(),
      transport: Transport(EngineConfig.local(), client: engine.client),
    ).api;
    final progress = <int>[];
    final done = await sendResumable(
      api,
      name: 'a.mp4',
      size: data.length,
      read: read,
      chunkSize: 4096,
      onProgress: (sent, _) => progress.add(sent),
    );
    expect(done.done, isTrue);
    expect(engine.received, data);
    expect(progress, [0, 4096, 8192, 10000]);
  });

  test('a lost answer resumes from what the engine has, without duplicating', () async {
    final engine = FakeUploads(data.length)..dropAnswerOn = {2};
    final api = AutoEditClient(
      EngineConfig.local(),
      transport: Transport(EngineConfig.local(), client: engine.client),
    ).api;
    final done = await sendResumable(
      api,
      name: 'a.mp4',
      size: data.length,
      read: read,
      chunkSize: 4096,
      pause: (_) => Duration.zero,
    );
    expect(done.done, isTrue);
    expect(engine.received, data); // the 2nd chunk arrived once
  });

  test('resumeId continues an earlier upload', () async {
    final engine = FakeUploads(data.length)..received.addAll(data.sublist(0, 6000));
    final api = AutoEditClient(
      EngineConfig.local(),
      transport: Transport(EngineConfig.local(), client: engine.client),
    ).api;
    String? started;
    await sendResumable(
      api,
      name: 'a.mp4',
      size: data.length,
      read: read,
      resumeId: 'u1',
      onStarted: (id) => started = id,
    );
    expect(started, 'u1');
    expect(engine.puts, 1);
    expect(engine.received, data);
  });

  test('gives up after the retries', () async {
    final api = AutoEditClient(
      EngineConfig.local(),
      transport: Transport(
        EngineConfig.local(),
        client: MockClient((req) async {
          if (req.method == 'POST') return http.Response(jsonEncode(FakeUploads(10).state), 201);
          throw const SocketException('sem rede');
        }),
      ),
    ).api;
    await expectLater(
      sendResumable(api, name: 'a.mp4', size: 10, read: read, retries: 2, pause: (_) => Duration.zero),
      throwsA(isA<SocketException>()),
    );
  });
}

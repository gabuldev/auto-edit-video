import 'dart:async';
import 'dart:convert';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

String sse(List<Map<String, Object?>> events) => events.map((e) => 'data: ${jsonEncode(e)}\n\n').join();

const fast = ReconnectPolicy(maxAttempts: 3, initialDelay: Duration(milliseconds: 1));

void main() {
  group('EngineConfig.parse', () {
    test('host only gets http and the default port', () {
      expect(EngineConfig.parse('192.168.0.10').baseUrl.toString(), 'http://192.168.0.10:8760');
    });
    test('keeps an explicit scheme and port', () {
      expect(EngineConfig.parse('https://motor.exemplo.com/').baseUrl.port, 443);
      expect(EngineConfig.parse('http://casa.local:80').baseUrl.port, 80);
      expect(EngineConfig.parse('casa.local:9000').baseUrl.port, 9000);
    });
    test('local is the desktop engine', () {
      expect(EngineConfig.local().baseUrl.toString(), 'http://127.0.0.1:8760');
    });
  });

  test('sends the token, the JSON body and the query', () async {
    late http.Request seen;
    final client = MockClient((req) async {
      seen = req;
      if (req.url.path == '/api/browse') {
        return http.Response(
          jsonEncode({'dir': '/tmp/a b', 'parent': '/tmp', 'exists': true, 'dirs': [], 'videos': []}),
          200,
        );
      }
      return http.Response(jsonEncode({'video_id': 'v', 'job_id': 'j'}), 202);
    });
    final api = AutoEditApi(
      Transport(
        EngineConfig(baseUrl: _base, token: 's3cret'),
        client: client,
      ),
    );
    final started = await api.resumeVideo('meu vídeo', const ResumeVideoRequest(fromStage: 'caption'));
    expect(started.jobId, 'j');
    expect(seen.method, 'POST');
    expect(seen.url.path, '/api/videos/meu%20v%C3%ADdeo/resume');
    expect(seen.headers['Authorization'], 'Bearer s3cret');
    expect(jsonDecode(seen.body), {'from_stage': 'caption'});

    await api.browse(dir: '/tmp/a b');
    expect(seen.url.queryParameters, {'dir': '/tmp/a b'});
    expect(seen.headers.containsKey('Content-Type'), isFalse);
  });

  test('a non-2xx answer throws ApiException with the engine error', () async {
    final client = MockClient((_) async => http.Response('{"error": "no workspace for: x"}', 404));
    final api = AutoEditApi(Transport(EngineConfig(baseUrl: _base), client: client));
    await expectLater(
      api.getVideo('x'),
      throwsA(
        isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 404)
            .having((e) => e.message, 'message', 'no workspace for: x'),
      ),
    );
  });

  group('events', () {
    final history = <Map<String, Object?>>[
      {'type': 'log', 'line': 'um'},
      {'type': 'stage', 'stage': 'execute'},
      {'type': 'log', 'line': 'dois'},
      {'type': 'done', 'status': 'done', 'output': '/out/v_final.mp4'},
    ];

    test('ends after done', () async {
      final client = MockClient.streaming(
        (req, _) async => http.StreamedResponse(
          Stream.value(
            utf8.encode(
              sse(history) +
                  sse([
                    {'type': 'log', 'line': 'x'},
                  ]),
            ),
          ),
          200,
        ),
      );
      final api = AutoEditApi(Transport(EngineConfig(baseUrl: _base), client: client));
      final events = await api.jobEvents('j').toList();
      expect(events.map((e) => e.type), ['log', 'stage', 'log', 'done']);
      expect(events.last.output, '/out/v_final.mp4');
    });

    test('reconnects after a drop and skips the replayed history', () async {
      var calls = 0;
      final client = MockClient.streaming((req, _) async {
        calls++;
        if (calls == 1) {
          // two events, then the connection breaks
          final ctrl = StreamController<List<int>>();
          ctrl.add(utf8.encode(sse(history.sublist(0, 2))));
          scheduleMicrotask(() {
            ctrl.addError(http.ClientException('connection reset'));
            ctrl.close();
          });
          return http.StreamedResponse(ctrl.stream, 200);
        }
        if (calls == 2) throw http.ClientException('refused'); // engine restarting
        return http.StreamedResponse(Stream.value(utf8.encode(sse(history))), 200);
      });
      final api = AutoEditApi(
        Transport(
          EngineConfig(baseUrl: _base),
          client: client,
          reconnect: fast,
        ),
      );
      final seen = await api.jobEvents('j').map((e) => e.line ?? e.stage ?? e.type).toList();
      expect(seen, ['um', 'execute', 'dois', 'done']);
      expect(calls, 3);
    });

    test('gives up after maxAttempts failures in a row', () async {
      var calls = 0;
      final client = MockClient.streaming((req, _) async {
        calls++;
        throw http.ClientException('refused');
      });
      final api = AutoEditApi(
        Transport(
          EngineConfig(baseUrl: _base),
          client: client,
          reconnect: fast,
        ),
      );
      await expectLater(api.jobEvents('j').toList(), throwsA(isA<http.ClientException>()));
      expect(calls, fast.maxAttempts + 1);
    });

    test('an unknown job is not retried', () async {
      var calls = 0;
      final client = MockClient.streaming((req, _) async {
        calls++;
        return http.StreamedResponse(Stream.value(utf8.encode('{"error": "no job"}')), 404);
      });
      final api = AutoEditApi(
        Transport(
          EngineConfig(baseUrl: _base),
          client: client,
          reconnect: fast,
        ),
      );
      await expectLater(api.jobEvents('j').toList(), throwsA(isA<ApiException>()));
      expect(calls, 1);
    });

    test('a stream that closes without a final event ends once nothing new comes', () async {
      var calls = 0;
      final client = MockClient.streaming((req, _) async {
        calls++;
        return http.StreamedResponse(Stream.value(utf8.encode(sse(history.sublist(0, 2)))), 200);
      });
      final api = AutoEditApi(
        Transport(
          EngineConfig(baseUrl: _base),
          client: client,
          reconnect: fast,
        ),
      );
      expect(await api.jobEvents('j').length, 2);
      expect(calls, 2);
    });
  });
}

final _base = Uri.parse('http://motor:8760');

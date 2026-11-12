import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'sse.dart';

/// Where the engine is and how to talk to it.
///
/// The same client drives the engine on this machine (`127.0.0.1:8760`, what
/// the desktop app starts), the home computer from the phone (its LAN or VPN
/// address) or the cloud. [token] goes as `Authorization: Bearer` when set.
class EngineConfig {
  const EngineConfig({required this.baseUrl, this.token});

  /// The engine the desktop app starts on this machine.
  factory EngineConfig.local({int port = 8760}) => EngineConfig(baseUrl: Uri.parse('http://127.0.0.1:$port'));

  /// `host`, `host:port` or a full URL (`http://192.168.0.10:8760`). Plain
  /// http without a port gets the engine's 8760; https keeps 443 (the cloud).
  factory EngineConfig.parse(String address, {String? token}) {
    var text = address.trim();
    if (!text.contains('://')) text = 'http://$text';
    var uri = Uri.parse(text);
    final explicitPort = RegExp(r'^[a-z]+://[^/]*:\d+', caseSensitive: false).hasMatch(text);
    if (uri.scheme == 'http' && !explicitPort) uri = uri.replace(port: 8760);
    return EngineConfig(
      baseUrl: uri.replace(path: ''),
      token: token,
    );
  }

  final Uri baseUrl;
  final String? token;
}

/// A non-2xx answer. [message] is the engine's `{"error": ...}` when it sent one.
class ApiException implements Exception {
  ApiException(this.statusCode, this.message, {this.body});

  final int statusCode;
  final String message;
  final String? body;

  bool get isNotFound => statusCode == 404;
  bool get isConflict => statusCode == 409;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// How [Transport.events] reconnects when the connection drops mid-job.
class ReconnectPolicy {
  const ReconnectPolicy({
    this.maxAttempts = 8,
    this.initialDelay = const Duration(milliseconds: 500),
    this.maxDelay = const Duration(seconds: 10),
  });

  /// Attempts in a row without receiving anything; then the stream errors.
  final int maxAttempts;
  final Duration initialDelay;
  final Duration maxDelay;

  Duration delay(int attempt) {
    final ms = initialDelay.inMilliseconds * (1 << (attempt - 1).clamp(0, 16));
    return Duration(milliseconds: ms.clamp(0, maxDelay.inMilliseconds));
  }
}

/// HTTP to one engine. The generated [AutoEditApi] calls this.
class Transport {
  Transport(this.config, {http.Client? client, this.reconnect = const ReconnectPolicy()})
    : _client = client ?? http.Client();

  final EngineConfig config;
  final ReconnectPolicy reconnect;
  final http.Client _client;

  /// Headers every request carries (the token). Hand them to a video player
  /// or an image widget together with a `...Uri` method.
  Map<String, String> get headers => {if (config.token != null) 'Authorization': 'Bearer ${config.token}'};

  Uri uri(String path, {Map<String, String>? query}) {
    final base = config.baseUrl;
    final prefix = base.path.endsWith('/') ? base.path.substring(0, base.path.length - 1) : base.path;
    return base.replace(path: '$prefix$path', queryParameters: (query == null || query.isEmpty) ? null : query);
  }

  /// Sends a request and decodes the JSON answer (null for an empty body).
  Future<Object?> json(String method, String path, {Map<String, String>? query, Object? body}) async {
    final res = await _send(method, path, query: query, body: body);
    final text = utf8.decode(res.bodyBytes);
    return text.isEmpty ? null : jsonDecode(text);
  }

  /// Sends a request and returns the raw answer (PNG, JPEG, the video...).
  Future<Uint8List> bytes(String method, String path, {Map<String, String>? query, Object? body}) async =>
      (await _send(method, path, query: query, body: body)).bodyBytes;

  Future<http.Response> _send(String method, String path, {Map<String, String>? query, Object? body}) async {
    final req = http.Request(method, uri(path, query: query))..headers.addAll(headers);
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final res = await http.Response.fromStream(await _client.send(req));
    if (res.statusCode >= 200 && res.statusCode < 300) return res;
    throw _error(res.statusCode, utf8.decode(res.bodyBytes, allowMalformed: true));
  }

  static ApiException _error(int status, String text) {
    var message = text.isEmpty ? 'HTTP $status' : text;
    try {
      final decoded = jsonDecode(text);
      if (decoded is Map && decoded['error'] is String) message = decoded['error'] as String;
    } on FormatException {
      // not JSON: keep the text
    }
    return ApiException(status, message, body: text);
  }

  /// The decoded `data:` of each Server-Sent Event, until the job ends.
  ///
  /// The engine replays a job's history from the start to every subscriber,
  /// so after a dropped connection this reconnects and skips what it already
  /// delivered: each event arrives once and in order. The stream ends after a
  /// `done` or `error` event; an [ApiException] (404: unknown job) is not
  /// retried. For `videos/<id>/events` a reconnection reaches the video's
  /// *current* job: if a new one started meanwhile, the count no longer lines up.
  Stream<Object?> events(String path) async* {
    var delivered = 0;
    var attempt = 0;
    while (true) {
      var skip = delivered;
      var fresh = false; // delivered something new on this connection
      try {
        final req = http.Request('GET', uri(path))
          ..headers.addAll(headers)
          ..headers['Accept'] = 'text/event-stream';
        final res = await _client.send(req);
        if (res.statusCode != 200) {
          throw _error(res.statusCode, await res.stream.bytesToString());
        }
        await for (final data in parseSse(res.stream)) {
          if (skip > 0) {
            skip--;
            continue;
          }
          final event = jsonDecode(data);
          delivered++;
          fresh = true;
          attempt = 0;
          yield event;
          if (event is Map && (event['type'] == 'done' || event['type'] == 'error')) return;
        }
        // Closed cleanly with nothing new: the job ended without a final event.
        if (!fresh) return;
        attempt++;
      } on ApiException {
        rethrow;
      } catch (_) {
        attempt++;
        if (attempt > reconnect.maxAttempts) rethrow;
      }
      await Future<void>.delayed(reconnect.delay(attempt < 1 ? 1 : attempt));
    }
  }

  void close() => _client.close();
}

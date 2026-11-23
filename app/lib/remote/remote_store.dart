import 'dart:convert';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// The computer this phone is paired with: where it is, its certificate and
/// this device's token.
class RemoteEngine {
  const RemoteEngine({required this.baseUrl, required this.token, required this.fingerprint, this.name});

  final Uri baseUrl;
  final String token;
  final String fingerprint;

  /// The computer's name (from the QR), to show.
  final String? name;

  EngineConfig get config => EngineConfig(baseUrl: baseUrl, token: token, fingerprint: fingerprint);

  /// The same computer at another address (the network gave it a new IP).
  RemoteEngine at(String host, int port) => RemoteEngine(
    baseUrl: baseUrl.replace(host: host, port: port),
    token: token,
    fingerprint: fingerprint,
    name: name,
  );

  Map<String, Object?> toJson() => {
    'base_url': baseUrl.toString(),
    'token': token,
    'fingerprint': fingerprint,
    'name': name,
  };

  static RemoteEngine? fromJson(Object? json) {
    if (json is! Map) return null;
    final url = Uri.tryParse(json['base_url'] as String? ?? '');
    final token = json['token'] as String?;
    final fp = json['fingerprint'] as String?;
    if (url == null || token == null || fp == null) return null;
    return RemoteEngine(baseUrl: url, token: token, fingerprint: fp, name: json['name'] as String?);
  }
}

/// Where the pairing is kept: the token is a secret, so the OS keychain.
abstract class RemoteStore {
  Future<RemoteEngine?> load();
  Future<void> save(RemoteEngine engine);
  Future<void> clear();
}

class SecureRemoteStore implements RemoteStore {
  SecureRemoteStore([FlutterSecureStorage? storage]) : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'auto_edit.remote_engine';
  final FlutterSecureStorage _storage;

  @override
  Future<RemoteEngine?> load() async {
    final text = await _storage.read(key: _key);
    if (text == null) return null;
    try {
      return RemoteEngine.fromJson(jsonDecode(text));
    } on FormatException {
      return null;
    }
  }

  @override
  Future<void> save(RemoteEngine engine) => _storage.write(key: _key, value: jsonEncode(engine.toJson()));

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

class MemoryRemoteStore implements RemoteStore {
  MemoryRemoteStore([this.engine]);
  RemoteEngine? engine;

  @override
  Future<RemoteEngine?> load() async => engine;

  @override
  Future<void> save(RemoteEngine e) async => engine = e;

  @override
  Future<void> clear() async => engine = null;
}

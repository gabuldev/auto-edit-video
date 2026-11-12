/// Client of the auto-edit engine API (`auto-edit serve`), generated from
/// `auto_edit/openapi.yaml`.
///
/// ```dart
/// final engine = AutoEditClient(EngineConfig.local());
/// final health = await engine.api.health();
/// await for (final event in engine.api.jobEvents(jobId)) { ... }
/// ```
library;

import 'src/generated/api.dart';
import 'src/transport.dart';

export 'src/generated/api.dart';
export 'src/generated/models.dart';
export 'src/sse.dart' show parseSse;
export 'src/transport.dart';

/// One engine: its [Transport] and the generated [AutoEditApi] over it.
class AutoEditClient {
  AutoEditClient(this.config, {Transport? transport}) : transport = transport ?? Transport(config);

  final EngineConfig config;
  final Transport transport;
  late final AutoEditApi api = AutoEditApi(transport);

  /// Whether the engine speaks a contract this client understands: the same
  /// major version (a minor bump only adds routes and fields).
  Future<bool> isCompatible() async {
    final health = await api.health();
    return health.apiVersion.split('.').first == AutoEditApi.contractVersion.split('.').first;
  }

  void close() => transport.close();
}

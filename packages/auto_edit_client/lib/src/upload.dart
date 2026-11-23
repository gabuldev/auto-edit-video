import 'dart:async';
import 'dart:convert';

import 'generated/api.dart';
import 'generated/models.dart';
import 'transport.dart';

/// Reads [length] bytes of the file at [offset] (a phone's file, a picker's stream...).
typedef ChunkReader = Future<List<int>> Function(int offset, int length);

/// Sends a video to the engine's inbox in chunks (`/api/uploads`), resuming
/// where the engine stopped: a dropped Wi-Fi or a resent chunk never starts
/// over nor duplicates bytes.
///
/// Pass [resumeId] (an [Upload.id] saved from an earlier try) to continue
/// that upload. [onStarted] gets the id as soon as there is one, to save it.
/// Network errors are retried [retries] times in a row, with a growing pause;
/// an [ApiException] other than a wrong offset (409) ends it.
Future<Upload> sendResumable(
  AutoEditApi api, {
  required String name,
  required int size,
  required ChunkReader read,
  String? resumeId,
  int chunkSize = 8 << 20,
  int retries = 6,
  void Function(String id)? onStarted,
  void Function(int sent, int total)? onProgress,
  Duration Function(int attempt) pause = _pause,
}) async {
  var state = resumeId != null
      ? await api.getUpload(resumeId)
      : await api.createUpload(CreateUploadRequest(name: name, size: size));
  onStarted?.call(state.id);
  onProgress?.call(state.offset, state.size);
  var failures = 0;
  while (!state.done) {
    final length = (state.size - state.offset).clamp(0, chunkSize);
    try {
      final bytes = await read(state.offset, length);
      state = await api.uploadChunk(state.id, bytes, offset: state.offset);
      failures = 0;
      onProgress?.call(state.offset, state.size);
    } on ApiException catch (e) {
      final at = e.statusCode == 409 ? _uploadIn(e.body) : null;
      if (at == null) rethrow;
      state = at; // the engine had a different offset: continue from there
    } catch (_) {
      failures++;
      if (failures > retries) rethrow;
      await Future<void>.delayed(pause(failures));
      try {
        state = await api.getUpload(state.id);
      } on ApiException {
        rethrow;
      } catch (_) {
        // still offline: the next round tries again
      }
    }
  }
  return state;
}

Duration _pause(int attempt) => Duration(seconds: (1 << (attempt - 1)).clamp(1, 30));

Upload? _uploadIn(String? body) {
  if (body == null) return null;
  try {
    final decoded = jsonDecode(body);
    if (decoded is Map && decoded['upload'] is Map) {
      return Upload.fromJson((decoded['upload'] as Map).cast<String, Object?>());
    }
  } on FormatException {
    // not JSON
  }
  return null;
}

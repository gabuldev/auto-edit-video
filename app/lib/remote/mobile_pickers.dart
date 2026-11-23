import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../platform.dart';
import '../ui/format.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart' show errorText;

/// Reads [length] bytes at [offset] of a file on this phone.
Future<List<int>> readFileChunk(String path, int offset, int length) async {
  final f = await File(path).open();
  try {
    await f.setPosition(offset);
    return await f.read(length);
  } finally {
    await f.close();
  }
}

/// Sends a local file to the engine's inbox with a progress dialog; the
/// engine's path of it, or null if cancelled or failed (the dialog said why).
Future<String?> uploadWithDialog(NavigatorState nav, AutoEditClient client, String path, {String? name}) async {
  final progress = ValueNotifier<(int, int)>((0, 0));
  final error = ValueNotifier<String?>(null);
  String? uploadId;
  var cancelled = false;
  final file = File(path);
  final size = await file.length();
  final fileName = name ?? path.split(Platform.pathSeparator).last;
  if (!nav.mounted) return null;

  final dialog = showDialog<void>(
    context: nav.context,
    barrierDismissible: false,
    builder: (context) => _UploadDialog(
      name: fileName,
      progress: progress,
      error: error,
      onCancel: () {
        cancelled = true;
        Navigator.of(context).pop();
      },
    ),
  );

  String? result;
  try {
    final up = await sendResumable(
      client.api,
      name: fileName,
      size: size,
      read: (offset, length) {
        if (cancelled) throw const _Cancelled();
        return readFileChunk(path, offset, length);
      },
      onStarted: (id) => uploadId = id,
      onProgress: (sent, total) => progress.value = (sent, total),
    );
    result = up.path;
    if (!cancelled) nav.pop();
  } on _Cancelled {
    // the dialog is already closed
  } catch (e) {
    if (!cancelled) error.value = 'Não deu pra mandar o vídeo: ${errorText(e)}';
    await dialog;
  }
  if (cancelled && uploadId != null) {
    unawaited(client.api.cancelUpload(uploadId!).then((_) {}, onError: (_) {}));
  }
  return cancelled ? null : result;
}

class _Cancelled implements Exception {
  const _Cancelled();
}

class _UploadDialog extends StatelessWidget {
  const _UploadDialog({
    this.title = 'Mandando pro computador',
    required this.name,
    required this.progress,
    required this.error,
    required this.onCancel,
  });

  final String title;
  final String name;
  final ValueNotifier<(int, int)> progress;
  final ValueNotifier<String?> error;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(title),
    content: ListenableBuilder(
      listenable: Listenable.merge([progress, error]),
      builder: (context, _) {
        final (sent, total) = progress.value;
        final fraction = total == 0 ? null : sent / total;
        return Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(name, style: const TextStyle(fontSize: 13.5), overflow: TextOverflow.ellipsis),
            const SizedBox(height: 14),
            if (error.value != null)
              Text(error.value!, style: const TextStyle(color: Tokens.err, fontSize: 13))
            else ...[
              LinearProgressIndicator(value: fraction),
              const SizedBox(height: 8),
              Text(
                total == 0 ? 'Começando…' : '${(fraction! * 100).floor()}% · ${humanSize(sent)} de ${humanSize(total)}',
                style: const TextStyle(fontSize: 12.5, color: Tokens.dim),
              ),
              const SizedBox(height: 6),
              const Text(
                'Deixe o app aberto. Se a rede cair, continua de onde parou.',
                style: TextStyle(fontSize: 12, color: Tokens.faint),
              ),
            ],
          ],
        );
      },
    ),
    actions: [
      ListenableBuilder(
        listenable: error,
        builder: (context, _) =>
            TextButton(onPressed: onCancel, child: Text(error.value != null ? 'Fechar' : 'Cancelar')),
      ),
    ],
  );
}

/// The phone's pickers: a video comes from the gallery and is sent to the
/// computer (the engine edits files on its own disk); the rest are the
/// regular file dialogs. Folders are the computer's: not chosen here.
class MobilePickers implements Pickers {
  MobilePickers({required this.client, required this.navigator, ImagePicker? picker})
    : _picker = picker ?? ImagePicker();

  final AutoEditClient client;
  final GlobalKey<NavigatorState> navigator;
  final ImagePicker _picker;
  final _files = const NativePickers();

  Future<String?> _galleryVideo() async {
    final file = await _picker.pickVideo(source: ImageSource.gallery);
    final nav = navigator.currentState;
    if (file == null || nav == null) return null;
    return uploadWithDialog(nav, client, file.path, name: file.name);
  }

  @override
  Future<String?> video({String? initial}) => _galleryVideo();

  @override
  Future<String?> broll() => _galleryVideo();

  @override
  bool get canShare => true;

  @override
  Future<void> share(AutoEditClient client, String videoId, String kind, String fileName) async {
    final dir = Directory('${(await getTemporaryDirectory()).path}/auto-edit/$videoId');
    await dir.create(recursive: true);
    final dest = File('${dir.path}/$fileName');
    final nav = navigator.currentState;
    if (nav == null) return;
    final ok = await downloadWithDialog(nav, client, client.api.getFileUri(videoId, ArtifactKind(kind)), dest);
    if (ok) await SharePlus.instance.share(ShareParams(files: [XFile(dest.path)]));
  }

  @override
  Future<String?> folder({String? initial}) async => null;

  @override
  Future<String?> jsonFile({String? title}) => _files.jsonFile(title: title);

  @override
  Future<(Uint8List, String)?> image() => _files.image();

  @override
  Future<String?> styleFile() => _files.styleFile();
}

/// Downloads [uri] to [dest] (resuming a partial `.part` with `Range`), with
/// a progress dialog. True when the whole file is there.
Future<bool> downloadWithDialog(NavigatorState nav, AutoEditClient client, Uri uri, File dest) async {
  if (await dest.exists()) return true; // downloaded before
  final part = File('${dest.path}.part');
  final progress = ValueNotifier<(int, int)>((0, 0));
  final error = ValueNotifier<String?>(null);
  var cancelled = false;
  if (!nav.mounted) return false;
  final dialog = showDialog<void>(
    context: nav.context,
    barrierDismissible: false,
    builder: (context) => _UploadDialog(
      title: 'Baixando do computador',
      name: dest.uri.pathSegments.last,
      progress: progress,
      error: error,
      onCancel: () {
        cancelled = true;
        Navigator.of(context).pop();
      },
    ),
  );
  for (var attempt = 1; attempt <= 6 && !cancelled; attempt++) {
    try {
      final have = await part.exists() ? await part.length() : 0;
      final req = http.Request('GET', uri);
      if (have > 0) req.headers['Range'] = 'bytes=$have-';
      final res = await client.transport.send(req);
      if (res.statusCode != 200 && res.statusCode != 206) {
        throw ApiException(res.statusCode, 'HTTP ${res.statusCode}');
      }
      final resumed = res.statusCode == 206;
      final total = (resumed ? have : 0) + (res.contentLength ?? 0);
      var got = resumed ? have : 0;
      final sink = part.openWrite(mode: resumed ? FileMode.append : FileMode.write);
      try {
        await for (final chunk in res.stream) {
          if (cancelled) break;
          sink.add(chunk);
          got += chunk.length;
          progress.value = (got, total);
        }
      } finally {
        await sink.close();
      }
      if (cancelled) break;
      await part.rename(dest.path);
      if (nav.mounted) nav.pop();
      return true;
    } on ApiException catch (e) {
      error.value = 'Não deu pra baixar: ${e.message}';
      break;
    } catch (_) {
      await Future<void>.delayed(Duration(seconds: attempt * 2)); // the Wi-Fi dropped: resume
    }
  }
  if (!cancelled && error.value == null) error.value = 'A conexão com o computador caiu. Tente de novo.';
  if (!cancelled) await dialog;
  return false;
}

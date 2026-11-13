import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:file_selector/file_selector.dart';

/// The OS dialogs the screens use. Behind an interface so the widget tests
/// can answer them.
abstract class Pickers {
  /// A folder, or null when the person cancels.
  Future<String?> folder({String? initial});

  /// The text of a JSON file the person picks, or null when they cancel.
  /// The content (not the path) goes to the engine: it may be on another machine.
  Future<String?> jsonFile({String? title});

  /// A video file's path (the dialog opens in [initial], the inbox), or null.
  Future<String?> video({String? initial});

  /// An image (the logo): its bytes and file name, or null.
  Future<(Uint8List, String)?> image();

  /// The text of a `.autoedit-style.json`, or null.
  Future<String?> styleFile();
}

class NativePickers implements Pickers {
  const NativePickers();

  @override
  Future<String?> folder({String? initial}) => getDirectoryPath(
    initialDirectory: initial != null && Directory(initial).existsSync() ? initial : null,
    confirmButtonText: 'Escolher',
  );

  @override
  Future<String?> jsonFile({String? title}) async {
    final file = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'JSON',
          extensions: ['json'],
          mimeTypes: ['application/json'],
          uniformTypeIdentifiers: ['public.json'],
        ),
      ],
      confirmButtonText: 'Escolher',
    );
    return file?.readAsString();
  }

  @override
  Future<String?> video({String? initial}) async {
    final file = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'Vídeos',
          extensions: ['mp4', 'mov', 'mkv', 'avi', 'webm', 'm4v', 'mts', 'm2ts'],
          uniformTypeIdentifiers: ['public.movie'],
        ),
      ],
      initialDirectory: initial != null && Directory(initial).existsSync() ? initial : null,
      confirmButtonText: 'Escolher',
    );
    return file?.path;
  }

  @override
  Future<(Uint8List, String)?> image() async {
    final file = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'Imagens',
          extensions: ['png', 'jpg', 'jpeg', 'webp', 'svg'],
          uniformTypeIdentifiers: ['public.image'],
        ),
      ],
      confirmButtonText: 'Escolher',
    );
    if (file == null) return null;
    return (await file.readAsBytes(), file.name);
  }

  @override
  Future<String?> styleFile() async {
    final file = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(label: 'Estilo do Auto-Edit', extensions: ['json'], uniformTypeIdentifiers: ['public.json']),
      ],
      confirmButtonText: 'Importar',
    );
    return file?.readAsString();
  }
}

/// What this app remembers about the person's choices (not the engine's
/// settings): a small JSON file next to the logs.
class AppPrefs {
  AppPrefs(this._file) : _data = _read(_file);

  /// In memory only (tests).
  AppPrefs.memory([Map<String, Object?>? data]) : _file = null, _data = {...?data};

  final File? _file;
  final Map<String, Object?> _data;

  static Map<String, Object?> _read(File? file) {
    try {
      final decoded = jsonDecode(file!.readAsStringSync());
      if (decoded is Map) return decoded.cast<String, Object?>();
    } catch (_) {
      // missing or broken: start over
    }
    return {};
  }

  /// "configurar depois" on the welcome screen: don't open it by itself again.
  bool get setupLater => _data['setup_later'] == true;
  set setupLater(bool value) => _set('setup_later', value);

  void _set(String key, Object? value) {
    _data[key] = value;
    final file = _file;
    if (file == null) return;
    try {
      file.parent.createSync(recursive: true);
      file.writeAsStringSync(jsonEncode(_data));
    } on FileSystemException {
      // not fatal: it is only remembered for this session
    }
  }
}

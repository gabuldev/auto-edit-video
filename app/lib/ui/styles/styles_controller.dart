import 'dart:async';
import 'dart:convert';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/foundation.dart';

import '../widgets.dart';

/// The four previews of a style, in the order the screen shows them.
const previewKinds = ['thumbnail', 'lower_third', 'cta', 'caption'];

/// A deep copy of tokens (they are plain JSON).
Map<String, Object?> cloneTokens(Map<String, Object?> t) => (jsonDecode(jsonEncode(t)) as Map).cast<String, Object?>();

/// `a.b.c` in nested tokens.
Object? getTok(Map<String, Object?> t, String path) {
  Object? o = t;
  for (final k in path.split('.')) {
    if (o is! Map) return null;
    o = o[k];
  }
  return o;
}

void setTok(Map<String, Object?> t, String path, Object? value) {
  final keys = path.split('.');
  var o = t;
  for (final k in keys.take(keys.length - 1)) {
    o = (o[k] ??= <String, Object?>{}) as Map<String, Object?>;
  }
  o[keys.last] = value;
}

/// Estilos (desktop/ui/js/styles.js): the brand, the gallery with previews
/// the engine renders on a frame of your own footage, and the editor. A style
/// is only tokens; the engine validates whatever is sent.
class StylesController extends ChangeNotifier {
  StylesController(
    this.client, {
    this.previewDebounce = const Duration(milliseconds: 350),
    this.brandDebounce = const Duration(milliseconds: 700),
  });

  final AutoEditClient client;
  final Duration previewDebounce;
  final Duration brandDebounce;
  AutoEditApi get _api => client.api;

  Styles? data;
  Settings? settings;
  String? error;

  /// A short line next to the brand ("salvo") or the detail ("exportado: …").
  String? brandNote;
  String? detailNote;

  String? selected;

  /// The tokens being edited (null: not editing).
  Map<String, Object?>? draft;
  String draftName = '';

  /// Two clicks to discard an edit or delete a style.
  bool discardArmed = false;
  bool deleteArmed = false;

  /// The brand fields as typed (saved after a pause).
  String name = '';
  String handle = '';

  /// Behind the logo in the video: a color of one's own, or null for the style's accent.
  String? logoBg;

  /// Bumped when the logo changes, so its image reloads.
  int logoVersion = 0;

  /// style id → its gallery thumbnail; kind → the detail's previews.
  final Map<String, Uint8List?> thumbs = {};
  final Map<String, Uint8List?> previews = {};
  bool previewing = false;

  int _seq = 0;
  Timer? _previewTimer;
  Timer? _brandTimer;
  Timer? _disarm;
  bool _disposed = false;
  bool _thumbsRunning = false;

  Style? styleOf(String? id) => data?.styles.where((s) => s.id == id).firstOrNull;
  Style? get current => styleOf(selected);
  Map<String, Object?>? get shown => draft ?? current?.tokens;
  bool get editing => draft != null;
  bool builtin(Style s) => s.builtin ?? false;

  Future<void> load({bool full = true}) async {
    try {
      final results = await Future.wait([_api.listStyles(), _api.getSettings()]);
      data = results[0] as Styles;
      final s = results[1] as Settings;
      if (settings == null) {
        name = (s.brand?['name'] as String?) ?? '';
        handle = (s.brand?['handle'] as String?) ?? '';
        logoBg = s.brand?['logo_bg'] as String?;
      }
      settings = s;
      error = null;
    } catch (e) {
      error = 'Não deu pra carregar os estilos: ${errorText(e)}';
      _notify();
      return;
    }
    if (styleOf(selected) == null) selected = data!.active;
    _notify();
    if (full) {
      unawaited(refreshPreviews());
      unawaited(loadThumbs());
    }
  }

  /// The gallery thumbnails one at a time (the engine renders each).
  Future<void> loadThumbs() async {
    if (_thumbsRunning) return;
    _thumbsRunning = true;
    try {
      for (final s in [...?data?.styles]) {
        if (thumbs.containsKey(s.id)) continue;
        try {
          thumbs[s.id] = await _api.previewStyle('thumbnail', PreviewStyleRequest(tokens: s.tokens));
        } catch (_) {
          thumbs[s.id] = null;
        }
        _notify();
        if (_disposed) return;
      }
    } finally {
      _thumbsRunning = false;
    }
  }

  Future<void> refreshPreviews({bool force = false}) async {
    final tokens = shown;
    if (tokens == null) return;
    final seq = ++_seq;
    if (force) thumbs.clear();
    previewing = true;
    _notify();
    for (final kind in previewKinds) {
      try {
        final png = await _api.previewStyle(kind, PreviewStyleRequest(tokens: tokens));
        if (seq != _seq || _disposed) return;
        previews[kind] = png;
        error = null;
      } catch (e) {
        if (seq != _seq) return;
        error = errorText(e);
      }
      _notify();
    }
    if (seq == _seq) previewing = false;
    _notify();
    if (force) unawaited(loadThumbs());
  }

  void select(String id) {
    if (id == selected) return;
    if (editing && !_armDiscard()) return;
    draft = null;
    selected = id;
    deleteArmed = false;
    detailNote = null;
    previews.clear();
    _notify();
    unawaited(refreshPreviews());
  }

  bool _armDiscard() {
    if (discardArmed) {
      discardArmed = false;
      return true;
    }
    discardArmed = true;
    _arm();
    return false;
  }

  void _arm() {
    _disarm?.cancel();
    _disarm = Timer(const Duration(milliseconds: 2500), () {
      discardArmed = false;
      deleteArmed = false;
      _notify();
    });
    _notify();
  }

  // ── Brand ──────────────────────────────────────────────────────────────

  void setName(String v) {
    name = v;
    _brandTimer?.cancel();
    _brandTimer = Timer(brandDebounce, saveBrand);
  }

  void setHandle(String v) {
    handle = v;
    _brandTimer?.cancel();
    _brandTimer = Timer(brandDebounce, saveBrand);
  }

  void setLogoBg(String? v) {
    logoBg = v;
    _notify();
    _brandTimer?.cancel();
    _brandTimer = Timer(brandDebounce, saveBrand);
  }

  Future<void> saveBrand() async {
    _brandTimer?.cancel();
    var h = handle.trim();
    if (h.isNotEmpty && !h.startsWith('@')) h = '@$h';
    final saved = settings?.brand;
    try {
      // the engine replaces the whole brand: send the logo back with it
      final raw = await client.transport.json(
        'PUT',
        '/api/settings',
        body: {
          'brand': {
            'name': name.trim().isEmpty ? null : name.trim(),
            'handle': h.isEmpty ? null : h,
            'logo': saved?['logo'],
            'logo_bg': logoBg,
          },
        },
      );
      settings = Settings.fromJson((raw as Map).cast<String, Object?>());
      brandNote = 'salvo';
      _notify();
      Timer(const Duration(milliseconds: 1500), () {
        brandNote = null;
        _notify();
      });
      await load(full: false);
      unawaited(refreshPreviews(force: true));
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  Future<void> uploadLogo(Uint8List bytes, String fileName) async {
    if (bytes.length > 5 * 1024 * 1024) {
      error = 'Imagem grande demais (máx. 5 MB).';
      _notify();
      return;
    }
    final ext = fileName.split('.').last.toLowerCase();
    final mime = switch (ext) {
      'jpg' || 'jpeg' => 'image/jpeg',
      'webp' => 'image/webp',
      'svg' => 'image/svg+xml',
      _ => 'image/png',
    };
    try {
      await _api.uploadLogo(UploadLogoRequest(data: 'data:$mime;base64,${base64Encode(bytes)}'));
      logoVersion++;
      settings = await _api.getSettings();
      await load(full: false);
      unawaited(refreshPreviews(force: true));
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  Future<void> deleteLogo() async {
    try {
      await _api.deleteLogo();
      logoVersion++;
      settings = await _api.getSettings();
      await load(full: false);
      unawaited(refreshPreviews(force: true));
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  Future<void> saveOverlaysDir(String? path) async {
    try {
      final raw = await client.transport.json('PUT', '/api/settings', body: {'overlays_dir': path});
      settings = Settings.fromJson((raw as Map).cast<String, Object?>());
      error = null;
    } catch (e) {
      error = errorText(e);
    }
    _notify();
  }

  // ── The selected style ────────────────────────────────────────────────

  Future<void> use() async {
    try {
      await _api.setActiveStyle(SetActiveStyleRequest(id: selected!));
      await load(full: false);
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  Future<void> export() async {
    try {
      final r = await _api.exportStyle(selected!);
      detailNote = 'exportado: ${r.path}';
    } catch (e) {
      error = errorText(e);
    }
    _notify();
  }

  Future<void> delete() async {
    if (!deleteArmed) {
      deleteArmed = true;
      _arm();
      return;
    }
    deleteArmed = false;
    try {
      await _api.deleteStyle(selected!);
      thumbs.remove(selected);
      selected = null;
      await load();
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  /// [text] is the file as read; the engine never overwrites (a copy with another name).
  Future<void> import(String text) async {
    final Object? file;
    try {
      file = jsonDecode(text);
    } on FormatException {
      error = 'Arquivo não é um estilo do Auto-Edit.';
      _notify();
      return;
    }
    if (file is! Map || file['tokens'] is! Map) {
      error = 'Arquivo não é um estilo do Auto-Edit.';
      _notify();
      return;
    }
    try {
      final saved = await client.transport.json('POST', '/api/styles/import', body: {'file': file});
      final id = (saved as Map)['id'] as String;
      await load(full: false);
      draft = null;
      selected = null;
      select(id);
      unawaited(loadThumbs());
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  // ── Editor ─────────────────────────────────────────────────────────────

  void startEditing() {
    final s = current;
    if (s == null) return;
    draft = cloneTokens(s.tokens);
    draftName = builtin(s) ? 'Meu ${s.name}' : s.name;
    _notify();
  }

  void cancelEditing() {
    if (!_armDiscard()) return;
    draft = null;
    previews.clear();
    _notify();
    unawaited(refreshPreviews());
  }

  void set(String path, Object? value, {Duration? debounce}) {
    final d = draft;
    if (d == null) return;
    setTok(d, path, value);
    changed(debounce: debounce);
  }

  /// The draft changed: the previews follow after a pause.
  void changed({Duration? debounce}) {
    _notify();
    _previewTimer?.cancel();
    _previewTimer = Timer(debounce ?? previewDebounce, refreshPreviews);
  }

  List<Map<String, Object?>> get steps => [
    for (final s in (getTok(draft ?? const {}, 'cta.steps') as List?) ?? const []) (s as Map).cast<String, Object?>(),
  ];

  void setStep(int i, String key, Object? value) {
    final list = (getTok(draft!, 'cta.steps') as List);
    (list[i] as Map)[key] = value;
    changed();
  }

  void addStep() {
    final list = (getTok(draft!, 'cta.steps') as List);
    if (list.length >= 3) return;
    list.add({'icon': 'comment', 'text': 'COMENTA AQUI!', 'color': null});
    changed();
  }

  void removeStep(int i) {
    (getTok(draft!, 'cta.steps') as List).removeAt(i);
    changed();
  }

  /// The thumbnail's own HTML layout; empty goes back to the default layout.
  void setHtml(String html) {
    final thumb = (draft!['thumbnail'] ??= <String, Object?>{}) as Map<String, Object?>;
    if (html.trim().isEmpty) {
      thumb.remove('html');
    } else {
      thumb['html'] = html;
    }
    changed(debounce: const Duration(milliseconds: 600));
  }

  Future<void> useLogoColors() async {
    try {
      final r = await _api.stylePalette();
      if (r.suggested.isEmpty) {
        error = 'Sem cor marcante no logo.';
        _notify();
        return;
      }
      final colors = (draft!['colors'] ??= <String, Object?>{}) as Map<String, Object?>;
      colors.addAll(r.suggested);
      changed();
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  Future<void> save({bool asNew = false}) async {
    final s = current;
    final d = draft;
    if (s == null || d == null) return;
    if (draftName.trim().isEmpty) {
      error = 'Dê um nome pro estilo.';
      _notify();
      return;
    }
    try {
      final saved = await _api.saveStyle(
        SaveStyleRequest(name: draftName.trim(), tokens: d, id: asNew || builtin(s) ? null : s.id, activate: true),
      );
      draft = null;
      thumbs.remove(saved.id);
      await load(full: false);
      selected = null;
      select(saved.id);
      unawaited(loadThumbs());
    } catch (e) {
      error = errorText(e);
      _notify();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _previewTimer?.cancel();
    _disarm?.cancel();
    // a pending brand save still goes through
    if (_brandTimer?.isActive ?? false) {
      _brandTimer!.cancel();
      unawaited(saveBrand());
    }
    super.dispose();
  }
}

/// Little formatters the Tauri screens use (shell.js, library.js, recordings.js).
library;

/// 1536 → "1.5 KB", like shell.js `humanSize`.
String humanSize(int? bytes) {
  if (bytes == null) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  var n = bytes.toDouble();
  var i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return '${n < 10 && i > 0 ? n.toStringAsFixed(1) : n.round()} ${units[i]}';
}

/// 754.2 → "12:34", 3725 → "1:02:05".
String duration(double? seconds) {
  if (seconds == null) return '—';
  final s = seconds.round();
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = (s % 60).toString().padLeft(2, '0');
  return h > 0 ? '$h:${m.toString().padLeft(2, '0')}:$sec' : '$m:$sec';
}

/// An ISO date as pt-BR short date + time ("12/11/2026 21:30"), local time.
String when(String? iso) {
  final d = iso == null ? null : DateTime.tryParse(iso)?.toLocal();
  if (d == null) return '';
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(d.day)}/${two(d.month)}/${d.year} ${two(d.hour)}:${two(d.minute)}';
}

const _accents = {
  'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a', //
  'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
  'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
  'ó': 'o', 'ò': 'o', 'ô': 'o', 'õ': 'o', 'ö': 'o',
  'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
  'ç': 'c', 'ñ': 'n',
};

/// Lowercase without accents: the search ignores both.
String fold(String s) => s.toLowerCase().split('').map((c) => _accents[c] ?? c).join();

/// Every word of [query] is somewhere in [fields] (case- and accent-insensitive).
bool matchesQuery(String query, Iterable<String?> fields) {
  final words = fold(query).split(RegExp(r'\s+')).where((w) => w.isNotEmpty);
  if (words.isEmpty) return true;
  final hay = fold(fields.whereType<String>().join(' '));
  return words.every(hay.contains);
}

/// The last part of a path, either separator.
String baseName(String? path) =>
    path == null ? '' : path.split(RegExp(r'[\\/]')).where((p) => p.isNotEmpty).lastOrNull ?? path;

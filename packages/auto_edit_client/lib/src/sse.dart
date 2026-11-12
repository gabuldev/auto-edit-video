import 'dart:async';
import 'dart:convert';

/// The `data` of each event in a Server-Sent Events byte stream.
///
/// Follows the EventSource format: `data:` lines (several join with `\n`),
/// a blank line dispatches, `:` lines are comments, other fields (`event`,
/// `id`, `retry`) are ignored because the engine doesn't send them. A last
/// event without the blank line is dropped, like a browser does.
Stream<String> parseSse(Stream<List<int>> bytes) async* {
  final data = <String>[];
  await for (final line in bytes.transform(utf8.decoder).transform(const LineSplitter())) {
    if (line.isEmpty) {
      if (data.isNotEmpty) {
        yield data.join('\n');
        data.clear();
      }
      continue;
    }
    if (line.startsWith(':')) continue;
    final colon = line.indexOf(':');
    final name = colon < 0 ? line : line.substring(0, colon);
    var value = colon < 0 ? '' : line.substring(colon + 1);
    if (value.startsWith(' ')) value = value.substring(1);
    if (name == 'data') data.add(value);
  }
}

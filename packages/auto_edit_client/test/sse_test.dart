import 'dart:convert';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:test/test.dart';

Stream<List<int>> chunks(List<String> parts) => Stream.fromIterable(parts.map(utf8.encode));

void main() {
  test('one event per blank line, data lines joined', () async {
    final out = await parseSse(chunks(['data: a\n\n', 'data: b\ndata: c\n\n'])).toList();
    expect(out, ['a', 'b\nc']);
  });

  test('events split across chunks and CRLF', () async {
    final out = await parseSse(chunks(['da', 'ta: {"type":', ' "log"}\r', '\n\r\n'])).toList();
    expect(out, ['{"type": "log"}']);
  });

  test('comments and other fields are ignored', () async {
    final out = await parseSse(chunks([': ping\n\n', 'event: x\nid: 3\ndata:no-space\n\n'])).toList();
    expect(out, ['no-space']);
  });

  test('a trailing event without the blank line is dropped', () async {
    expect(await parseSse(chunks(['data: a\n\ndata: b'])).toList(), ['a']);
  });

  test('accented text decodes across chunks', () async {
    final bytes = utf8.encode('data: edição\n\n');
    final out = await parseSse(Stream.fromIterable([bytes.sublist(0, 9), bytes.sublist(9)])).toList();
    expect(out, ['edição']);
  });
}

import 'dart:async';
import 'dart:convert';

import 'package:dzmm_mobile/api/sse_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test(
    'parses multiline data, ids, comments, and UTF-8 chunk boundaries',
    () async {
      final encoded = utf8.encode(
        ': heartbeat\r\nid: 4\r\nevent: narrative\r\ndata: 第一行\r\ndata: 第二行🙂\r\n\r\n',
      );
      final emoji = encoded.indexOf(0xF0);
      final chunks = [
        encoded.sublist(0, emoji + 1),
        encoded.sublist(emoji + 1, emoji + 3),
        encoded.sublist(emoji + 3),
      ];

      final events = await const SseParser()
          .parse(Stream<List<int>>.fromIterable(chunks))
          .toList();

      expect(events, hasLength(1));
      expect(events.single.id, 4);
      expect(events.single.event, 'narrative');
      expect(events.single.data, '第一行\n第二行🙂');
    },
  );

  test('dispatches a final event without a trailing blank line', () async {
    final events = await const SseParser()
        .parse(Stream.value(utf8.encode('event: done\ndata: {}')))
        .toList();

    expect(events.single.event, 'done');
  });

  test('sends auth and Last-Event-ID on reconnect', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('id: 8\nevent: done\ndata: {}\n\n', 200);
    });
    final sse = HttpSseClient(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      deviceToken: 'device-secret',
      client: client,
    );

    final events = await sse
        .connect('/sessions/1/turn-runs/run/events', lastEventId: 7)
        .toList();

    expect(events.single.id, 8);
    expect(captured.headers['authorization'], 'Bearer device-secret');
    expect(captured.headers['Last-Event-ID'], '7');
  });
}

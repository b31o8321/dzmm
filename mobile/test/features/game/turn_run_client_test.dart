import 'dart:async';

import 'package:dzmm_mobile/api/api_error.dart';
import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/api/sse_client.dart';
import 'package:dzmm_mobile/features/game/turn_run_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:uuid/uuid.dart';

void main() {
  test('keeps request id and event cursor across transient retries', () async {
    final transport = ReconnectingTransport();
    final seen = <int?>[];
    final client = TurnRunClient(
      transport: transport,
      uuid: const Uuid(),
      delay: (_) async {},
    );

    final result = await client.run(
      7,
      '推开门',
      onEvent: (event) => seen.add(event.id),
    );

    expect(result.status, TurnRunStatus.completed);
    expect(transport.createRequestIds, hasLength(2));
    expect(transport.createRequestIds.toSet(), hasLength(1));
    expect(transport.eventCursors, [0, 1]);
    expect(seen, [1, 2]);
  });

  test('event gap requires hydration and never resubmits the action', () async {
    final transport = GapTransport();
    final client = TurnRunClient(transport: transport, delay: (_) async {});

    await expectLater(
      client.run(9, '观察', onEvent: (_) {}),
      throwsA(isA<TurnRehydrateRequired>()),
    );
    expect(transport.createCalls, 1);
  });

  test(
    'resume checks persisted status before opening another stream',
    () async {
      final transport = CompletedTransport();
      final client = TurnRunClient(transport: transport);

      final result = await client.resume(2, 'run-done', onEvent: (_) {});

      expect(result.status, TurnRunStatus.completed);
      expect(transport.eventCalls, 0);
    },
  );
}

TurnRunRecord record(String status) => TurnRunRecord.fromJson({
  'run_id': 'run-1',
  'request_id': 'request-1',
  'status': status,
  'error_code': null,
  'error_message': null,
});

class ReconnectingTransport implements TurnRunTransport {
  final createRequestIds = <String>[];
  final eventCursors = <int>[];
  var reads = 0;

  @override
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  }) async {
    createRequestIds.add(requestId);
    if (createRequestIds.length == 1) {
      throw const ApiError(code: 'offline', message: 'offline');
    }
    return record('running');
  }

  @override
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) async {
    reads += 1;
    return record(reads >= 3 ? 'completed' : 'running');
  }

  @override
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  }) async* {
    eventCursors.add(lastEventId);
    if (eventCursors.length == 1) {
      yield const SseEvent(id: 1, event: 'narrative', data: '{"text":"A"}');
      throw const ApiError(code: 'offline', message: 'offline');
    }
    yield const SseEvent(id: 2, event: 'done', data: '{}');
  }
}

class GapTransport implements TurnRunTransport {
  var createCalls = 0;

  @override
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  }) async {
    createCalls += 1;
    return record('running');
  }

  @override
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) async => record('running');

  @override
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  }) => Stream.error(const ApiError(code: 'event_gap', message: 'rehydrate'));
}

class CompletedTransport implements TurnRunTransport {
  var eventCalls = 0;

  @override
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  }) async => record('completed');

  @override
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) async => record('completed');

  @override
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  }) {
    eventCalls += 1;
    return const Stream.empty();
  }
}

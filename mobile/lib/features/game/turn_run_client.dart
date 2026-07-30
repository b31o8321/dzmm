import 'dart:async';

import 'package:uuid/uuid.dart';

import '../../api/api_error.dart';
import '../../api/dzmm_api.dart';
import '../../api/sse_client.dart';

enum TurnRunStatus { running, completed, failed, interrupted }

class TurnRunRecord {
  const TurnRunRecord({
    required this.runId,
    required this.requestId,
    required this.status,
    this.errorCode,
    this.errorMessage,
  });

  final String runId;
  final String requestId;
  final TurnRunStatus status;
  final String? errorCode;
  final String? errorMessage;

  factory TurnRunRecord.fromJson(Map<String, Object?> json) {
    final runId = json['run_id'];
    final requestId = json['request_id'];
    final rawStatus = json['status'];
    if (runId is! String || requestId is! String || rawStatus is! String) {
      throw const FormatException('Invalid turn run response');
    }
    return TurnRunRecord(
      runId: runId,
      requestId: requestId,
      status: TurnRunStatus.values.firstWhere(
        (status) => status.name == rawStatus,
        orElse: () => throw const FormatException('Invalid turn run status'),
      ),
      errorCode: json['error_code'] as String?,
      errorMessage: json['error_message'] as String?,
    );
  }
}

abstract interface class TurnRunTransport {
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  });
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  });
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  });
}

class DzmmTurnRunTransport implements TurnRunTransport {
  const DzmmTurnRunTransport({required this.api, required this.sse});

  final DzmmApi api;
  final HttpSseClient sse;

  @override
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  }) async {
    final value = await api.postJson('/sessions/$sessionId/turn-runs', {
      'request_id': requestId,
      'action': action,
    }, cancellationToken: cancellationToken);
    return TurnRunRecord.fromJson(_object(value));
  }

  @override
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) async {
    final value = await api.getJson(
      '/sessions/$sessionId/turn-runs/${Uri.encodeComponent(runId)}',
      cancellationToken: cancellationToken,
    );
    return TurnRunRecord.fromJson(_object(value));
  }

  @override
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  }) => sse.connect(
    '/sessions/$sessionId/turn-runs/${Uri.encodeComponent(runId)}/events',
    lastEventId: lastEventId,
    cancellationToken: cancellationToken,
  );

  static Map<String, Object?> _object(Object? value) {
    if (value is! Map) throw const FormatException('Expected turn run object');
    return value.cast<String, Object?>();
  }
}

class TurnRehydrateRequired implements Exception {
  const TurnRehydrateRequired();
}

class TurnRunClient {
  factory TurnRunClient({
    required TurnRunTransport transport,
    Future<void> Function(Duration)? delay,
    Uuid? uuid,
  }) => TurnRunClient._(
    transport,
    delay ?? Future<void>.delayed,
    uuid ?? const Uuid(),
  );

  TurnRunClient._(this._transport, this._delay, this._uuid);

  final TurnRunTransport _transport;
  final Future<void> Function(Duration) _delay;
  final Uuid _uuid;

  Future<TurnRunRecord> check(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) => _transport.read(sessionId, runId, cancellationToken: cancellationToken);

  Future<TurnRunRecord> run(
    int sessionId,
    String action, {
    required void Function(SseEvent event) onEvent,
    void Function(TurnRunRecord run)? onStarted,
    CancellationToken? cancellationToken,
  }) async {
    final requestId = _uuid.v4();
    final run = await _retry(
      () => _transport.create(
        sessionId,
        requestId,
        action,
        cancellationToken: cancellationToken,
      ),
      cancellationToken,
    );
    onStarted?.call(run);
    return resume(
      sessionId,
      run.runId,
      onEvent: onEvent,
      cancellationToken: cancellationToken,
    );
  }

  Future<TurnRunRecord> resume(
    int sessionId,
    String runId, {
    required void Function(SseEvent event) onEvent,
    CancellationToken? cancellationToken,
  }) async {
    var cursor = 0;
    var attempt = 0;
    while (true) {
      _throwIfCancelled(cancellationToken);
      final status = await _retry(
        () => _transport.read(
          sessionId,
          runId,
          cancellationToken: cancellationToken,
        ),
        cancellationToken,
      );
      if (status.status != TurnRunStatus.running) return _finish(status);
      try {
        await for (final event in _transport.events(
          sessionId,
          runId,
          lastEventId: cursor,
          cancellationToken: cancellationToken,
        )) {
          if (event.id != null && event.id! > cursor) cursor = event.id!;
          onEvent(event);
          attempt = 0;
        }
      } on ApiError catch (error) {
        if (error.code == 'event_gap') throw const TurnRehydrateRequired();
        if (!_transient(error)) rethrow;
        await _backoff(attempt++, cancellationToken);
      }
    }
  }

  Future<T> _retry<T>(
    Future<T> Function() operation,
    CancellationToken? cancellationToken,
  ) async {
    var attempt = 0;
    while (true) {
      _throwIfCancelled(cancellationToken);
      try {
        return await operation();
      } on ApiError catch (error) {
        if (!_transient(error)) rethrow;
        await _backoff(attempt++, cancellationToken);
      }
    }
  }

  Future<void> _backoff(
    int attempt,
    CancellationToken? cancellationToken,
  ) async {
    final seconds = (1 << attempt.clamp(0, 5)).clamp(1, 30);
    await Future.any([
      _delay(Duration(seconds: seconds)),
      if (cancellationToken != null) cancellationToken.whenCancelled,
    ]);
    _throwIfCancelled(cancellationToken);
  }

  static bool _transient(ApiError error) =>
      error.code == 'offline' || error.code == 'timeout';

  static TurnRunRecord _finish(TurnRunRecord record) {
    if (record.status == TurnRunStatus.completed) return record;
    throw ApiError(
      code: record.errorCode ?? 'turn_${record.status.name}',
      message: record.errorMessage ?? 'The turn did not complete',
    );
  }

  static void _throwIfCancelled(CancellationToken? token) {
    if (token?.isCancelled == true) {
      throw const ApiError(code: 'cancelled', message: 'Request cancelled');
    }
  }
}

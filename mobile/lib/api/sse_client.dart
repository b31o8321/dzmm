import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_error.dart';
import 'dzmm_api.dart';

class SseEvent {
  const SseEvent({required this.event, required this.data, this.id});

  final int? id;
  final String event;
  final String data;
}

class SseParser {
  const SseParser();

  Stream<SseEvent> parse(Stream<List<int>> bytes) async* {
    int? id;
    var event = 'message';
    final data = <String>[];

    await for (final line
        in bytes.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.isEmpty) {
        if (data.isNotEmpty) {
          yield SseEvent(id: id, event: event, data: data.join('\n'));
        }
        id = null;
        event = 'message';
        data.clear();
        continue;
      }
      if (line.startsWith(':')) continue;
      final separator = line.indexOf(':');
      final field = separator < 0 ? line : line.substring(0, separator);
      var value = separator < 0 ? '' : line.substring(separator + 1);
      if (value.startsWith(' ')) value = value.substring(1);
      switch (field) {
        case 'id':
          id = int.tryParse(value);
        case 'event':
          event = value.isEmpty ? 'message' : value;
        case 'data':
          data.add(value);
      }
    }
    if (data.isNotEmpty) {
      yield SseEvent(id: id, event: event, data: data.join('\n'));
    }
  }
}

class HttpSseClient {
  factory HttpSseClient({
    required Uri baseUri,
    required String deviceToken,
    http.Client? client,
    Duration connectTimeout = const Duration(seconds: 10),
  }) => HttpSseClient._(
    baseUri.replace(path: '/', query: null, fragment: null),
    deviceToken,
    client,
    connectTimeout,
  );

  HttpSseClient._(
    this._baseUri,
    this._deviceToken,
    this._client,
    this.connectTimeout,
  );

  final Uri _baseUri;
  final String _deviceToken;
  final http.Client? _client;
  final Duration connectTimeout;

  Stream<SseEvent> connect(
    String path, {
    int lastEventId = 0,
    CancellationToken? cancellationToken,
  }) async* {
    final client = _client ?? http.Client();
    final ownsClient = _client == null;
    final connectAbort = Completer<void>();
    final connectTimer = Timer(connectTimeout, () => connectAbort.complete());
    final abortTrigger = cancellationToken == null
        ? connectAbort.future
        : Future.any([cancellationToken.whenCancelled, connectAbort.future]);
    final request =
        http.AbortableRequest(
            'GET',
            _baseUri.resolve(path),
            abortTrigger: abortTrigger,
          )
          ..headers['accept'] = 'text/event-stream'
          ..headers['authorization'] = 'Bearer $_deviceToken';
    if (lastEventId > 0) {
      request.headers['Last-Event-ID'] = '$lastEventId';
    }

    try {
      final response = await client.send(request).timeout(connectTimeout);
      connectTimer.cancel();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = await response.stream.toBytes();
        throw _responseError(response.statusCode, body);
      }
      yield* const SseParser().parse(response.stream);
    } on ApiError {
      rethrow;
    } on http.RequestAbortedException {
      if (cancellationToken?.isCancelled == true) {
        throw const ApiError(code: 'cancelled', message: 'Request cancelled');
      }
      throw const ApiError(
        code: 'timeout',
        message: 'The host did not respond in time',
      );
    } on TimeoutException {
      throw const ApiError(
        code: 'timeout',
        message: 'The host did not respond in time',
      );
    } on http.ClientException {
      throw const ApiError(code: 'offline', message: 'The host is unreachable');
    } finally {
      connectTimer.cancel();
      if (ownsClient) client.close();
    }
  }

  static ApiError _responseError(int statusCode, List<int> bytes) {
    try {
      final value = jsonDecode(utf8.decode(bytes));
      if (value is Map) {
        final payload = value.cast<String, Object?>();
        return ApiError(
          code: payload['code'] is String
              ? payload['code']! as String
              : 'http_error',
          message: payload['message'] is String
              ? payload['message']! as String
              : 'The host rejected the event stream',
          statusCode: statusCode,
        );
      }
    } on Object {
      // Fall through to a structured generic error.
    }
    return ApiError(
      code: 'http_error',
      message: 'The host rejected the event stream',
      statusCode: statusCode,
    );
  }
}

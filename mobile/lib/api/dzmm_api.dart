import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_error.dart';

class CancellationToken {
  final _completer = Completer<void>();

  Future<void> get whenCancelled => _completer.future;
  bool get isCancelled => _completer.isCompleted;

  void cancel() {
    if (!_completer.isCompleted) _completer.complete();
  }
}

class HealthInfo {
  const HealthInfo({
    required this.version,
    required this.apiVersion,
    required this.serverId,
    required this.remoteAccess,
    required this.capabilities,
  });

  final String version;
  final int apiVersion;
  final String serverId;
  final bool remoteAccess;
  final Set<String> capabilities;

  factory HealthInfo.fromJson(Map<String, Object?> json) {
    final ok = json['ok'];
    final version = json['version'];
    final apiVersion = json['api_version'];
    final serverId = json['server_id'];
    final remoteAccess = json['remote_access'];
    final capabilities = json['capabilities'];
    if (ok != true ||
        version is! String ||
        apiVersion is! int ||
        serverId is! String ||
        serverId.isEmpty ||
        remoteAccess is! bool ||
        capabilities is! List ||
        !capabilities.every((item) => item is String)) {
      throw const ApiError(
        code: 'invalid_response',
        message: 'The host did not return a compatible dzmm health response',
      );
    }
    return HealthInfo(
      version: version,
      apiVersion: apiVersion,
      serverId: serverId,
      remoteAccess: remoteAccess,
      capabilities: capabilities.cast<String>().toSet(),
    );
  }
}

abstract interface class DzmmClient {
  Future<HealthInfo> health({CancellationToken? cancellationToken});
  Future<Object?> getJson(
    String path, {
    Map<String, String>? headers,
    Map<String, String>? query,
    bool authenticated = true,
    CancellationToken? cancellationToken,
  });
  void close();
}

class DzmmApi implements DzmmClient {
  DzmmApi({
    required Uri baseUri,
    String? deviceToken,
    http.Client? client,
    Duration timeout = const Duration(seconds: 10),
  }) : _baseUri = _normalizeBaseUri(baseUri),
       _authorization = deviceToken,
       _client = client ?? http.Client(),
       _requestTimeout = timeout;

  final Uri _baseUri;
  final String? _authorization;
  final http.Client _client;
  final Duration _requestTimeout;

  @override
  Future<HealthInfo> health({CancellationToken? cancellationToken}) async {
    final value = await _requestJson(
      'GET',
      '/health',
      authenticated: false,
      cancellationToken: cancellationToken,
    );
    if (value is! Map) {
      throw const ApiError(
        code: 'invalid_response',
        message: 'The health response was not an object',
      );
    }
    return HealthInfo.fromJson(value.cast<String, Object?>());
  }

  @override
  Future<Object?> getJson(
    String path, {
    Map<String, String>? headers,
    Map<String, String>? query,
    bool authenticated = true,
    CancellationToken? cancellationToken,
  }) => _requestJson(
    'GET',
    path,
    headers: headers,
    query: query,
    authenticated: authenticated,
    cancellationToken: cancellationToken,
  );

  Future<Object?> postJson(
    String path,
    Object body, {
    bool authenticated = true,
    Map<String, String>? headers,
    CancellationToken? cancellationToken,
  }) => _requestJson(
    'POST',
    path,
    body: body,
    headers: headers,
    authenticated: authenticated,
    cancellationToken: cancellationToken,
  );

  Future<Object?> _requestJson(
    String method,
    String path, {
    Object? body,
    Map<String, String>? headers,
    Map<String, String>? query,
    bool authenticated = true,
    CancellationToken? cancellationToken,
  }) async {
    if (!path.startsWith('/') || path.contains('://')) {
      throw ArgumentError.value(path, 'path', 'Expected an absolute API path');
    }
    final timeoutTrigger = Future<void>.delayed(_requestTimeout);
    final abortTrigger = cancellationToken == null
        ? timeoutTrigger
        : Future.any([cancellationToken.whenCancelled, timeoutTrigger]);
    final request = http.AbortableRequest(
      method,
      _baseUri.resolve(path).replace(queryParameters: query),
      abortTrigger: abortTrigger,
    );
    request.headers['accept'] = 'application/json';
    if (headers != null) request.headers.addAll(headers);
    if (authenticated && _authorization != null && _authorization.isNotEmpty) {
      request.headers['authorization'] = 'Bearer $_authorization';
    }
    if (body != null) {
      request.headers['content-type'] = 'application/json';
      request.body = jsonEncode(body);
    }

    try {
      final streamed = await _client.send(request).timeout(_requestTimeout);
      final response = await http.Response.fromStream(
        streamed,
      ).timeout(_requestTimeout);
      final decoded = _decodeJson(response.bodyBytes);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw _responseError(response.statusCode, decoded);
      }
      return decoded;
    } on ApiError {
      rethrow;
    } on http.RequestAbortedException {
      if (cancellationToken?.isCancelled != true) {
        throw const ApiError(
          code: 'timeout',
          message: 'The host did not respond in time',
        );
      }
      throw const ApiError(code: 'cancelled', message: 'Request cancelled');
    } on TimeoutException {
      throw const ApiError(
        code: 'timeout',
        message: 'The host did not respond in time',
      );
    } on http.ClientException {
      throw const ApiError(code: 'offline', message: 'The host is unreachable');
    } on FormatException {
      throw const ApiError(
        code: 'invalid_response',
        message: 'The host returned invalid JSON',
      );
    }
  }

  static Object? _decodeJson(List<int> bytes) {
    if (bytes.isEmpty) return null;
    return jsonDecode(utf8.decode(bytes));
  }

  static ApiError _responseError(int statusCode, Object? decoded) {
    Map<String, Object?>? payload;
    if (decoded is Map) {
      payload = decoded.cast<String, Object?>();
      final detail = payload['detail'];
      if (detail is Map) payload = detail.cast<String, Object?>();
    }
    final code = payload?['code'];
    final message = payload?['message'];
    return ApiError(
      code: code is String ? code : 'http_error',
      message: message is String ? message : 'The host rejected the request',
      statusCode: statusCode,
    );
  }

  static Uri _normalizeBaseUri(Uri uri) {
    if ((uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw ArgumentError.value(uri, 'baseUri', 'Expected an HTTP host URL');
    }
    return uri.replace(path: '/', query: null, fragment: null);
  }

  @override
  void close() => _client.close();

  @override
  String toString() => 'DzmmApi(baseUri: $_baseUri)';
}

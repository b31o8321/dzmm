import 'dart:convert';

import 'package:http/http.dart' as http;

class HostApiError implements Exception {
  const HostApiError(this.statusCode, this.detail);

  final int statusCode;
  final String detail;

  bool get isUnauthorized => statusCode == 401;
  bool get isConflict => statusCode == 409;

  @override
  String toString() => detail;
}

class PairingRequest {
  const PairingRequest({required this.requestId, required this.approvalCode});

  final String requestId;
  final String approvalCode;

  factory PairingRequest.fromJson(Map<String, dynamic> json) => PairingRequest(
    requestId: json['request_id'] as String,
    approvalCode: json['approval_code'] as String,
  );
}

class MobileCredential {
  const MobileCredential({required this.deviceId, required this.accessToken});

  final String deviceId;
  final String accessToken;

  factory MobileCredential.fromJson(Map<String, dynamic> json) =>
      MobileCredential(
        deviceId: json['device_id'] as String,
        accessToken: json['access_token'] as String,
      );
}

class RunSnapshot {
  const RunSnapshot(this.value);

  final Map<String, dynamic> value;

  String get runId => value['run_id'] as String;
  Map<String, dynamic> get state =>
      Map<String, dynamic>.from(value['state'] as Map);
  List<Map<String, dynamic>> get turns => (value['turns'] as List)
      .map((turn) => Map<String, dynamic>.from(turn as Map))
      .toList(growable: false);
  List<Map<String, dynamic>> get availableChoices =>
      (value['available_choices'] as List)
          .map((choice) => Map<String, dynamic>.from(choice as Map))
          .toList(growable: false);
}

class MobileApi {
  MobileApi({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Future<PairingRequest> requestPairing({
    required String host,
    required String deviceName,
  }) async {
    final response = await _client.post(
      _uri(host, '/api/v2/mobile/pairing-requests'),
      headers: const {'content-type': 'application/json'},
      body: jsonEncode({'device_name': deviceName}),
    );
    return PairingRequest.fromJson(_map(response));
  }

  Future<MobileCredential> completePairing({
    required String host,
    required PairingRequest request,
  }) async {
    final response = await _client.post(
      _uri(
        host,
        '/api/v2/mobile/pairing-requests/${request.requestId}:complete',
      ),
      headers: const {'content-type': 'application/json'},
      body: jsonEncode({'approval_code': request.approvalCode}),
    );
    return MobileCredential.fromJson(_map(response));
  }

  Future<RunSnapshot> loadRun({
    required String host,
    required String token,
    required String runId,
  }) async {
    final response = await _client.get(
      _uri(host, '/api/v2/mobile/runs/$runId'),
      headers: _auth(token),
    );
    return RunSnapshot(_map(response));
  }

  Future<RunSnapshot> choose({
    required String host,
    required String token,
    required String runId,
    required int expectedRevision,
    required String choiceId,
    required String playerInput,
    required String requestId,
  }) async {
    final response = await _client.post(
      _uri(host, '/api/v2/mobile/runs/$runId/choices'),
      headers: {'content-type': 'application/json', ..._auth(token)},
      body: jsonEncode({
        'request_id': requestId,
        'expected_revision': expectedRevision,
        'choice_id': choiceId,
        'player_input': playerInput,
      }),
    );
    return RunSnapshot(_map(response));
  }

  Map<String, String> _auth(String token) => {'authorization': 'Bearer $token'};

  Uri _uri(String host, String path) {
    final normalized = host.trim().replaceFirst(RegExp(r'/$'), '');
    final uri = Uri.tryParse(normalized);
    if (uri == null ||
        !uri.hasAuthority ||
        (uri.scheme != 'http' && uri.scheme != 'https')) {
      throw const HostApiError(0, 'Mac Host 地址必须是 http:// 或 https:// 地址。');
    }
    return Uri.parse('$normalized$path');
  }

  Map<String, dynamic> _map(http.Response response) {
    dynamic decoded;
    try {
      decoded = jsonDecode(response.body);
    } on FormatException {
      throw HostApiError(response.statusCode, 'Mac Host 返回了无法识别的响应。');
    }
    if (response.statusCode >= 400) {
      final detail = decoded is Map ? decoded['detail']?.toString() : null;
      throw HostApiError(
        response.statusCode,
        detail ?? 'Host 请求失败（${response.statusCode}）。',
      );
    }
    if (decoded is! Map) {
      throw HostApiError(response.statusCode, 'Mac Host 返回了无法识别的响应。');
    }
    return Map<String, dynamic>.from(decoded);
  }
}

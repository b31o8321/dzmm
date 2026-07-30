import 'dart:convert';

import 'package:dzmm_mobile/api/api_error.dart';
import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('validates dzmm health schema', () async {
    final api = DzmmApi(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      client: MockClient(
        (_) async => http.Response(jsonEncode(_health()), 200),
      ),
    );

    final health = await api.health();

    expect(health.serverId, 'server-1');
    expect(health.capabilities, contains('session_hydration'));
  });

  test('maps nested structured errors and never puts token in URL', () async {
    late http.Request captured;
    final api = DzmmApi(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      deviceToken: 'secret-token',
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'detail': {'code': 'session_not_found', 'message': 'missing'},
          }),
          404,
        );
      }),
    );

    await expectLater(
      api.getJson('/sessions/9'),
      throwsA(
        isA<ApiError>()
            .having((error) => error.code, 'code', 'session_not_found')
            .having((error) => error.statusCode, 'status', 404),
      ),
    );
    expect(captured.url.toString(), isNot(contains('secret-token')));
    expect(captured.headers['authorization'], 'Bearer secret-token');
    expect(api.toString(), isNot(contains('secret-token')));
  });

  test('rejects an HTTP 200 response that is not dzmm health', () async {
    final api = DzmmApi(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      client: MockClient((_) async => http.Response('{"ok":true}', 200)),
    );

    await expectLater(
      api.health(),
      throwsA(
        isA<ApiError>().having(
          (error) => error.code,
          'code',
          'invalid_response',
        ),
      ),
    );
  });

  test('keeps pairing secret in a header instead of the route URL', () async {
    late http.Request captured;
    final api = DzmmApi(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      deviceToken: 'device-token-not-used',
      client: MockClient((request) async {
        captured = request;
        return http.Response('{}', 200);
      }),
    );

    await api.getJson(
      '/remote/pair/requests/request-1',
      headers: const {'X-DZMM-Pair-Secret': 'poll-secret'},
      query: const {'wait_seconds': '25'},
      authenticated: false,
    );

    expect(captured.url.queryParameters['wait_seconds'], '25');
    expect(captured.url.toString(), isNot(contains('poll-secret')));
    expect(captured.headers['x-dzmm-pair-secret'], 'poll-secret');
    expect(captured.headers, isNot(contains('authorization')));
  });

  test('supports explicit request cancellation', () async {
    final token = CancellationToken();
    final api = DzmmApi(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      client: AbortAwareClient(),
    );

    final request = api.health(cancellationToken: token);
    token.cancel();

    await expectLater(
      request,
      throwsA(
        isA<ApiError>().having((error) => error.code, 'code', 'cancelled'),
      ),
    );
  });

  test('aborts a request when the timeout expires', () async {
    final api = DzmmApi(
      baseUri: Uri.parse('http://192.168.1.8:8765'),
      client: AbortAwareClient(),
      timeout: const Duration(milliseconds: 1),
    );

    await expectLater(
      api.health(),
      throwsA(isA<ApiError>().having((error) => error.code, 'code', 'timeout')),
    );
  });
}

Map<String, Object?> _health({
  String serverId = 'server-1',
  int apiVersion = 1,
  bool remoteAccess = true,
}) => {
  'ok': true,
  'status': 'ok',
  'version': '0.16.0',
  'server_id': serverId,
  'api_version': apiVersion,
  'remote_access': remoteAccess,
  'capabilities': ['pair_request', 'session_hydration'],
};

class AbortAwareClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final abortable = request as http.AbortableRequest;
    await abortable.abortTrigger;
    throw http.RequestAbortedException(request.url);
  }
}

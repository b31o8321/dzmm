import 'dart:convert';

import 'package:dzmm_next_mobile/mobile_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('submits a server-planned choice with the expected revision', () async {
    late http.Request captured;
    final api = MobileApi(
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'run_id': 'run-1',
            'state': {'revision': 2},
            'turns': [],
            'available_choices': [],
          }),
          201,
        );
      }),
    );

    final run = await api.choose(
      host: 'http://192.168.31.241:8765',
      token: 'secret-token',
      runId: 'run-1',
      expectedRevision: 1,
      choiceId: 'rescue-lan',
      playerInput: '救岚',
      requestId: 'android-choice-1',
    );

    expect(captured.url.path, '/api/v2/mobile/runs/run-1/choices');
    expect(captured.headers['authorization'], 'Bearer secret-token');
    expect(jsonDecode(captured.body), {
      'request_id': 'android-choice-1',
      'expected_revision': 1,
      'choice_id': 'rescue-lan',
      'player_input': '救岚',
    });
    expect(run.state['revision'], 2);
  });

  test('surfaces a Host conflict without accepting stale state', () async {
    final api = MobileApi(
      client: MockClient(
        (_) async =>
            http.Response(jsonEncode({'detail': 'revision conflict'}), 409),
      ),
    );

    expect(
      () => api.loadRun(
        host: 'http://192.168.31.241:8765',
        token: 'token',
        runId: 'run-1',
      ),
      throwsA(
        isA<HostApiError>().having(
          (error) => error.isConflict,
          'isConflict',
          isTrue,
        ),
      ),
    );
  });
}

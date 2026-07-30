import 'dart:convert';

import 'package:dzmm_mobile/features/pairing/qr_scan_page.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('parses the versioned dzmm QR payload and redacts its claim', () {
    final payload = DzmmQrPayload.parse(
      jsonEncode({
        'type': 'dzmm_pair',
        'version': 1,
        'server_id': 'server-1',
        'api_version': 1,
        'hosts': ['192.168.31.169', '8.8.8.8'],
        'claim': 'single-use-claim-that-is-secret',
        'expires_at': '2030-01-01T00:05:00Z',
      }),
      now: DateTime.utc(2030, 1, 1),
    );

    expect(payload.hosts, hasLength(1));
    expect(payload.hosts.single.host, '192.168.31.169');
    expect(
      payload.toString(),
      isNot(contains('single-use-claim-that-is-secret')),
    );
  });

  test('rejects expiry, wrong protocol, and public-only hosts', () {
    Map<String, Object?> valid() => {
      'type': 'dzmm_pair',
      'version': 1,
      'server_id': 'server-1',
      'api_version': 1,
      'hosts': ['192.168.1.8'],
      'claim': 'single-use-claim-that-is-secret',
      'expires_at': '2030-01-01T00:05:00Z',
    };

    final expired = valid()..['expires_at'] = '2029-12-31T23:59:59Z';
    final incompatible = valid()..['api_version'] = 2;
    final public = valid()..['hosts'] = ['8.8.8.8'];

    for (final value in [expired, incompatible, public]) {
      expect(
        () => DzmmQrPayload.parse(
          jsonEncode(value),
          now: DateTime.utc(2030, 1, 1),
        ),
        throwsA(isA<FormatException>()),
      );
    }
  });
}

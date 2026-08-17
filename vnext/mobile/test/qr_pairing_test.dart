import 'package:dzmm_next_mobile/mobile_api.dart';
import 'package:dzmm_next_mobile/qr_pairing.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('accepts a private desktop QR handoff without granting authority', () {
    final payload = Uri(
      scheme: 'dzmm-next',
      host: 'pair',
      queryParameters: {
        'host': 'http://192.168.31.241:28765',
        'host_id': 'host-123',
      },
    ).toString();

    final host = parseQrPairingPayload(payload);

    expect(host.url, 'http://192.168.31.241:28765');
    expect(host.hostId, 'host-123');
  });

  test('rejects a public or malformed QR handoff', () {
    expect(
      () => parseQrPairingPayload(
        'dzmm-next://pair?host=https%3A%2F%2Fexample.com&host_id=x',
      ),
      throwsA(isA<HostApiError>()),
    );
    expect(
      () => parseQrPairingPayload('https://example.com'),
      throwsA(isA<HostApiError>()),
    );
  });
}

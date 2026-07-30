import 'package:dzmm_mobile/api/api_error.dart';
import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/connection/connection_store.dart';
import 'package:dzmm_mobile/connection/lan_scanner.dart';
import 'package:dzmm_mobile/features/pairing/pairing_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../connection/connection_store_test.dart'
    show MemoryPreferences, MemorySecrets;

void main() {
  late MemoryPreferences preferences;
  late MemorySecrets secrets;
  late ConnectionStore connectionStore;

  setUp(() {
    preferences = MemoryPreferences()
      ..values['android_device_id_v1'] = 'android-device-123'
      ..values['android_device_name_v1'] = '测试手机';
    secrets = MemorySecrets();
    connectionStore = ConnectionStore(
      preferences: preferences,
      secrets: secrets,
    );
  });

  test(
    'approval waits through pending and persists approved credential',
    () async {
      final transport = FakePairingTransport(
        polls: [
          ApprovalPoll(status: 'pending', expiresAt: DateTime.utc(2030)),
          ApprovalPoll(
            status: 'approved',
            expiresAt: DateTime.utc(2030),
            credential: const PairCredential(
              serverId: 'server-1',
              deviceToken: 'approved-token',
            ),
          ),
        ],
      );
      final controller = controllerWith(
        connectionStore,
        preferences,
        transport,
      );

      await controller.requestMacApproval(discoveredServer());

      expect(controller.state.status, PairingStatus.paired);
      expect(
        (await connectionStore.loadPairing('server-1'))?.deviceToken,
        'approved-token',
      );
      expect(controller.state.toString(), isNot(contains('approved-token')));
    },
  );

  test('models deny, expiry, rate limit, and offline explicitly', () async {
    for (final scenario in [
      (
        const ApiError(code: 'request_denied', message: 'denied'),
        PairingStatus.denied,
      ),
      (
        const ApiError(code: 'request_expired', message: 'expired'),
        PairingStatus.expired,
      ),
      (
        const ApiError(code: 'rate_limited', message: 'slow down'),
        PairingStatus.rateLimited,
      ),
      (
        const ApiError(code: 'offline', message: 'offline'),
        PairingStatus.offline,
      ),
    ]) {
      final transport = FakePairingTransport(pinError: scenario.$1);
      final controller = controllerWith(
        connectionStore,
        preferences,
        transport,
      );
      await controller.pairWithPin(discoveredServer(), '123456');
      expect(controller.state.status, scenario.$2);
    }
  });

  test(
    'QR replay error is expired and wrong server id is never saved',
    () async {
      final replayed = controllerWith(
        connectionStore,
        preferences,
        FakePairingTransport(
          qrError: const ApiError(code: 'claim_invalid', message: 'used'),
        ),
      );
      await replayed.pairWithQr(discoveredServer(), 'long-enough-claim-value');
      expect(replayed.state.status, PairingStatus.expired);

      final mismatch = controllerWith(
        connectionStore,
        preferences,
        FakePairingTransport(
          qrCredential: const PairCredential(
            serverId: 'another-server',
            deviceToken: 'must-not-save',
          ),
        ),
      );
      await mismatch.pairWithQr(discoveredServer(), 'long-enough-claim-value');
      expect(mismatch.state.errorCode, 'server_identity_mismatch');
      expect(await connectionStore.loadServers(), isEmpty);
      expect(secrets.values.values, isNot(contains('must-not-save')));
    },
  );

  test('user cancellation interrupts a long approval poll', () async {
    final transport = FakePairingTransport(waitForCancellation: true);
    final controller = controllerWith(connectionStore, preferences, transport);

    final pairing = controller.requestMacApproval(discoveredServer());
    await Future<void>.delayed(Duration.zero);
    controller.cancel();
    await pairing;

    expect(controller.state.status, PairingStatus.cancelled);
    expect(await connectionStore.loadServers(), isEmpty);
  });
}

PairingController controllerWith(
  ConnectionStore connectionStore,
  MemoryPreferences preferences,
  PairingTransport transport,
) => PairingController(
  connectionStore: connectionStore,
  identityStore: DeviceIdentityStore(preferences: preferences),
  transportFactory: (_) => transport,
  now: () => DateTime.utc(2029),
);

DiscoveredServer discoveredServer() => DiscoveredServer(
  health: const HealthInfo(
    version: '0.16.0',
    apiVersion: 1,
    serverId: 'server-1',
    remoteAccess: true,
    capabilities: {'pair_request', 'session_hydration'},
  ),
  endpoint: const HostEndpoint(
    host: '192.168.1.8',
    port: 8765,
    source: DiscoverySource.mdns,
  ),
  name: '书房 Mac',
);

class FakePairingTransport implements PairingTransport {
  FakePairingTransport({
    this.polls = const [],
    this.pinError,
    this.qrError,
    this.qrCredential = const PairCredential(
      serverId: 'server-1',
      deviceToken: 'qr-token',
    ),
    this.waitForCancellation = false,
  });

  final List<ApprovalPoll> polls;
  final ApiError? pinError;
  final ApiError? qrError;
  final PairCredential qrCredential;
  final bool waitForCancellation;
  var pollIndex = 0;

  @override
  Future<ApprovalTicket> createApproval(
    DeviceIdentity identity,
    CancellationToken cancellation,
  ) async => ApprovalTicket(
    requestId: 'request-1',
    pollSecret: 'pair-secret-long-enough',
    expiresAt: DateTime.utc(2030),
  );

  @override
  Future<ApprovalPoll> pollApproval(
    ApprovalTicket ticket,
    CancellationToken cancellation,
  ) async {
    if (waitForCancellation) {
      await cancellation.whenCancelled;
      throw const ApiError(code: 'cancelled', message: 'cancelled');
    }
    return polls[pollIndex++];
  }

  @override
  Future<PairCredential> pairWithPin(
    DeviceIdentity identity,
    String pin,
    CancellationToken cancellation,
  ) async {
    if (pinError != null) throw pinError!;
    return const PairCredential(serverId: 'server-1', deviceToken: 'pin-token');
  }

  @override
  Future<PairCredential> pairWithQr(
    DeviceIdentity identity,
    String claim,
    CancellationToken cancellation,
  ) async {
    if (qrError != null) throw qrError!;
    return qrCredential;
  }

  @override
  void close() {}
}

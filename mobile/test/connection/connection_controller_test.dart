import 'package:dzmm_mobile/api/api_error.dart';
import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/connection/connection_controller.dart';
import 'package:dzmm_mobile/connection/connection_store.dart';
import 'package:dzmm_mobile/connection/paired_server.dart';
import 'package:flutter_test/flutter_test.dart';

import 'connection_store_test.dart' show MemoryPreferences, MemorySecrets;

void main() {
  const server = PairedServer(
    serverId: 'server-1',
    name: '书房 Mac',
    port: 8765,
    recentHosts: ['192.168.1.7'],
  );
  final host = Uri.parse('http://192.168.1.8:8765');

  test('connects only after identity and authenticated probe pass', () async {
    final store = ConnectionStore(
      preferences: MemoryPreferences(),
      secrets: MemorySecrets(),
    );
    await store.savePairing(server, 'token');
    final client = FakeDzmmClient(healthInfo: validHealth());
    final controller = ConnectionController(
      store: store,
      clientFactory: (_, token) {
        expect(token, 'token');
        return client;
      },
    );

    await controller.connect(server: server, host: host, deviceToken: 'token');

    expect(controller.state.status, ConnectionStatus.connected);
    expect(controller.state.server?.recentHosts.first, '192.168.1.8');
    expect(client.requestedPaths, ['/sessions']);
  });

  test('rejects wrong server identity without using credential', () async {
    final client = FakeDzmmClient(
      healthInfo: validHealth(serverId: 'another-server'),
    );
    final controller = ConnectionController(
      store: memoryStore(),
      clientFactory: (_, _) => client,
    );

    await controller.connect(server: server, host: host, deviceToken: 'token');

    expect(controller.state.status, ConnectionStatus.reconnecting);
    expect(controller.state.errorCode, 'server_identity_mismatch');
    expect(client.requestedPaths, isEmpty);
  });

  test('models incompatible capability and revoked token states', () async {
    final store = memoryStore();
    await store.savePairing(server, 'token');
    final incompatible = ConnectionController(
      store: store,
      clientFactory: (_, _) => FakeDzmmClient(
        healthInfo: validHealth(capabilities: {'pair_request'}),
      ),
    );
    await incompatible.connect(
      server: server,
      host: host,
      deviceToken: 'token',
    );
    expect(incompatible.state.status, ConnectionStatus.incompatible);

    final revoked = ConnectionController(
      store: store,
      clientFactory: (_, _) => FakeDzmmClient(
        healthInfo: validHealth(),
        requestError: const ApiError(
          code: 'revoked',
          message: 'revoked',
          statusCode: 401,
        ),
      ),
    );
    await revoked.connect(server: server, host: host, deviceToken: 'token');
    expect(revoked.state.status, ConnectionStatus.revoked);
    expect(await store.loadPairing(server.serverId), isNull);
  });
}

ConnectionStore memoryStore() =>
    ConnectionStore(preferences: MemoryPreferences(), secrets: MemorySecrets());

HealthInfo validHealth({
  String serverId = 'server-1',
  Set<String> capabilities = const {'session_hydration'},
}) => HealthInfo(
  version: '0.16.0',
  apiVersion: 1,
  serverId: serverId,
  remoteAccess: true,
  capabilities: capabilities,
);

class FakeDzmmClient implements DzmmClient {
  FakeDzmmClient({required this.healthInfo, this.requestError});

  final HealthInfo healthInfo;
  final ApiError? requestError;
  final requestedPaths = <String>[];

  @override
  Future<HealthInfo> health({CancellationToken? cancellationToken}) async =>
      healthInfo;

  @override
  Future<Object?> getJson(
    String path, {
    Map<String, String>? headers,
    Map<String, String>? query,
    bool authenticated = true,
    CancellationToken? cancellationToken,
  }) async {
    requestedPaths.add(path);
    if (requestError != null) throw requestError!;
    return const [];
  }

  @override
  void close() {}
}

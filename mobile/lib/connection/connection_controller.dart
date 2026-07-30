import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../api/dzmm_api.dart';
import 'connection_store.dart';
import 'paired_server.dart';

enum ConnectionStatus {
  offline,
  scanning,
  pairing,
  connected,
  reconnecting,
  revoked,
  incompatible,
}

class DzmmConnectionState {
  const DzmmConnectionState({
    this.status = ConnectionStatus.offline,
    this.server,
    this.host,
    this.errorCode,
  });

  final ConnectionStatus status;
  final PairedServer? server;
  final Uri? host;
  final String? errorCode;

  @override
  String toString() =>
      'DzmmConnectionState(status: ${status.name}, server: $server, '
      'host: $host, errorCode: $errorCode)';
}

typedef DzmmClientFactory = DzmmClient Function(Uri host, String deviceToken);

class ConnectionController extends StateNotifier<DzmmConnectionState> {
  ConnectionController({
    required ConnectionStore store,
    DzmmClientFactory? clientFactory,
  }) : _connectionStore = store,
       _clientFactory =
           clientFactory ??
           ((host, token) => DzmmApi(baseUri: host, deviceToken: token)),
       super(const DzmmConnectionState());

  static const supportedApiVersion = 1;
  static const requiredCapabilities = {'session_hydration'};

  final ConnectionStore _connectionStore;
  final DzmmClientFactory _clientFactory;
  CancellationToken? _activeCancellation;

  void showOffline({String? errorCode}) {
    _cancelActiveRequest();
    state = DzmmConnectionState(
      status: ConnectionStatus.offline,
      errorCode: errorCode,
    );
  }

  void startScanning() {
    _cancelActiveRequest();
    state = const DzmmConnectionState(status: ConnectionStatus.scanning);
  }

  void startPairing(Uri host) {
    _cancelActiveRequest();
    state = DzmmConnectionState(status: ConnectionStatus.pairing, host: host);
  }

  Future<bool> connect({
    required PairedServer server,
    required Uri host,
    required String deviceToken,
  }) async {
    _cancelActiveRequest();
    final cancellation = CancellationToken();
    _activeCancellation = cancellation;
    state = DzmmConnectionState(
      status: ConnectionStatus.reconnecting,
      server: server,
      host: host,
    );
    final client = _clientFactory(host, deviceToken);
    try {
      final health = await client.health(cancellationToken: cancellation);
      _validateIdentity(server, health);
      await client.getJson('/sessions', cancellationToken: cancellation);
      if (cancellation.isCancelled) return false;
      await _connectionStore.updateRecentHost(server.serverId, host.host);
      final refreshed = (await _connectionStore.loadServers())
          .where((item) => item.serverId == server.serverId)
          .firstOrNull;
      state = DzmmConnectionState(
        status: ConnectionStatus.connected,
        server: refreshed ?? server,
        host: host,
      );
      return true;
    } on ApiError catch (error) {
      if (error.code == 'cancelled') return false;
      if (error.isAuthenticationFailure) {
        await _connectionStore.markRevoked(server.serverId);
        state = DzmmConnectionState(
          status: ConnectionStatus.revoked,
          server: server,
          host: host,
          errorCode: error.code,
        );
      } else if (error.code == 'server_incompatible') {
        state = DzmmConnectionState(
          status: ConnectionStatus.incompatible,
          server: server,
          host: host,
          errorCode: error.code,
        );
      } else {
        state = DzmmConnectionState(
          status: ConnectionStatus.reconnecting,
          server: server,
          host: host,
          errorCode: error.code,
        );
      }
      return false;
    } finally {
      client.close();
      if (identical(_activeCancellation, cancellation)) {
        _activeCancellation = null;
      }
    }
  }

  static void _validateIdentity(PairedServer server, HealthInfo health) {
    if (health.serverId != server.serverId) {
      throw const ApiError(
        code: 'server_identity_mismatch',
        message: 'The address belongs to a different dzmm host',
      );
    }
    if (health.apiVersion != supportedApiVersion ||
        !health.capabilities.containsAll(requiredCapabilities)) {
      throw const ApiError(
        code: 'server_incompatible',
        message: 'The dzmm host protocol is not supported',
      );
    }
    if (!health.remoteAccess) {
      throw const ApiError(
        code: 'remote_disabled',
        message: 'Remote access is disabled on the Mac',
      );
    }
  }

  void _cancelActiveRequest() {
    _activeCancellation?.cancel();
    _activeCancellation = null;
  }

  @override
  void dispose() {
    _cancelActiveRequest();
    super.dispose();
  }
}

final connectionStoreProvider = Provider<ConnectionStore>(
  (_) => ConnectionStore(),
);

final connectionControllerProvider =
    StateNotifierProvider<ConnectionController, DzmmConnectionState>(
      (ref) => ConnectionController(store: ref.watch(connectionStoreProvider)),
    );

import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';

import 'connection_controller.dart';
import 'connection_store.dart';
import 'lan_scanner.dart';
import 'paired_server.dart';

enum ReconnectStatus { idle, scanning, connected, notFound, permissionDenied }

class ReconnectState {
  const ReconnectState({this.status = ReconnectStatus.idle, this.serverId});

  final ReconnectStatus status;
  final String? serverId;
}

typedef ReconnectScanner =
    Stream<DiscoveredServer> Function(List<PairedServer> servers);
typedef ReconnectConnector =
    Future<bool> Function(PairedServer server, Uri host, String deviceToken);

class ReconnectService {
  ReconnectService({
    required ConnectionStore store,
    required ReconnectConnector connect,
    ReconnectScanner? scan,
    Stream<List<ConnectivityResult>>? networkChanges,
    this.debounce = const Duration(seconds: 2),
  }) : _connectionStore = store,
       _connector = connect,
       _scan =
           scan ??
           ((servers) => LanScanner().scan(
             recentServers: servers,
             ports: servers.map((server) => server.port).toSet(),
             requestPermission: false,
           )),
       _networkChanges = networkChanges ?? Connectivity().onConnectivityChanged;

  final ConnectionStore _connectionStore;
  final ReconnectConnector _connector;
  final ReconnectScanner _scan;
  final Stream<List<ConnectivityResult>> _networkChanges;
  final Duration debounce;
  final _stateController = StreamController<ReconnectState>.broadcast();
  StreamSubscription<List<ConnectivityResult>>? _subscription;
  Timer? _debounceTimer;
  bool _running = false;

  Stream<ReconnectState> get states => _stateController.stream;

  void start() {
    _subscription ??= _networkChanges.listen((results) {
      final reachable = results.any(
        (result) =>
            result == ConnectivityResult.wifi ||
            result == ConnectivityResult.ethernet,
      );
      if (!reachable) return;
      _debounceTimer?.cancel();
      _debounceTimer = Timer(debounce, reconnectNow);
    });
  }

  Future<void> reconnectNow() async {
    if (_running) return;
    _running = true;
    _emit(const ReconnectState(status: ReconnectStatus.scanning));
    try {
      final servers = (await _connectionStore.loadServers())
          .where((server) => server.credentialState == CredentialState.active)
          .toList();
      if (servers.isEmpty) {
        _emit(const ReconnectState(status: ReconnectStatus.notFound));
        return;
      }
      await for (final found in _scan(servers)) {
        final server = servers
            .where((item) => item.serverId == found.serverId)
            .firstOrNull;
        if (server == null) continue;
        final pairing = await _connectionStore.loadPairing(server.serverId);
        if (pairing == null) continue;
        final connected = await _connector(
          server,
          found.endpoint.uri,
          pairing.deviceToken,
        );
        if (!connected) continue;
        _emit(
          ReconnectState(
            status: ReconnectStatus.connected,
            serverId: server.serverId,
          ),
        );
        return;
      }
      _emit(const ReconnectState(status: ReconnectStatus.notFound));
    } on NearbyPermissionException {
      _emit(const ReconnectState(status: ReconnectStatus.permissionDenied));
    } finally {
      _running = false;
    }
  }

  void _emit(ReconnectState state) {
    if (!_stateController.isClosed) _stateController.add(state);
  }

  Future<void> dispose() async {
    _debounceTimer?.cancel();
    await _subscription?.cancel();
    await _stateController.close();
  }
}

ReconnectConnector connectionControllerConnector(
  ConnectionController controller,
) {
  return (server, host, token) =>
      controller.connect(server: server, host: host, deviceToken: token);
}

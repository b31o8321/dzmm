import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../api/api_error.dart';
import '../../api/dzmm_api.dart';
import '../../connection/connection_controller.dart';
import '../../connection/connection_store.dart';
import '../../connection/lan_scanner.dart';
import '../../connection/paired_server.dart';

class DeviceIdentity {
  const DeviceIdentity({required this.id, required this.name});

  final String id;
  final String name;
}

class DeviceIdentityStore {
  DeviceIdentityStore({PreferencesBackend? preferences, Uuid? uuid})
    : _preferences = preferences ?? SharedPreferencesBackend(),
      _uuid = uuid ?? const Uuid();

  static const _idKey = 'android_device_id_v1';
  static const _nameKey = 'android_device_name_v1';

  final PreferencesBackend _preferences;
  final Uuid _uuid;

  Future<DeviceIdentity> load({String? preferredName}) async {
    var id = await _preferences.read(_idKey);
    if (id == null || id.length < 8) {
      id = _uuid.v4();
      await _preferences.write(_idKey, id);
    }
    final storedName = await _preferences.read(_nameKey);
    final name = preferredName?.trim().isNotEmpty == true
        ? preferredName!.trim()
        : storedName ?? 'Android 手机';
    if (name != storedName) await _preferences.write(_nameKey, name);
    return DeviceIdentity(id: id, name: name);
  }
}

class ApprovalTicket {
  const ApprovalTicket({
    required this.requestId,
    required this.pollSecret,
    required this.expiresAt,
  });

  final String requestId;
  final String pollSecret;
  final DateTime expiresAt;
}

class PairCredential {
  const PairCredential({required this.serverId, required this.deviceToken});

  final String serverId;
  final String deviceToken;

  @override
  String toString() =>
      'PairCredential(serverId: $serverId, deviceToken: <redacted>)';
}

class ApprovalPoll {
  const ApprovalPoll({
    required this.status,
    required this.expiresAt,
    this.credential,
  });

  final String status;
  final DateTime expiresAt;
  final PairCredential? credential;
}

abstract interface class PairingTransport {
  Future<ApprovalTicket> createApproval(
    DeviceIdentity identity,
    CancellationToken cancellation,
  );
  Future<ApprovalPoll> pollApproval(
    ApprovalTicket ticket,
    CancellationToken cancellation,
  );
  Future<PairCredential> pairWithPin(
    DeviceIdentity identity,
    String pin,
    CancellationToken cancellation,
  );
  Future<PairCredential> pairWithQr(
    DeviceIdentity identity,
    String claim,
    CancellationToken cancellation,
  );
  void close();
}

class HttpPairingTransport implements PairingTransport {
  HttpPairingTransport(Uri host)
    : _api = DzmmApi(baseUri: host, timeout: const Duration(seconds: 30));

  final DzmmApi _api;

  @override
  Future<ApprovalTicket> createApproval(
    DeviceIdentity identity,
    CancellationToken cancellation,
  ) async {
    final value = await _api.postJson(
      '/remote/pair/requests',
      _identityJson(identity),
      authenticated: false,
      cancellationToken: cancellation,
    );
    final json = _object(value);
    return ApprovalTicket(
      requestId: _string(json, 'request_id'),
      pollSecret: _string(json, 'poll_secret'),
      expiresAt: _dateTime(json, 'expires_at'),
    );
  }

  @override
  Future<ApprovalPoll> pollApproval(
    ApprovalTicket ticket,
    CancellationToken cancellation,
  ) async {
    final value = await _api.getJson(
      '/remote/pair/requests/${Uri.encodeComponent(ticket.requestId)}',
      headers: {'X-DZMM-Pair-Secret': ticket.pollSecret},
      query: const {'wait_seconds': '25'},
      authenticated: false,
      cancellationToken: cancellation,
    );
    final json = _object(value);
    final status = _string(json, 'status');
    return ApprovalPoll(
      status: status,
      expiresAt: _dateTime(json, 'expires_at'),
      credential: status == 'approved' ? _credential(json) : null,
    );
  }

  @override
  Future<PairCredential> pairWithPin(
    DeviceIdentity identity,
    String pin,
    CancellationToken cancellation,
  ) async {
    final value = await _api.postJson(
      '/remote/pair/pin',
      {..._identityJson(identity), 'pin': pin},
      authenticated: false,
      cancellationToken: cancellation,
    );
    return _credential(_object(value));
  }

  @override
  Future<PairCredential> pairWithQr(
    DeviceIdentity identity,
    String claim,
    CancellationToken cancellation,
  ) async {
    final value = await _api.postJson(
      '/remote/pair/qr-claim',
      {..._identityJson(identity), 'claim': claim},
      authenticated: false,
      cancellationToken: cancellation,
    );
    return _credential(_object(value));
  }

  static Map<String, String> _identityJson(DeviceIdentity identity) => {
    'device_id': identity.id,
    'device_name': identity.name,
  };

  static Map<String, Object?> _object(Object? value) {
    if (value is! Map) {
      throw const ApiError(
        code: 'invalid_response',
        message: 'The pairing response was not an object',
      );
    }
    return value.cast<String, Object?>();
  }

  static String _string(Map<String, Object?> json, String key) {
    final value = json[key];
    if (value is! String || value.isEmpty) {
      throw const ApiError(
        code: 'invalid_response',
        message: 'The pairing response was incomplete',
      );
    }
    return value;
  }

  static DateTime _dateTime(Map<String, Object?> json, String key) {
    final value = json[key];
    final parsed = value is String ? DateTime.tryParse(value) : null;
    if (parsed == null) {
      throw const ApiError(
        code: 'invalid_response',
        message: 'The pairing expiry was invalid',
      );
    }
    return parsed.toUtc();
  }

  static PairCredential _credential(Map<String, Object?> json) =>
      PairCredential(
        serverId: _string(json, 'server_id'),
        deviceToken: _string(json, 'device_token'),
      );

  @override
  void close() => _api.close();
}

enum PairingStatus {
  idle,
  submitting,
  waitingApproval,
  paired,
  denied,
  expired,
  rateLimited,
  offline,
  cancelled,
  failed,
}

class PairingState {
  const PairingState({
    this.status = PairingStatus.idle,
    this.serverId,
    this.expiresAt,
    this.errorCode,
  });

  final PairingStatus status;
  final String? serverId;
  final DateTime? expiresAt;
  final String? errorCode;
}

typedef PairingTransportFactory = PairingTransport Function(Uri host);

class PairingController extends StateNotifier<PairingState> {
  PairingController({
    required ConnectionStore connectionStore,
    DeviceIdentityStore? identityStore,
    PairingTransportFactory? transportFactory,
    DateTime Function()? now,
  }) : _pairingStore = connectionStore,
       _identityStore = identityStore ?? DeviceIdentityStore(),
       _transportFactory = transportFactory ?? HttpPairingTransport.new,
       _now = now ?? (() => DateTime.now().toUtc()),
       super(const PairingState());

  final ConnectionStore _pairingStore;
  final DeviceIdentityStore _identityStore;
  final PairingTransportFactory _transportFactory;
  final DateTime Function() _now;
  CancellationToken? _cancellation;

  Future<void> requestMacApproval(
    DiscoveredServer discovered, {
    String? deviceName,
  }) => _run(discovered, deviceName, (transport, identity, cancellation) async {
    final ticket = await transport.createApproval(identity, cancellation);
    state = PairingState(
      status: PairingStatus.waitingApproval,
      serverId: discovered.serverId,
      expiresAt: ticket.expiresAt,
    );
    while (!cancellation.isCancelled && _now().isBefore(ticket.expiresAt)) {
      final poll = await transport.pollApproval(ticket, cancellation);
      switch (poll.status) {
        case 'pending':
          continue;
        case 'approved':
          final credential = poll.credential;
          if (credential == null) {
            throw const ApiError(
              code: 'invalid_response',
              message: 'Approved pairing did not include a credential',
            );
          }
          return credential;
        case 'denied':
          throw const ApiError(
            code: 'request_denied',
            message: 'Pairing denied',
          );
        case 'expired':
          throw const ApiError(
            code: 'request_expired',
            message: 'Pairing expired',
          );
        default:
          throw const ApiError(
            code: 'invalid_response',
            message: 'Unknown pairing status',
          );
      }
    }
    throw const ApiError(code: 'request_expired', message: 'Pairing expired');
  });

  Future<void> pairWithPin(
    DiscoveredServer discovered,
    String pin, {
    String? deviceName,
  }) {
    if (!RegExp(r'^\d{6}$').hasMatch(pin)) {
      state = const PairingState(
        status: PairingStatus.failed,
        errorCode: 'bad_pin_format',
      );
      return Future.value();
    }
    return _run(
      discovered,
      deviceName,
      (transport, identity, cancellation) =>
          transport.pairWithPin(identity, pin, cancellation),
    );
  }

  Future<void> pairWithQr(
    DiscoveredServer discovered,
    String claim, {
    String? deviceName,
  }) => _run(
    discovered,
    deviceName,
    (transport, identity, cancellation) =>
        transport.pairWithQr(identity, claim, cancellation),
  );

  Future<void> _run(
    DiscoveredServer discovered,
    String? deviceName,
    Future<PairCredential> Function(
      PairingTransport transport,
      DeviceIdentity identity,
      CancellationToken cancellation,
    )
    action,
  ) async {
    cancel();
    final cancellation = CancellationToken();
    _cancellation = cancellation;
    state = PairingState(
      status: PairingStatus.submitting,
      serverId: discovered.serverId,
    );
    final transport = _transportFactory(discovered.endpoint.uri);
    try {
      final identity = await _identityStore.load(preferredName: deviceName);
      final credential = await action(transport, identity, cancellation);
      if (cancellation.isCancelled) return;
      if (credential.serverId != discovered.serverId) {
        throw const ApiError(
          code: 'server_identity_mismatch',
          message: 'The pairing response belongs to another host',
        );
      }
      await _pairingStore.savePairing(
        PairedServer(
          serverId: discovered.serverId,
          name: discovered.name,
          port: discovered.endpoint.port,
          recentHosts: [discovered.endpoint.host],
          apiVersion: discovered.health.apiVersion,
          lastSeen: _now(),
        ),
        credential.deviceToken,
      );
      state = PairingState(
        status: PairingStatus.paired,
        serverId: discovered.serverId,
      );
    } on ApiError catch (error) {
      if (error.code == 'cancelled' || cancellation.isCancelled) {
        state = PairingState(
          status: PairingStatus.cancelled,
          serverId: discovered.serverId,
          errorCode: 'cancelled',
        );
      } else {
        state = PairingState(
          status: _statusForError(error.code),
          serverId: discovered.serverId,
          errorCode: error.code,
        );
      }
    } on Object {
      state = PairingState(
        status: PairingStatus.failed,
        serverId: discovered.serverId,
        errorCode: 'local_storage_error',
      );
    } finally {
      transport.close();
      if (identical(_cancellation, cancellation)) {
        _cancellation = null;
      }
    }
  }

  static PairingStatus _statusForError(String code) => switch (code) {
    'request_denied' => PairingStatus.denied,
    'request_expired' || 'claim_invalid' => PairingStatus.expired,
    'rate_limited' || 'too_many_pending' => PairingStatus.rateLimited,
    'offline' || 'timeout' || 'remote_disabled' => PairingStatus.offline,
    _ => PairingStatus.failed,
  };

  void cancel() {
    _cancellation?.cancel();
    _cancellation = null;
  }

  @override
  void dispose() {
    cancel();
    super.dispose();
  }
}

final deviceIdentityStoreProvider = Provider<DeviceIdentityStore>(
  (_) => DeviceIdentityStore(),
);

final pairingControllerProvider =
    StateNotifierProvider<PairingController, PairingState>((ref) {
      return PairingController(
        connectionStore: ref.watch(connectionStoreProvider),
        identityStore: ref.watch(deviceIdentityStoreProvider),
      );
    });

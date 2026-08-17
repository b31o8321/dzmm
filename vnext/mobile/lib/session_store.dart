import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class StoredSession {
  const StoredSession({
    required this.host,
    required this.token,
    this.runId,
    this.hostId,
  });

  final String host;
  final String token;
  final String? runId;
  final String? hostId;
}

abstract class SessionStore {
  Future<StoredSession?> read();
  Future<void> save(StoredSession session);
  Future<void> clear();
}

class SecureSessionStore implements SessionStore {
  const SecureSessionStore([this._storage = const FlutterSecureStorage()]);

  static const _hostKey = 'host_url';
  static const _tokenKey = 'mobile_token';
  static const _runKey = 'mobile_run_id';
  static const _hostIdKey = 'mobile_host_id';

  final FlutterSecureStorage _storage;

  @override
  Future<StoredSession?> read() async {
    final host = await _storage.read(key: _hostKey);
    final token = await _storage.read(key: _tokenKey);
    if (host == null || token == null) return null;
    return StoredSession(
      host: host,
      token: token,
      runId: await _storage.read(key: _runKey),
      hostId: await _storage.read(key: _hostIdKey),
    );
  }

  @override
  Future<void> save(StoredSession session) async {
    await _storage.write(key: _hostKey, value: session.host);
    await _storage.write(key: _tokenKey, value: session.token);
    if (session.runId == null || session.runId!.isEmpty) {
      await _storage.delete(key: _runKey);
    } else {
      await _storage.write(key: _runKey, value: session.runId);
    }
    if (session.hostId == null || session.hostId!.isEmpty) {
      await _storage.delete(key: _hostIdKey);
    } else {
      await _storage.write(key: _hostIdKey, value: session.hostId);
    }
  }

  @override
  Future<void> clear() => _storage.deleteAll();
}

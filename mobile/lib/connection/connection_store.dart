import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'paired_server.dart';

abstract interface class PreferencesBackend {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

abstract interface class SecretBackend {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
  Future<void> deleteWithPrefix(String prefix);
}

class SharedPreferencesBackend implements PreferencesBackend {
  @override
  Future<String?> read(String key) async =>
      (await SharedPreferences.getInstance()).getString(key);

  @override
  Future<void> write(String key, String value) async {
    final saved = await (await SharedPreferences.getInstance()).setString(
      key,
      value,
    );
    if (!saved) throw StateError('Could not persist connection metadata');
  }

  @override
  Future<void> delete(String key) async {
    await (await SharedPreferences.getInstance()).remove(key);
  }
}

class AndroidSecretBackend implements SecretBackend {
  AndroidSecretBackend({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);

  @override
  Future<void> deleteWithPrefix(String prefix) async {
    final values = await _storage.readAll();
    await Future.wait(
      values.keys
          .where((key) => key.startsWith(prefix))
          .map((key) => _storage.delete(key: key)),
    );
  }
}

class StoredPairing {
  const StoredPairing(this.server, this.deviceToken);

  final PairedServer server;
  final String deviceToken;

  @override
  String toString() =>
      'StoredPairing(server: $server, deviceToken: <redacted>)';
}

class ConnectionStore {
  ConnectionStore({PreferencesBackend? preferences, SecretBackend? secrets})
    : _preferences = preferences ?? SharedPreferencesBackend(),
      _secrets = secrets ?? AndroidSecretBackend();

  static const _serversKey = 'paired_servers_v1';
  static const _tokenPrefix = 'dzmm_device_token_';

  final PreferencesBackend _preferences;
  final SecretBackend _secrets;

  Future<List<PairedServer>> loadServers() async {
    final raw = await _preferences.read(_serversKey);
    if (raw == null) return const [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) throw const FormatException('Expected a list');
      return decoded
          .map(
            (item) =>
                PairedServer.fromJson((item as Map).cast<String, Object?>()),
          )
          .toList(growable: false);
    } on Object {
      await _preferences.delete(_serversKey);
      await _secrets.deleteWithPrefix(_tokenPrefix);
      return const [];
    }
  }

  Future<StoredPairing?> loadPairing(String serverId) async {
    final servers = await loadServers();
    final server = servers
        .where((item) => item.serverId == serverId)
        .firstOrNull;
    if (server == null || server.credentialState == CredentialState.revoked) {
      return null;
    }
    try {
      final token = await _secrets.read(_tokenKey(serverId));
      if (token == null || token.isEmpty) return null;
      return StoredPairing(server, token);
    } on Object {
      await _secrets.delete(_tokenKey(serverId));
      return null;
    }
  }

  Future<void> savePairing(PairedServer server, String deviceToken) async {
    if (deviceToken.isEmpty) {
      throw ArgumentError('deviceToken must not be empty');
    }
    final tokenKey = _tokenKey(server.serverId);
    String? oldToken;
    try {
      oldToken = await _secrets.read(tokenKey);
    } on Object {
      await _secrets.delete(tokenKey);
    }
    await _secrets.write(tokenKey, deviceToken);
    try {
      await _upsert(server.copyWith(credentialState: CredentialState.active));
    } on Object {
      if (oldToken == null) {
        await _secrets.delete(tokenKey);
      } else {
        await _secrets.write(tokenKey, oldToken);
      }
      rethrow;
    }
  }

  Future<void> markRevoked(String serverId) async {
    await _secrets.delete(_tokenKey(serverId));
    final servers = await loadServers();
    await _saveServers([
      for (final server in servers)
        if (server.serverId == serverId)
          server.copyWith(credentialState: CredentialState.revoked)
        else
          server,
    ]);
  }

  Future<void> forget(String serverId) async {
    await _secrets.delete(_tokenKey(serverId));
    final servers = await loadServers();
    await _saveServers(
      servers.where((server) => server.serverId != serverId).toList(),
    );
  }

  Future<void> updateRecentHost(
    String serverId,
    String host, {
    DateTime? seenAt,
  }) async {
    final servers = await loadServers();
    await _saveServers([
      for (final server in servers)
        if (server.serverId == serverId)
          server.copyWith(
            recentHosts: [
              host,
              ...server.recentHosts.where((candidate) => candidate != host),
            ].take(5).toList(),
            lastSeen: seenAt ?? DateTime.now().toUtc(),
          )
        else
          server,
    ]);
  }

  Future<void> _upsert(PairedServer server) async {
    final servers = await loadServers();
    await _saveServers([
      ...servers.where((item) => item.serverId != server.serverId),
      server,
    ]);
  }

  Future<void> _saveServers(List<PairedServer> servers) => _preferences.write(
    _serversKey,
    jsonEncode(servers.map((server) => server.toJson()).toList()),
  );

  static String _tokenKey(String serverId) => '$_tokenPrefix$serverId';
}

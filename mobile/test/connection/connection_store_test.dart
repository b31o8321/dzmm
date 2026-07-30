import 'package:dzmm_mobile/connection/connection_store.dart';
import 'package:dzmm_mobile/connection/paired_server.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const server = PairedServer(
    serverId: 'c1601171-7df0-4f12-afd2-cbfcfbc9df45',
    name: '书房 Mac',
    port: 8765,
    recentHosts: ['192.168.1.8'],
  );

  test('keeps device token outside metadata and redacts diagnostics', () async {
    final preferences = MemoryPreferences();
    final secrets = MemorySecrets();
    final store = ConnectionStore(preferences: preferences, secrets: secrets);

    await store.savePairing(server, 'top-secret-token');
    final pairing = await store.loadPairing(server.serverId);

    expect(
      preferences.values.values.single,
      isNot(contains('top-secret-token')),
    );
    expect(pairing?.deviceToken, 'top-secret-token');
    expect(pairing.toString(), isNot(contains('top-secret-token')));
  });

  test('rotates a token without duplicating server metadata', () async {
    final store = ConnectionStore(
      preferences: MemoryPreferences(),
      secrets: MemorySecrets(),
    );

    await store.savePairing(server, 'old-token');
    await store.savePairing(server, 'new-token');

    expect((await store.loadServers()), hasLength(1));
    expect(
      (await store.loadPairing(server.serverId))?.deviceToken,
      'new-token',
    );
  });

  test(
    'revocation removes token but retains a re-pairable host record',
    () async {
      final store = ConnectionStore(
        preferences: MemoryPreferences(),
        secrets: MemorySecrets(),
      );
      await store.savePairing(server, 'token');

      await store.markRevoked(server.serverId);

      expect(await store.loadPairing(server.serverId), isNull);
      expect(
        (await store.loadServers()).single.credentialState,
        CredentialState.revoked,
      );
    },
  );

  test('forget removes metadata and secret', () async {
    final secrets = MemorySecrets();
    final store = ConnectionStore(
      preferences: MemoryPreferences(),
      secrets: secrets,
    );
    await store.savePairing(server, 'token');

    await store.forget(server.serverId);

    expect(await store.loadServers(), isEmpty);
    expect(secrets.values, isEmpty);
  });

  test('recovers safely from corrupt metadata and token storage', () async {
    final preferences = MemoryPreferences()
      ..values['paired_servers_v1'] = '{bad';
    final secrets = MemorySecrets()
      ..values['dzmm_device_token_orphan'] = 'must-be-cleared';
    final store = ConnectionStore(preferences: preferences, secrets: secrets);

    expect(await store.loadServers(), isEmpty);
    expect(preferences.values, isEmpty);
    expect(secrets.values, isEmpty);

    await store.savePairing(server, 'fresh-token');
    secrets.failReads = true;
    expect(await store.loadPairing(server.serverId), isNull);
    expect(secrets.values, isEmpty);
  });

  test('re-pairing replaces an unreadable secure-storage entry', () async {
    final secrets = MemorySecrets()
      ..values['dzmm_device_token_${server.serverId}'] = 'bad';
    final store = ConnectionStore(
      preferences: MemoryPreferences(),
      secrets: secrets,
    );
    secrets.failReads = true;

    await store.savePairing(server, 'rotated-token');
    secrets.failReads = false;

    expect(
      (await store.loadPairing(server.serverId))?.deviceToken,
      'rotated-token',
    );
  });
}

class MemoryPreferences implements PreferencesBackend {
  final values = <String, String>{};

  @override
  Future<void> delete(String key) async => values.remove(key);

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async => values[key] = value;
}

class MemorySecrets implements SecretBackend {
  final values = <String, String>{};
  var failReads = false;

  @override
  Future<void> delete(String key) async => values.remove(key);

  @override
  Future<void> deleteWithPrefix(String prefix) async {
    values.removeWhere((key, _) => key.startsWith(prefix));
  }

  @override
  Future<String?> read(String key) async {
    if (failReads) throw StateError('corrupt keystore');
    return values[key];
  }

  @override
  Future<void> write(String key, String value) async => values[key] = value;
}

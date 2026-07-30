import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/connection/connection_store.dart';
import 'package:dzmm_mobile/connection/lan_scanner.dart';
import 'package:dzmm_mobile/connection/paired_server.dart';
import 'package:dzmm_mobile/connection/reconnect_service.dart';
import 'package:flutter_test/flutter_test.dart';

import 'connection_store_test.dart' show MemoryPreferences, MemorySecrets;

void main() {
  test(
    'debounces network changes and reconnects by stable server id',
    () async {
      const server = PairedServer(
        serverId: 'server-1',
        name: '书房 Mac',
        port: 8765,
        recentHosts: ['192.168.1.7'],
      );
      final store = ConnectionStore(
        preferences: MemoryPreferences(),
        secrets: MemorySecrets(),
      );
      await store.savePairing(server, 'device-token');
      final changes = StreamController<List<ConnectivityResult>>();
      var scans = 0;
      final connections = <Uri>[];
      final service = ReconnectService(
        store: store,
        networkChanges: changes.stream,
        debounce: const Duration(milliseconds: 10),
        scan: (_) {
          scans++;
          return Stream.value(
            DiscoveredServer(
              health: HealthInfo(
                version: '0.16.0',
                apiVersion: 1,
                serverId: server.serverId,
                remoteAccess: true,
                capabilities: const {'session_hydration'},
              ),
              endpoint: const HostEndpoint(
                host: '192.168.1.22',
                port: 8765,
                source: DiscoverySource.mdns,
              ),
              name: server.name,
            ),
          );
        },
        connect: (matched, host, token) async {
          expect(matched.serverId, server.serverId);
          expect(token, 'device-token');
          connections.add(host);
        },
      );
      service.start();
      changes.add([ConnectivityResult.wifi]);
      changes.add([ConnectivityResult.none]);
      changes.add([ConnectivityResult.wifi]);

      await Future<void>.delayed(const Duration(milliseconds: 80));

      expect(scans, 1);
      expect(connections.single.host, '192.168.1.22');
      await service.dispose();
      await changes.close();
    },
  );
}

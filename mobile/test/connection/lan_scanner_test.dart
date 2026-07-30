import 'dart:async';

import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/connection/lan_scanner.dart';
import 'package:dzmm_mobile/connection/paired_server.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'probes recent hosts first and deduplicates updates by server id',
    () async {
      final probe = RecordingProbe({
        '192.168.1.7': health('server-1'),
        '192.168.1.8': health('server-1'),
      });
      final scanner = LanScanner(
        probe: probe,
        mdns: FakeMdns([
          const HostEndpoint(
            host: '192.168.1.8',
            port: 8765,
            source: DiscoverySource.mdns,
          ),
        ]),
        networkInfo: const FakeNetworkInfo(null),
        permissionGate: const GrantedPermission(),
        scanDuration: Duration.zero,
      );

      final results = await scanner
          .scan(
            recentServers: const [
              PairedServer(
                serverId: 'server-1',
                name: '书房 Mac',
                port: 8765,
                recentHosts: ['192.168.1.7'],
              ),
            ],
            includeSubnet: false,
          )
          .toList();

      expect(results.map((item) => item.serverId).toSet(), {'server-1'});
      expect(results.first.endpoint.source, DiscoverySource.recent);
      expect(results.last.endpoint.host, '192.168.1.8');
    },
  );

  test('bounds subnet probe concurrency', () async {
    final probe = RecordingProbe(
      const {},
      delay: const Duration(milliseconds: 2),
    );
    final scanner = LanScanner(
      probe: probe,
      mdns: const FakeMdns([]),
      networkInfo: const FakeNetworkInfo('192.168.7.20'),
      permissionGate: const GrantedPermission(),
      maxConcurrent: 7,
      scanDuration: Duration.zero,
    );

    await scanner.scan().drain<void>();

    expect(probe.maxActive, lessThanOrEqualTo(7));
    expect(probe.seen, hasLength(253));
  });

  test('manual entry accepts private LAN and rejects public targets', () async {
    final endpoint = await parseManualEndpoint('192.168.31.169:9000');
    expect(endpoint.port, 9000);
    expect(endpoint.source, DiscoverySource.manual);

    await expectLater(
      parseManualEndpoint('8.8.8.8:8765'),
      throwsA(isA<FormatException>()),
    );
    await expectLater(
      parseManualEndpoint('https://192.168.1.8'),
      throwsA(isA<FormatException>()),
    );
  });

  test('surfaces nearby permission denial for actionable UI', () async {
    final scanner = LanScanner(
      probe: RecordingProbe(const {}),
      mdns: const FakeMdns([]),
      networkInfo: const FakeNetworkInfo(null),
      permissionGate: const DeniedPermission(),
    );

    await expectLater(
      scanner.scan().drain<void>(),
      throwsA(
        isA<NearbyPermissionException>().having(
          (error) => error.permanentlyDenied,
          'permanentlyDenied',
          true,
        ),
      ),
    );
  });
}

HealthInfo health(String serverId) => HealthInfo(
  version: '0.16.0',
  apiVersion: 1,
  serverId: serverId,
  remoteAccess: true,
  capabilities: const {'session_hydration'},
);

class RecordingProbe implements HostProbe {
  RecordingProbe(this.responses, {this.delay = Duration.zero});

  final Map<String, HealthInfo> responses;
  final Duration delay;
  final seen = <HostEndpoint>[];
  var active = 0;
  var maxActive = 0;

  @override
  Future<HealthInfo?> probe(HostEndpoint endpoint) async {
    seen.add(endpoint);
    active++;
    if (active > maxActive) maxActive = active;
    await Future<void>.delayed(delay);
    active--;
    return responses[endpoint.host];
  }
}

class FakeMdns implements MdnsSource {
  const FakeMdns(this.endpoints);
  final List<HostEndpoint> endpoints;

  @override
  Stream<HostEndpoint> discover(Duration duration) =>
      Stream.fromIterable(endpoints);
}

class FakeNetworkInfo implements NetworkInfo {
  const FakeNetworkInfo(this.address);
  final String? address;

  @override
  Future<String?> privateIpv4() async => address;
}

class GrantedPermission implements NearbyPermissionGate {
  const GrantedPermission();

  @override
  Future<void> ensureGranted() async {}
}

class DeniedPermission implements NearbyPermissionGate {
  const DeniedPermission();

  @override
  Future<void> ensureGranted() async =>
      throw const NearbyPermissionException(permanentlyDenied: true);
}

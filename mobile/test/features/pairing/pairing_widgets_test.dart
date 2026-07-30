import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/connection/lan_scanner.dart';
import 'package:dzmm_mobile/connection/paired_server.dart';
import 'package:dzmm_mobile/features/pairing/connection_onboarding_page.dart';
import 'package:dzmm_mobile/features/pairing/manual_address_sheet.dart';
import 'package:dzmm_mobile/features/pairing/pin_pair_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../connection/lan_scanner_test.dart'
    show FakeMdns, FakeNetworkInfo, GrantedPermission, RecordingProbe;

void main() {
  testWidgets('scan results remain usable in landscape with many hosts', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final endpoints = List.generate(
      12,
      (index) => HostEndpoint(
        host: '192.168.1.${index + 10}',
        port: 8765,
        source: DiscoverySource.mdns,
        name: 'Mac ${index + 1}',
      ),
    );
    final scanner = LanScanner(
      probe: RecordingProbe({
        for (final endpoint in endpoints)
          endpoint.host: HealthInfo(
            version: '0.16.0',
            apiVersion: 1,
            serverId: 'server-${endpoint.host}',
            remoteAccess: true,
            capabilities: const {'session_hydration'},
          ),
      }),
      mdns: FakeMdns(endpoints),
      networkInfo: const FakeNetworkInfo(null),
      permissionGate: const GrantedPermission(),
      scanDuration: Duration.zero,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ConnectionOnboardingPage(scanner: scanner, onSelected: (_) {}),
        ),
      ),
    );

    await tester.tap(find.text('查找 Mac'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.byType(SingleChildScrollView), findsOneWidget);
  });

  testWidgets('scan shows compatible hosts incrementally and paired status', (
    tester,
  ) async {
    final scanner = LanScanner(
      probe: RecordingProbe({
        '192.168.1.8': const HealthInfo(
          version: '0.16.0',
          apiVersion: 1,
          serverId: 'server-1',
          remoteAccess: true,
          capabilities: {'session_hydration'},
        ),
      }),
      mdns: const FakeMdns([
        HostEndpoint(
          host: '192.168.1.8',
          port: 8765,
          source: DiscoverySource.mdns,
          name: '书房 Mac',
        ),
      ]),
      networkInfo: const FakeNetworkInfo(null),
      permissionGate: const GrantedPermission(),
      scanDuration: Duration.zero,
    );
    DiscoveredServer? selected;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ConnectionOnboardingPage(
            scanner: scanner,
            pairedServers: const [
              PairedServer(
                serverId: 'server-1',
                name: '书房 Mac',
                port: 8765,
                recentHosts: [],
              ),
            ],
            onSelected: (value) => selected = value,
          ),
        ),
      ),
    );

    await tester.tap(find.text('查找 Mac'));
    await tester.pumpAndSettle();

    expect(find.text('书房 Mac'), findsOneWidget);
    expect(find.textContaining('已配对'), findsOneWidget);
    await tester.tap(find.text('书房 Mac'));
    expect(selected?.serverId, 'server-1');
  });

  testWidgets('manual address gives guidance and returns private endpoint', (
    tester,
  ) async {
    HostEndpoint? endpoint;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                endpoint = await showModalBottomSheet<HostEndpoint>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => const ManualAddressSheet(),
                );
              },
              child: const Text('打开'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '8.8.8.8:8765');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(find.textContaining('仅允许'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '192.168.1.9:9000');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(endpoint?.port, 9000);
  });

  testWidgets('PIN sheet only returns six digits', (tester) async {
    String? pin;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                pin = await showModalBottomSheet<String>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => const PinPairSheet(),
                );
              },
              child: const Text('打开 PIN'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开 PIN'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '12ab345678');
    await tester.pump();
    expect(find.text('123456'), findsOneWidget);
    await tester.tap(find.text('配对'));
    await tester.pumpAndSettle();
    expect(pin, '123456');
  });
}

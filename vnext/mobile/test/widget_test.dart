import 'package:flutter_test/flutter_test.dart';

import 'package:dzmm_next_mobile/host_discovery.dart';
import 'package:dzmm_next_mobile/main.dart';
import 'package:dzmm_next_mobile/mobile_api.dart';
import 'package:dzmm_next_mobile/session_store.dart';

class _MemorySessionStore implements SessionStore {
  StoredSession? value;
  @override
  Future<void> clear() async => value = null;
  @override
  Future<StoredSession?> read() async => value;
  @override
  Future<void> save(StoredSession session) async => value = session;
}

class _StaticHostDiscovery implements HostDiscovery {
  const _StaticHostDiscovery(this.hosts);

  final List<DiscoveredHost> hosts;

  @override
  Stream<DiscoveredHost> discover({
    Duration duration = const Duration(seconds: 4),
  }) async* {
    yield* Stream.fromIterable(hosts);
  }
}

void main() {
  testWidgets('shows the gameplay-only pairing entry point', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      DzmmMobileApp(
        api: MobileApi(),
        sessionStore: _MemorySessionStore(),
        discovery: const _StaticHostDiscovery([
          DiscoveredHost(
            host: '192.168.31.241',
            port: 8765,
            name: 'DZMM Host on Norman-Mac',
            hostId: 'host-123',
          ),
        ]),
      ),
    );
    await tester.pump();
    expect(find.text('连接桌面 Host'), findsOneWidget);
    expect(find.text('申请手机配对'), findsOneWidget);
    expect(find.textContaining('世界、模型和删除操作只在桌面端管理'), findsOneWidget);
    expect(find.text('DZMM Host on Norman-Mac'), findsOneWidget);
  });
}

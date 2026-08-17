import 'package:flutter_test/flutter_test.dart';

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

void main() {
  testWidgets('shows the gameplay-only pairing entry point', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      DzmmMobileApp(api: MobileApi(), sessionStore: _MemorySessionStore()),
    );
    await tester.pump();
    expect(find.text('连接 Mac Host'), findsOneWidget);
    expect(find.text('申请手机配对'), findsOneWidget);
    expect(find.textContaining('世界、模型和删除操作只在 Mac 上管理'), findsOneWidget);
  });
}

import 'package:dzmm_mobile/app.dart';
import 'package:dzmm_mobile/connection/connection_controller.dart';
import 'package:dzmm_mobile/connection/connection_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'connection/connection_store_test.dart'
    show MemoryPreferences, MemorySecrets;

void main() {
  testWidgets('navigates between connection and game shells', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          connectionStoreProvider.overrideWithValue(
            ConnectionStore(
              preferences: MemoryPreferences(),
              secrets: MemorySecrets(),
            ),
          ),
        ],
        child: const DzmmApp(),
      ),
    );

    expect(find.text('连接你的 Mac'), findsOneWidget);
    await tester.tap(find.text('跑团'));
    await tester.pumpAndSettle();

    expect(find.text('等待连接'), findsOneWidget);
  });
}

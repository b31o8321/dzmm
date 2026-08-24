import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:dzmm_next_mobile/local_host_port.dart';
import 'package:dzmm_next_mobile/widgets/operation_status.dart';

void main() {
  testWidgets('announces model stage and elapsed time to assistive tech', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: OperationStatusCard(
          stage: LocalHostOperationStage.generating,
          label: '正在生成后续故事',
          elapsedMs: 9200,
        ),
      ),
    );

    final semantics = tester.getSemantics(find.byType(OperationStatusCard));
    expect(semantics.label, '正在生成后续故事，已耗时 9.2 秒');
    expect(semantics.flagsCollection.isLiveRegion, isTrue);
    expect(find.byType(Wrap), findsNothing);
    expect(find.byType(SingleChildScrollView), findsOneWidget);
  });
}

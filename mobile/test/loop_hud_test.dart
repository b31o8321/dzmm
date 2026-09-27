import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:dzmm_mobile/widgets/loop_hud.dart';

void main() {
  testWidgets('renders nothing without clock and loop blocks', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(body: LoopHud(state: {}))),
    );
    expect(find.text('第 1 天 · 06:00 分钟'), findsNothing);
    expect(find.textContaining('循环'), findsNothing);
  });

  testWidgets('shows clock label, progress and loop badge', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LoopHud(state: {
            'clock': {
              'now_minutes': 600,
              'start_minutes': 360,
              'day': 1,
              'unit': '分钟',
            },
            'loop': {'count': 2, 'max_loops': 3},
          }),
        ),
      ),
    );
    expect(find.text('第 1 天 · 10:00 分钟'), findsOneWidget);
    expect(find.text('第 2/3 次循环'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
  });

  testWidgets('marks the final loop and warns at the boundary', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LoopHud(state: {
            'clock': {
              'now_minutes': 600,
              'start_minutes': 360,
              'loop_at_minutes': 600,
              'day': 1,
              'unit': '分钟',
            },
            'loop': {'count': 3, 'max_loops': 3},
          }),
        ),
      ),
    );
    expect(find.text('最终循环 3/3'), findsOneWidget);
    expect(find.text('已到达循环边界'), findsOneWidget);
  });

  testWidgets('lists cross-loop knowledge and summaries', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LoopHud(state: {
            'loop_memory': {
              'count': 2,
              'knowledge': [
                {'id': 'watchmaker-secret', 'text': '三座钟的齿轮'},
              ],
              'summaries': [
                {'loop_no': 1, 'summary': '玩家探索回廊后被拉回起点。'},
              ],
            },
          }),
        ),
      ),
    );
    expect(find.text('跨循环记忆'), findsOneWidget);
    expect(find.text('1 条知识 · 1 段循环摘要'), findsOneWidget);
    await tester.tap(find.text('跨循环记忆'));
    await tester.pumpAndSettle();
    expect(find.text('• 三座钟的齿轮'), findsOneWidget);
    expect(find.text('第 1 次循环：玩家探索回廊后被拉回起点。'), findsOneWidget);
  });
}

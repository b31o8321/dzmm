// v1.8 thematic-round emulator acceptance: the re-created summer-echo loop
// world through the real embedded Python runtime — clock advance, narrative
// turns, and LoopHud rendering, with a screenshot for review.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:dzmm_mobile/local_host_port.dart';
import 'package:dzmm_mobile/pages/play_page.dart';

Future<Map<String, dynamic>> _loadFixture(String name) async {
  final raw = await rootBundle.loadString('integration_test/fixtures/$name');
  return Map<String, dynamic>.from(jsonDecode(raw) as Map);
}

Future<void> _pumpUntil(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 60),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 200));
    final listFinder = find.byType(ListView);
    if (listFinder.evaluate().isNotEmpty) {
      await tester.drag(listFinder.first, const Offset(0, 20000));
    }
    await tester.pump(const Duration(milliseconds: 200));
    if (finder.evaluate().isNotEmpty) return;
  }
  final texts = tester
      .widgetList<Text>(find.byType(Text))
      .map((w) => w.data)
      .toList();
  fail('等待超时：${finder.describeMatch(Plurality.zero)}；当前文本：$texts');
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.fullyLive;

  Widget playPage(LocalHostPort port, String runId, int seed) => MaterialApp(
        home: PlayPage(
          key: ValueKey('play-$runId-$seed'),
          port: port,
          runId: runId,
          onStartNewRun: (_) async {},
          onReturnToWorlds: () {},
        ),
      );

  testWidgets('summer-echo loop world advances clock across turns on device', (
    tester,
  ) async {
    final port = EmbeddedPythonLocalHostPort();
    var ready = false;
    for (var attempt = 0; attempt < 30 && !ready; attempt++) {
      try {
        await port.runtimeHealth();
        ready = true;
      } catch (_) {
        await Future<void>.delayed(const Duration(seconds: 1));
      }
    }
    expect(ready, isTrue, reason: 'embedded python runtime never became healthy');

    final bundle = await _loadFixture('summer_echo.json');
    final composed = await port.importWorld({
      'request_id': 'thematic-summer-import',
      'bundle': bundle,
    });
    final runId = composed.runId;
    expect(runId, isNotEmpty);

    await tester.pumpWidget(playPage(port, runId, 0));
    await _pumpUntil(tester, find.textContaining('第 1 天 · 05:00'));
    expect(find.text('第 1/5 次循环'), findsOneWidget);

    // 三回合：每回合时钟 +30 分钟（预算内 narrate），断言 HUD 同步
    var revision = 0;
    for (var i = 0; i < 3; i++) {
      final run = await port.getRun(runId);
      revision = (run.state['revision'] as num).toInt();
      await port.playTurn(runId, {
        'request_id': 'thematic-summer-t$i',
        'expected_revision': revision,
        'player_input': '我在潮声栈桥观察海面，寻找「影」的痕迹。',
        'commands': [
          {'type': 'narrate', 'payload': {}},
        ],
      });
      final after = await port.getRun(runId);
      expect(after.state['clock'], isNotNull);
      final minutes = ((after.state['clock'] as Map)['now_minutes'] as num).toInt();
      expect(minutes, 300 + 30 * (i + 1), reason: 'turn $i clock advance');
    }

    // 重泵以渲染最新 HUD，断言第五回合时刻 05:00+150=07:30
    final fresh = await port.getRun(runId);
    final revisionNow = (fresh.state['revision'] as num).toInt();
    await tester.pumpWidget(playPage(port, runId, revisionNow));
    await _pumpUntil(tester, find.textContaining('第 1 天 · 06:30'));
    expect(find.text('第 1/5 次循环'), findsOneWidget);
    expect(find.text('跨循环记忆'), findsNothing, reason: '无知识注入时面板隐藏');

    await binding.convertFlutterSurfaceToImage();
    await binding.takeScreenshot('thematic_summer_echo');
    await Future<void>.delayed(const Duration(seconds: 1));
  });
}

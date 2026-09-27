// v1.5.0 emulator acceptance: time-loop rewind + countdown paths through the
// real embedded Python runtime, with screenshots for review.
import 'dart:convert';
import 'dart:io';

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

Future<void> _scrollListToTop(WidgetTester tester) async {
  final listFinder = find.byType(ListView);
  if (listFinder.evaluate().isNotEmpty) {
    await tester.drag(listFinder.first, const Offset(0, 20000));
    await tester.pumpAndSettle(const Duration(milliseconds: 500));
  }
}

Future<void> _pumpUntil(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 60),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 200));
    // 加载完成后页面会自动滚到底部；惰性 ListView 顶部的 HUD 需要拉回顶部才构建
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

  Widget playPage(LocalHostPort port, String runId, int seed) =>
      MaterialApp(
        home: PlayPage(
          key: ValueKey('play-$runId-$seed'),
          port: port,
          runId: runId,
          onStartNewRun: (_) async {},
          onReturnToWorlds: () {},
        ),
      );

  testWidgets('time-loop world rewinds and shows the cross-loop HUD', (
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

    final bundle = await _loadFixture('loop_world.json');
    final composed = await port.importWorld({
      'request_id': 'acc-loop-import',
      'bundle': bundle,
    });
    final runId = composed.runId;
    expect(runId, isNotEmpty);

    await tester.pumpWidget(playPage(port, runId, 0));
    await _scrollListToTop(tester);
    await _pumpUntil(tester, find.textContaining('第 1 天 · 06:00'));
    expect(find.text('第 1/3 次循环'), findsOneWidget);

    // discover + narrate → 时钟 360+30=390 ≥ loop_at 390 → 引擎 rewind
    final run = await port.getRun(runId);
    await port.playTurn(runId, {
      'request_id': 'acc-loop-turn-1',
      'expected_revision': run.state['revision'],
      'player_input': '我在回廊中辨认昨日的裂痕。',
      'commands': [
        {
          'type': 'discover',
          'payload': {'id': 'watchmaker-secret', 'text': '钟表匠的死与三座钟的齿轮有关'},
        },
        {'type': 'narrate', 'payload': {}},
      ],
    });

    final afterRewind = await port.getRun(runId);
    final revision = (afterRewind.state['revision'] as num).toInt();
    await tester.pumpWidget(playPage(port, runId, revision));
    await _scrollListToTop(tester);
    await _pumpUntil(
      tester,
      find.text('第 2/3 次循环'),
      timeout: const Duration(seconds: 60),
    );
    expect(find.textContaining('第 1 天 · 06:00'), findsOneWidget); // rewind 重置

    await tester.tap(find.text('跨循环记忆'));
    await tester.pumpAndSettle();
    expect(find.textContaining('钟表匠的死与三座钟的齿轮'), findsOneWidget);
    expect(find.textContaining('第 1 次循环：'), findsOneWidget);

    await binding.convertFlutterSurfaceToImage();
    await binding.takeScreenshot('loop_rewind_path');
    await Future<void>.delayed(const Duration(seconds: 1));
  });

  testWidgets('countdown world ticks down and warns', (tester) async {
    final port = EmbeddedPythonLocalHostPort();
    final bundle = await _loadFixture('countdown_world.json');
    final composed = await port.importWorld({
      'request_id': 'acc-countdown-import',
      'bundle': bundle,
    });
    final runId = composed.runId;

    await tester.pumpWidget(playPage(port, runId, 0));
    await _scrollListToTop(tester);
    await _pumpUntil(tester, find.textContaining('第 1 天 · 01:00'));

    final run = await port.getRun(runId);
    await port.playTurn(runId, {
      'request_id': 'acc-cd-turn-1',
      'expected_revision': run.state['revision'],
      'player_input': '我检查黯星余烬中残余的魔力储备。',
      'commands': [
        {
          'type': 'adjust_clock',
          'payload': {'delta': -20},
        },
        {'type': 'narrate', 'payload': {}},
      ],
    });

    final afterTick = await port.getRun(runId);
    final revision = (afterTick.state['revision'] as num).toInt();
    await tester.pumpWidget(playPage(port, runId, revision));
    await _scrollListToTop(tester);
    await _pumpUntil(
      tester,
      find.textContaining('第 1 天 · 00:10'),
      timeout: const Duration(seconds: 60),
    );
    expect(find.text('余量告急'), findsOneWidget);

    await binding.convertFlutterSurfaceToImage();
    await binding.takeScreenshot('countdown_path');
    await Future<void>.delayed(const Duration(seconds: 1));
  });
}

// 引用以避免未使用导入告警
// ignore: unused_element
final _ = Platform.operatingSystem;

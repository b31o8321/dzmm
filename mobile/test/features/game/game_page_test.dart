import 'dart:async';

import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/api/sse_client.dart';
import 'package:dzmm_mobile/features/game/game_page.dart';
import 'package:dzmm_mobile/features/game/turn_run_client.dart';
import 'package:dzmm_mobile/features/sessions/session_models.dart';
import 'package:dzmm_mobile/features/sessions/session_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('hydrates history and exposes compact player state', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: GamePage(
          session: const GameSessionSummary(id: 4, name: '雾港', turnCount: 2),
          repository: SessionRepository(FakeHydrationTransport()),
          turnClient: TurnRunClient(transport: CompletedTurnTransport()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('打开舱门'), findsOneWidget);
    expect(find.textContaining('潮湿的风'), findsOneWidget);
    expect(find.textContaining('守门人'), findsOneWidget);
    await tester.tap(find.byTooltip('角色与世界状态'));
    await tester.pumpAndSettle();
    expect(find.textContaining('生命与状态'), findsOneWidget);
    expect(find.textContaining('钥匙'), findsOneWidget);
    expect(find.textContaining('找到出口'), findsOneWidget);
    expect(find.textContaining('当前位置'), findsOneWidget);
  });

  testWidgets('streams one action and prevents a duplicate send', (
    tester,
  ) async {
    final transport = StreamingTurnTransport();
    await tester.pumpWidget(
      MaterialApp(
        home: GamePage(
          session: const GameSessionSummary(id: 4, name: '雾港', turnCount: 2),
          repository: SessionRepository(FakeHydrationTransport()),
          turnClient: TurnRunClient(transport: transport, delay: (_) async {}),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '倾听门后');
    await tester.tap(find.byTooltip('发送行动'));
    await tester.pump();
    await tester.pump();

    expect(find.text('倾听门后'), findsOneWidget);
    expect(find.textContaining('你听见脚步'), findsOneWidget);
    expect(transport.createCalls, 1);
    final sendButton = tester.widget<IconButton>(
      find.byWidgetPredicate(
        (widget) => widget is IconButton && widget.tooltip == '发送行动',
      ),
    );
    expect(sendButton.onPressed, isNull);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(transport.readCalls, greaterThanOrEqualTo(2));

    transport.finish.complete();
    await tester.pumpAndSettle();
    expect(transport.createCalls, 1);
  });

  testWidgets('a 500-message save builds history lazily', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: GamePage(
          session: const GameSessionSummary(
            id: 4,
            name: '长篇存档',
            turnCount: 250,
          ),
          repository: SessionRepository(LargeHydrationTransport()),
          turnClient: TurnRunClient(transport: CompletedTurnTransport()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('长篇存档'), findsOneWidget);
    expect(find.textContaining('叙事 499'), findsOneWidget);
    expect(find.byType(MarkdownBody).evaluate().length, lessThan(30));
  });
}

class FakeHydrationTransport implements SessionTransport {
  @override
  Future<Object?> get(
    String path, {
    CancellationToken? cancellationToken,
  }) async => switch (path) {
    '/sessions/4' => {'id': 4, 'name': '雾港', 'turn_count': 2},
    '/sessions/4/messages' => [
      {'id': 1, 'role': 'user', 'content': '打开舱门', 'turn': 1},
      {
        'id': 2,
        'role': 'assistant',
        'content':
            '<narrative>潮湿的风扑面而来。</narrative>'
            '<say speaker="守门人">别进去。</say>',
        'turn': 1,
      },
    ],
    '/sessions/4/state' => {
      'vitals': {'hp': 8, 'max_hp': 10},
      'inventory_v2': [
        {'name': '钥匙', 'qty': 1},
      ],
      'npcs': [
        {'name': '守门人'},
      ],
      'threads': [
        {'description': '进入船舱'},
      ],
    },
    '/sessions/4/goals' => [
      {'description': '找到出口', 'status': 'active'},
    ],
    '/sessions/4/locations' => [
      {'name': '船舱', 'is_current': true},
    ],
    _ => throw StateError('Unexpected $path'),
  };
}

class LargeHydrationTransport implements SessionTransport {
  @override
  Future<Object?> get(
    String path, {
    CancellationToken? cancellationToken,
  }) async => switch (path) {
    '/sessions/4' => {'id': 4, 'name': '长篇存档', 'turn_count': 250},
    '/sessions/4/messages' => List.generate(
      500,
      (index) => {
        'id': index + 1,
        'role': index.isEven ? 'user' : 'assistant',
        'content': index.isEven
            ? '行动 $index'
            : '<narrative>叙事 $index</narrative>',
        'turn': (index ~/ 2) + 1,
      },
    ),
    '/sessions/4/state' => <String, Object?>{},
    '/sessions/4/goals' => <Object?>[],
    '/sessions/4/locations' => <Object?>[],
    _ => throw StateError('Unexpected $path'),
  };
}

TurnRunRecord _record(String status) => TurnRunRecord.fromJson({
  'run_id': 'run-4',
  'request_id': 'request-4',
  'status': status,
  'error_code': null,
  'error_message': null,
});

class CompletedTurnTransport implements TurnRunTransport {
  @override
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  }) async => _record('completed');

  @override
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  }) => const Stream.empty();

  @override
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) async => _record('completed');
}

class StreamingTurnTransport implements TurnRunTransport {
  final finish = Completer<void>();
  var createCalls = 0;
  var readCalls = 0;

  @override
  Future<TurnRunRecord> create(
    int sessionId,
    String requestId,
    String action, {
    CancellationToken? cancellationToken,
  }) async {
    createCalls += 1;
    return _record('running');
  }

  @override
  Stream<SseEvent> events(
    int sessionId,
    String runId, {
    required int lastEventId,
    CancellationToken? cancellationToken,
  }) async* {
    yield const SseEvent(id: 1, event: 'narrative', data: '{"text":"你听见脚步。"}');
    await finish.future;
  }

  @override
  Future<TurnRunRecord> read(
    int sessionId,
    String runId, {
    CancellationToken? cancellationToken,
  }) async {
    readCalls += 1;
    return _record(readCalls == 1 ? 'running' : 'completed');
  }
}

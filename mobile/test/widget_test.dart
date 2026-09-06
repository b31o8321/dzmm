import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:dzmm_mobile/local_host_port.dart';
import 'package:dzmm_mobile/main.dart';
import 'package:dzmm_mobile/session_store.dart';

class _MemoryStore implements SessionStore {
  LocalSession session = const LocalSession();
  String theme = 'fog';

  @override
  Future<LocalSession> read() async => session;

  @override
  Future<void> save(LocalSession value) async => session = value;

  @override
  Future<String?> readTheme() async => theme;

  @override
  Future<void> saveTheme(String value) async => theme = value;
}

class _FakePort implements LocalHostPort {
  @override
  Future<Map<String, dynamic>> runtimeHealth() async => {
    'runtime': 'fake',
    'storage': 'memory',
  };

  @override
  Future<List<WorldSummary>> listWorlds() async => const [];

  @override
  Future<WorldDetail> getWorld(String worldId) => throw UnimplementedError();

  @override
  Future<void> archiveWorld(String worldId) => throw UnimplementedError();

  @override
  Future<void> restoreWorld(String worldId) => throw UnimplementedError();

  @override
  Future<void> deleteWorld(String worldId) => throw UnimplementedError();

  @override
  Future<ComposeResult> createRun(
    String worldId,
    Map<String, dynamic> payload,
  ) => throw UnimplementedError();

  @override
  Future<Map<String, dynamic>> exportWorld(String worldId) =>
      throw UnimplementedError();

  @override
  Future<ComposeResult> importWorld(Map<String, dynamic> payload) =>
      throw UnimplementedError();

  @override
  Future<Map<String, dynamic>> exportRun(String runId) =>
      throw UnimplementedError();

  @override
  Future<ComposeResult> cloneRun(Map<String, dynamic> payload) =>
      throw UnimplementedError();

  @override
  Future<Map<String, dynamic>> worldTemplate() async => {};

  @override
  Future<List<ModelProfile>> listModelProfiles() async => const [
    ModelProfile(
      id: 'fake-model',
      name: '测试模型',
      providerType: 'ollama',
      baseUrl: 'http://127.0.0.1:11434',
      modelName: 'qwen:7b',
      isDefault: true,
    ),
  ];

  @override
  Future<ModelProfile> createModelProfile(Map<String, dynamic> profile) =>
      throw UnimplementedError();

  @override
  Future<ModelProfile> updateModelProfile(
    String profileId,
    Map<String, dynamic> profile,
  ) => throw UnimplementedError();

  @override
  Future<ModelProfile> setDefaultModelProfile(String profileId) =>
      throw UnimplementedError();

  @override
  Future<void> deleteModelProfile(String profileId) =>
      throw UnimplementedError();

  @override
  Future<ModelProbeResult> probeModelProfile(String profileId) =>
      throw UnimplementedError();

  @override
  Future<AIWorldDraft> generateDraft(Map<String, dynamic> brief) =>
      throw UnimplementedError();

  @override
  Future<AIWorldDraft> validateDraft(Map<String, dynamic> draft) =>
      throw UnimplementedError();

  @override
  Future<ComposeResult> composeWorld(Map<String, dynamic> payload) =>
      throw UnimplementedError();

  @override
  Future<RunSnapshot> getRun(String runId) => throw UnimplementedError();

  @override
  Future<RunSnapshot> choose(String runId, Map<String, dynamic> payload) =>
      throw UnimplementedError();

  @override
  Future<RunSnapshot> playTurn(String runId, Map<String, dynamic> payload) =>
      throw UnimplementedError();

  @override
  Future<bool> cancelOperation(String requestId) async => false;

  @override
  Future<RunSnapshot> rollback(String runId, Map<String, dynamic> payload) =>
      throw UnimplementedError();
}

class _WorldFlowPort extends _FakePort {
  @override
  Future<List<WorldSummary>> listWorlds() async => const [
    WorldSummary(
      id: 'world-1',
      name: '雾港',
      status: 'active',
      runCount: 1,
      latestRunId: 'run-1',
    ),
  ];

  @override
  Future<WorldDetail> getWorld(String worldId) async => const WorldDetail(
    id: 'world-1',
    name: '雾港',
    status: 'active',
    worldVersionId: 'version-1',
    runs: [RunSummary(id: 'run-1', heroName: '米拉', revision: 0)],
  );

  @override
  Future<RunSnapshot> getRun(String runId) async => RunSnapshot({
    'run_id': runId,
    'state': {'revision': 0, 'ending': null},
    'story_beats': [
      {
        'kind': 'opening',
        'title': '潮雾抵港',
        'location': '雾港码头',
        'narrative': '米拉抵达雾港码头，故事从此刻开始。',
        'dialogue': {'speaker': '岚', 'text': '别让这里替你作出第一个决定。'},
        'objective': '确认眼前的局势。',
        'guidance': '你可以选择救岚。',
      },
    ],
    'available_choices': [
      {'id': 'rescue-lan', 'label': '救岚'},
    ],
    'turns': <Map<String, dynamic>>[],
  });
}

class _ArchiveFlowPort extends _WorldFlowPort {
  bool archived = false;

  @override
  Future<List<WorldSummary>> listWorlds() async => [
    WorldSummary(
      id: 'world-1',
      name: '雾港',
      status: archived ? 'archived' : 'active',
      runCount: 1,
      latestRunId: 'run-1',
    ),
  ];

  @override
  Future<WorldDetail> getWorld(String worldId) async => WorldDetail(
    id: 'world-1',
    name: '雾港',
    status: archived ? 'archived' : 'active',
    worldVersionId: 'version-1',
    runs: const [RunSummary(id: 'run-1', heroName: '米拉', revision: 0)],
  );

  @override
  Future<void> archiveWorld(String worldId) async => archived = true;

  @override
  Future<void> restoreWorld(String worldId) async => archived = false;
}

class _DeleteFlowPort extends _ArchiveFlowPort {
  bool deleted = false;

  @override
  Future<List<WorldSummary>> listWorlds() async => deleted
      ? const []
      : [
          WorldSummary(
            id: 'world-1',
            name: '雾港',
            status: 'active',
            runCount: 2,
            latestRunId: 'run-1',
          ),
        ];

  @override
  Future<void> deleteWorld(String worldId) async => deleted = true;
}

class _FreeActionPort extends _WorldFlowPort {
  Map<String, dynamic>? turnPayload;

  @override
  Future<RunSnapshot> getRun(String runId) async => RunSnapshot({
    'run_id': runId,
    'world_id': 'world-1',
    'state': {'revision': 0, 'ending': null, 'location_id': 'harbor'},
    'presentation': {
      'locations': {'harbor': '雾港码头', 'lighthouse': '旧灯塔'},
    },
    'story_beats': [
      {
        'kind': 'opening',
        'title': '自由航路',
        'location': '雾港外海',
        'narrative': '海面没有预设航线，旅人可以描述自己的行动。',
        'objective': '决定下一步行动。',
        'guidance': '写下你想尝试的事。',
      },
    ],
    'available_choices': <Map<String, dynamic>>[],
    'turns': <Map<String, dynamic>>[],
  });

  @override
  Future<RunSnapshot> playTurn(
    String runId,
    Map<String, dynamic> payload,
  ) async {
    turnPayload = payload;
    return getRun(runId);
  }
}

class _DelayedChoicePort extends _WorldFlowPort {
  final choiceCompleter = Completer<RunSnapshot>();
  bool throwOnCancel = false;

  @override
  Future<RunSnapshot> choose(String runId, Map<String, dynamic> payload) =>
      choiceCompleter.future;

  @override
  Future<bool> cancelOperation(String requestId) async {
    if (throwOnCancel) throw StateError('cancel transport unavailable');
    return true;
  }
}

class _DelayedDraftPort extends _FakePort {
  final draftCompleter = Completer<AIWorldDraft>();
  int composeCalls = 0;
  bool throwOnCancel = false;

  @override
  Future<List<ModelProfile>> listModelProfiles() async => const [
    ModelProfile(
      id: 'local-model',
      name: '本地模型',
      providerType: 'ollama',
      baseUrl: 'http://127.0.0.1:11434',
      modelName: 'qwen2.5:7b',
    ),
  ];

  @override
  Future<AIWorldDraft> generateDraft(Map<String, dynamic> brief) =>
      draftCompleter.future;

  @override
  Future<bool> cancelOperation(String requestId) async {
    if (throwOnCancel) throw StateError('cancel transport unavailable');
    return false;
  }

  @override
  Future<ComposeResult> composeWorld(Map<String, dynamic> payload) async {
    composeCalls += 1;
    throw StateError('compose should not be called after cancellation');
  }
}

class _EditableDraftPort extends _FakePort {
  String? validatedWorldName;
  int generateCalls = 0;

  @override
  Future<List<ModelProfile>> listModelProfiles() async => const [
    ModelProfile(
      id: 'local-model',
      name: '本地模型',
      providerType: 'ollama',
      baseUrl: 'http://127.0.0.1:11434',
      modelName: 'qwen2.5:7b',
    ),
  ];

  @override
  Future<AIWorldDraft> generateDraft(Map<String, dynamic> brief) async {
    generateCalls += 1;
    return const AIWorldDraft(
      valid: true,
      summary: 'draft',
      worldDefinition: {
        'schema_version': 3,
        'name': '原世界',
        'locations': [
          {'name': '月光港'},
        ],
        'character_cards': [
          {'name': '艾莉'},
        ],
        'npcs': [
          {'name': '老渔夫汤姆'},
        ],
        'factions': [
          {'name': '月影协会'},
        ],
        'events': [
          {'name': '月圆之夜'},
        ],
      },
      hero: {'name': '原主角'},
      repairs: [],
      issues: [],
    );
  }

  @override
  Future<AIWorldDraft> validateDraft(Map<String, dynamic> draft) async {
    final definition = Map<String, dynamic>.from(
      draft['world_definition'] as Map,
    );
    final hero = Map<String, dynamic>.from(draft['hero'] as Map);
    validatedWorldName = definition['name'] as String;
    return AIWorldDraft(
      valid: true,
      summary: 'validated',
      worldDefinition: definition,
      hero: hero,
      repairs: const [],
      issues: const [],
    );
  }
}

class _ModelManagementPort extends _FakePort {
  @override
  Future<List<ModelProfile>> listModelProfiles() async => const [
    ModelProfile(
      id: 'default-model',
      name: '默认模型',
      providerType: 'ollama',
      baseUrl: 'http://127.0.0.1:11434',
      modelName: 'qwen:7b',
      isDefault: true,
    ),
    ModelProfile(
      id: 'backup-model',
      name: '备用模型',
      providerType: 'lm_studio',
      baseUrl: 'http://127.0.0.1:1234/v1',
      modelName: 'qwen-14b',
    ),
  ];
}

class _DelayedProbePort extends _ModelManagementPort {
  final probeCompleter = Completer<ModelProbeResult>();

  @override
  Future<ModelProbeResult> probeModelProfile(String profileId) =>
      probeCompleter.future;
}

class _EndedRunPort extends _WorldFlowPort {
  @override
  Future<RunSnapshot> getRun(String runId) async => RunSnapshot({
    'run_id': runId,
    'world_id': 'world-1',
    'status': 'completed',
    'state': {
      'revision': 3,
      'ending': {'id': 'lan-dawn', 'kind': 'good'},
      'route': {'id': 'lan-route', 'status': 'locked'},
      'inventory': [
        {'id': 'fog-lantern', 'quantity': 1},
      ],
      'relationships': {
        'lan': {
          'dimensions': {'affection': 45, 'trust': 40},
          'applied_events': <String, dynamic>{},
        },
      },
    },
    'presentation': {
      'routes': {'lan-route': '岚路线'},
      'resources': {'fog-lantern': '雾灯'},
      'relationships': {'lan': '岚'},
    },
    'story_beats': [
      {
        'kind': 'ending',
        'title': '结局 · 好结局',
        'location': '雾港码头',
        'narrative': '潮声渐远，这段旅程已经抵达结局。',
        'dialogue': null,
        'objective': '这段旅程已经抵达正式结局。',
        'guidance': '你可以从同一个世界开始新的旅程。',
      },
    ],
    'available_choices': <Map<String, dynamic>>[],
    'turns': [
      {'id': 'turn-1', 'kind': 'turn', 'player_input': '点亮雾灯', 'sequence': 3},
      {
        'id': 'rollback-1',
        'kind': 'rollback',
        'player_input': '回滚到第 3 回合之后',
        'sequence': 4,
        'rollback_target_id': 'turn-1',
      },
    ],
  });
}

void main() {
  test('maps model draft parser failures to player-safe guidance', () {
    expect(
      playerSafeDraftError(
        "model draft is not valid JSON: Expecting ',' delimiter",
      ),
      '模型返回的世界草案格式不完整，未创建世界。请重试或切换模型。',
    );
    expect(
      playerSafeDraftError('model returned no draft content'),
      '模型没有返回世界草案，未创建世界。请重试或切换模型。',
    );
  });

  test(
    'RunSnapshot treats a model response without choices as free action',
    () {
      final snapshot = RunSnapshot({
        'run_id': 'run-1',
        'world_id': 'world-1',
        'state': {'revision': 3, 'ending': null},
        'story_beats': [
          {'kind': 'turn', 'title': '潮门之夜', 'narrative': '模型返回了正文，但没有结构化选项。'},
        ],
        'turns': <Map<String, dynamic>>[],
      });

      expect(snapshot.availableChoices, isEmpty);
      expect(snapshot.storyBeats.single['title'], '潮门之夜');
    },
  );

  testWidgets('shows local-first navigation without host discovery controls', (
    tester,
  ) async {
    await tester.pumpWidget(
      DzmmMobileApp(port: _FakePort(), sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();

    expect(find.text('DZMM'), findsOneWidget);
    expect(find.text('本机游戏服务已就绪 · 存档只保存在此设备'), findsOneWidget);
    expect(find.text('世界'), findsOneWidget);
    expect(find.text('创作'), findsOneWidget);
    expect(find.text('模型'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
    expect(find.text('配对'), findsNothing);
    expect(find.text('扫描'), findsNothing);
  });

  testWidgets(
    'reopens with an explanation after an interrupted Run operation',
    (tester) async {
      final store = _MemoryStore()
        ..session = const LocalSession(
          runId: 'run-1',
          pendingRunOperation: true,
        );
      await tester.pumpWidget(
        DzmmMobileApp(port: _WorldFlowPort(), sessionStore: store),
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('上一次旅程操作在应用关闭前没有完成'), findsOneWidget);
      expect((await store.read()).pendingRunOperation, isFalse);
      expect(find.text('米拉抵达雾港码头，故事从此刻开始。'), findsOneWidget);
    },
  );

  testWidgets('settings exposes local themes', (tester) async {
    await tester.pumpWidget(
      DzmmMobileApp(port: _FakePort(), sessionStore: _MemoryStore()),
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();

    expect(find.textContaining('旧版 DZMM 存档不会自动迁移'), findsOneWidget);
    expect(find.text('雾夜'), findsOneWidget);
    expect(find.text('纸页'), findsOneWidget);
    expect(find.text('琥珀'), findsOneWidget);
  });

  testWidgets('world card opens an existing run and shows a real opening', (
    tester,
  ) async {
    await tester.pumpWidget(
      DzmmMobileApp(port: _WorldFlowPort(), sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    expect(find.text('1 段旅程；同一个世界可以重复游玩，彼此存档独立。'), findsOneWidget);
    expect(find.text('米拉'), findsOneWidget);
    expect(find.text('导出世界包'), findsOneWidget);

    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();
    expect(find.text('潮雾抵港'), findsOneWidget);
    expect(find.text('米拉抵达雾港码头，故事从此刻开始。'), findsOneWidget);
    expect(find.text('岚：别让这里替你作出第一个决定。'), findsOneWidget);
    expect(find.text('确认眼前的局势。'), findsOneWidget);
    expect(find.text('你可以选择救岚。'), findsOneWidget);
    expect(find.text('救岚'), findsOneWidget);
    expect(find.text('记录行动'), findsNothing);
    expect(find.text('Python 已裁定'), findsNothing);
  });

  testWidgets('archived worlds keep existing runs view-only', (tester) async {
    final port = _ArchiveFlowPort()..archived = true;
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();

    expect(find.text('世界已归档，暂不可开始'), findsOneWidget);
    final runTile = tester.widget<ListTile>(
      find.widgetWithText(ListTile, '米拉'),
    );
    expect(runTile.enabled, isFalse);
    expect(runTile.onTap, isNull);
    expect(find.text('世界已归档'), findsOneWidget);
  });

  testWidgets('world archive is reversible and blocks a new Run', (
    tester,
  ) async {
    final port = _ArchiveFlowPort();
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('归档世界'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '归档'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    expect(find.text('世界已归档，暂不可开始'), findsOneWidget);
    expect(find.text('恢复世界'), findsOneWidget);
    await tester.tap(find.text('恢复世界'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    expect(find.text('开始新旅程'), findsOneWidget);
    expect(find.text('旅程进行中'), findsOneWidget);
    expect(find.textContaining('状态版本'), findsNothing);
  });

  testWidgets('world deletion confirms and removes the world with its runs', (
    tester,
  ) async {
    final port = _DeleteFlowPort();
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();

    expect(find.text('删除世界及全部旅程'), findsOneWidget);
    await tester.tap(find.text('删除世界及全部旅程'));
    await tester.pumpAndSettle();
    expect(find.text('永久删除这个世界？'), findsOneWidget);
    expect(find.textContaining('及其 2 段旅程、回合记录和历史内容都会从本机删除'), findsOneWidget);
    await tester.tap(find.text('删除世界及旅程'));
    await tester.pumpAndSettle();

    expect(port.deleted, isTrue);
    expect(find.text('还没有世界。从雾港模板或 AI 草案开始。'), findsOneWidget);
  });

  testWidgets(
    'free action input only appears when there are no valid choices',
    (tester) async {
      final port = _FreeActionPort();
      await tester.pumpWidget(
        DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('雾港'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('继续'));
      await tester.pumpAndSettle();

      expect(find.text('记录行动'), findsOneWidget);
      expect(find.text('目的地'), findsOneWidget);
      expect(find.text('提交行动'), findsOneWidget);

      final destination = tester.widget<DropdownButtonFormField<String>>(
        find.byType(DropdownButtonFormField<String>),
      );
      destination.onChanged?.call('lighthouse');
      await tester.enterText(
        find.widgetWithText(TextField, '记录行动'),
        '去旧灯塔调查灯号',
      );
      await tester.ensureVisible(find.text('提交行动'));
      await tester.tap(find.text('提交行动'));
      await tester.pumpAndSettle();
      expect(port.turnPayload?['commands'], [
        {
          'type': 'move',
          'payload': {'location_id': 'lighthouse'},
        },
        {'type': 'narrate', 'payload': {}},
      ]);
    },
  );

  testWidgets('play keeps model progress visible until the choice completes', (
    tester,
  ) async {
    final port = _DelayedChoicePort();
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('救岚'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('正在生成后续故事；成功前不会写入半个回合。'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.text('连接模型'), findsOneWidget);
    expect(find.text('生成叙事'), findsOneWidget);
    expect(find.text('状态写入'), findsOneWidget);

    port.choiceCompleter.complete(await port.getRun('run-1'));
    await tester.pumpAndSettle();
    expect(find.text('正在生成后续故事；成功前不会写入半个回合。'), findsNothing);
  });

  testWidgets('player can cancel a slow turn without losing the current Run', (
    tester,
  ) async {
    final port = _DelayedChoicePort();
    final store = _MemoryStore();
    await tester.pumpWidget(DzmmMobileApp(port: port, sessionStore: store));
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('救岚'));
    await tester.pump(const Duration(milliseconds: 50));
    await tester.tap(find.text('取消本次行动'));
    await tester.pumpAndSettle();

    expect(find.textContaining('原旅程没有改变'), findsOneWidget);
    expect(find.text('重试上次行动'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);
    expect((await store.read()).pendingRunOperation, isFalse);
  });

  testWidgets('failed turn cancellation keeps the operation recoverable', (
    tester,
  ) async {
    final port = _DelayedChoicePort()..throwOnCancel = true;
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('雾港'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('救岚'));
    await tester.pump(const Duration(milliseconds: 50));
    await tester.tap(find.text('取消本次行动'));
    await tester.pump();
    expect(find.textContaining('取消未送达'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);

    port.throwOnCancel = false;
    port.choiceCompleter.complete(await port.getRun('run-1'));
    await tester.pumpAndSettle();
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });

  testWidgets('model settings expose edit delete and default controls', (
    tester,
  ) async {
    await tester.pumpWidget(
      DzmmMobileApp(port: _ModelManagementPort(), sessionStore: _MemoryStore()),
    );
    await tester.tap(find.text('模型'));
    await tester.pumpAndSettle();

    expect(find.text('默认模型'), findsOneWidget);
    expect(find.text('默认'), findsOneWidget);
    expect(find.text('编辑'), findsNWidgets(2));
    expect(find.text('删除'), findsNWidgets(2));
    expect(find.text('设为默认'), findsOneWidget);
    expect(find.text('测试连接'), findsNWidgets(2));
  });

  testWidgets('model probe keeps a visible operation status until it returns', (
    tester,
  ) async {
    final port = _DelayedProbePort();
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.tap(find.text('模型'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('测试连接').first);
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.text('正在连接本地模型…'), findsOneWidget);

    port.probeCompleter.complete(
      const ModelProbeResult(
        success: true,
        endpoint: 'http://127.0.0.1:11434/api/chat',
        detail: 'protocol response contains content',
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byType(LinearProgressIndicator), findsNothing);
    expect(
      find.textContaining('可用 · protocol response contains content'),
      findsOneWidget,
    );
  });

  testWidgets('model setup explains missing fields before calling the host', (
    tester,
  ) async {
    await tester.pumpWidget(
      DzmmMobileApp(port: _FakePort(), sessionStore: _MemoryStore()),
    );
    await tester.tap(find.text('模型'));
    await tester.pumpAndSettle();

    await tester.drag(find.byType(ListView).first, const Offset(0, -420));
    await tester.pump();
    await tester.tap(find.text('保存模型档案'));
    await tester.pump();

    expect(find.text('请输入模型名'), findsOneWidget);
  });

  testWidgets(
    'model provider selection updates the complete connection preset',
    (tester) async {
      await tester.pumpWidget(
        DzmmMobileApp(port: _FakePort(), sessionStore: _MemoryStore()),
      );
      await tester.tap(find.text('模型'));
      await tester.pumpAndSettle();
      final provider = tester.widget<DropdownButtonFormField<String>>(
        find.byType(DropdownButtonFormField<String>),
      );
      provider.onChanged?.call('lm_studio');
      await tester.pump();

      final baseUrl = tester.widget<TextField>(
        find.widgetWithText(TextField, 'Base URL'),
      );
      expect(baseUrl.controller?.text, 'http://127.0.0.1:1234/v1');
    },
  );

  testWidgets('ended run has a formal summary and replay exits', (
    tester,
  ) async {
    final store = _MemoryStore()..session = const LocalSession(runId: 'run-1');
    await tester.pumpWidget(
      DzmmMobileApp(port: _EndedRunPort(), sessionStore: store),
    );
    await tester.pumpAndSettle();

    expect(find.text('旅程完成 · 好结局'), findsOneWidget);
    expect(find.text('潮声渐远，这段旅程已经抵达结局。'), findsOneWidget);
    expect(find.text('从同一世界开始新旅程'), findsOneWidget);
    expect(find.text('这段旅程留下了'), findsOneWidget);
    expect(find.text('最终路线：岚路线'), findsOneWidget);
    expect(find.text('持有物品：雾灯 ×1'), findsOneWidget);
    expect(find.text('人物关系：岚：好感 45、信任 40'), findsOneWidget);
    expect(find.text('• 点亮雾灯'), findsOneWidget);
    expect(find.text('这段旅程已正式结算，共完成 1 个回合。'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('已恢复至第 3 回合之后'), 300);
    expect(find.text('已恢复至第 3 回合之后'), findsOneWidget);
    expect(find.text('• 回滚到第 3 回合之后'), findsNothing);
    expect(find.text('返回世界'), findsOneWidget);
    expect(find.textContaining('正式结算'), findsOneWidget);
  });

  testWidgets(
    'cancelling an AI draft ignores the model result and does not compose',
    (tester) async {
      final port = _DelayedDraftPort();
      await tester.pumpWidget(
        DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
      );
      await tester.tap(find.text('创作'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('生成待审阅草案'));
      await tester.pump();
      expect(find.text('取消起草'), findsOneWidget);
      expect(
        find.byType(LinearProgressIndicator, skipOffstage: false),
        findsOneWidget,
      );
      expect(find.text('连接模型', skipOffstage: false), findsOneWidget);
      expect(find.text('生成叙事', skipOffstage: false), findsOneWidget);

      await tester.drag(find.byType(Scrollable).first, const Offset(0, -260));
      // The operation clock intentionally keeps scheduling frames while the model is pending.
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tap(find.text('取消起草'));
      port.draftCompleter.complete(
        const AIWorldDraft(
          valid: true,
          summary: 'late result',
          worldDefinition: {'schema_version': 3},
          hero: {'name': 'late'},
          repairs: [],
          issues: [],
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('已取消本次起草；没有创建世界、旅程或其他存档。'), findsOneWidget);
      expect(find.text('late result'), findsNothing);
      expect(port.composeCalls, 0);
    },
  );

  testWidgets(
    'AI draft cancellation remains recoverable when the cancel transport fails',
    (tester) async {
      final port = _DelayedDraftPort()..throwOnCancel = true;
      await tester.pumpWidget(
        DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
      );
      await tester.tap(find.text('创作'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('生成待审阅草案'));
      await tester.pump();
      await tester.drag(find.byType(Scrollable).first, const Offset(0, -260));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.ensureVisible(find.text('取消起草'));
      await tester.tap(find.text('取消起草'));
      await tester.pumpAndSettle();

      expect(find.text('已停止等待本次起草；没有创建世界、旅程或其他存档。'), findsOneWidget);
      port.draftCompleter.complete(
        const AIWorldDraft(
          valid: true,
          summary: 'late result',
          worldDefinition: {'schema_version': 3},
          hero: {'name': 'late'},
          repairs: [],
          issues: [],
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('late result'), findsNothing);
      expect(port.composeCalls, 0);
    },
  );

  testWidgets('structured draft edits must be revalidated by the local core', (
    tester,
  ) async {
    final port = _EditableDraftPort();
    await tester.pumpWidget(
      DzmmMobileApp(port: port, sessionStore: _MemoryStore()),
    );
    await tester.tap(find.text('创作'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('生成待审阅草案'));
    await tester.pumpAndSettle();

    expect(port.generateCalls, 1);
    await tester.drag(find.byType(ListView), const Offset(0, -500));
    await tester.pumpAndSettle();
    expect(find.text('草案已通过本机规则校验'), findsOneWidget);
    expect(find.text('生成素材摘要'), findsOneWidget);
    expect(find.text('地点：月光港'), findsOneWidget);
    expect(find.text('角色/NPC：艾莉、老渔夫汤姆'), findsOneWidget);
    expect(find.text('势力：月影协会'), findsOneWidget);
    expect(find.text('事件：月圆之夜'), findsOneWidget);
    expect(
      find.textContaining('章节、选项、关系、路线和结局由本机 hybrid 规则校验'),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('draft-world-name')), findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('draft-world-name')),
      '新世界',
    );
    await tester.ensureVisible(find.text('验证编辑'));
    await tester.tap(find.text('验证编辑'));
    await tester.pumpAndSettle();

    expect(port.validatedWorldName, '新世界');
    expect(find.text('草案已通过本机规则校验'), findsOneWidget);
  });
}

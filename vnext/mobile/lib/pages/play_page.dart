import 'dart:async';

import 'package:flutter/material.dart';

import '../local_host_port.dart';
import '../widgets/operation_status.dart';
import '../widgets/runtime_error.dart';

bool shouldResetRetriableAction(String? previousRunId, String nextRunId) =>
    previousRunId != nextRunId;

class PlayPage extends StatefulWidget {
  const PlayPage({
    super.key,
    required this.port,
    required this.runId,
    required this.onStartNewRun,
    required this.onReturnToWorlds,
    this.onPendingRunOperation,
  });

  final LocalHostPort port;
  final String? runId;
  final Future<void> Function(String) onStartNewRun;
  final VoidCallback onReturnToWorlds;
  final Future<void> Function(bool pending)? onPendingRunOperation;

  @override
  State<PlayPage> createState() => _PlayPageState();
}

class _PlayPageState extends State<PlayPage> {
  RunSnapshot? _run;
  String? _error;
  bool _busy = false;
  String _operationStage = LocalHostOperationStage.preparing;
  String? _operationLabel;
  int _operationElapsedMs = 0;
  Timer? _operationTicker;
  DateTime? _operationStartedAt;
  String? _activeRequestId;
  String? _destination;
  Future<void> Function()? _retryAction;
  final _action = TextEditingController();
  final _storyScroll = ScrollController();

  Future<void> _markPendingRunOperation(bool pending) async {
    try {
      await widget.onPendingRunOperation?.call(pending);
    } catch (_) {
      // A recovery marker must never prevent a player action from running.
    }
  }

  @override
  void initState() {
    super.initState();
    if (widget.runId != null) _load();
  }

  @override
  void dispose() {
    _operationTicker?.cancel();
    _action.dispose();
    _storyScroll.dispose();
    super.dispose();
  }

  void _scrollToLatest() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_storyScroll.hasClients) return;
      _storyScroll.animateTo(
        _storyScroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOutCubic,
      );
    });
  }

  void _beginOperation(
    String label, {
    String stage = LocalHostOperationStage.preparing,
  }) {
    _operationTicker?.cancel();
    _operationStartedAt = DateTime.now();
    setState(() {
      _operationLabel = label;
      _operationStage = stage;
      _operationElapsedMs = 0;
    });
    _operationTicker = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (!mounted || _operationStartedAt == null) return;
      setState(() {
        _operationElapsedMs = DateTime.now()
            .difference(_operationStartedAt!)
            .inMilliseconds;
      });
    });
  }

  void _advanceOperation(String stage, String label) {
    if (mounted) {
      setState(() {
        _operationStage = stage;
        _operationLabel = label;
      });
    }
  }

  Future<void> _showModelGeneration() async {
    _advanceOperation(LocalHostOperationStage.connecting, '正在连接本机模型…');
    await Future<void>.delayed(const Duration(milliseconds: 16));
    if (mounted) {
      _advanceOperation(
        LocalHostOperationStage.generating,
        '正在生成后续故事；成功前不会写入半个回合。',
      );
    }
  }

  void _endOperation() {
    _operationTicker?.cancel();
    _operationTicker = null;
    _operationStartedAt = null;
    if (mounted) {
      setState(() {
        _operationLabel = null;
        _operationElapsedMs = 0;
      });
    }
  }

  Future<void> _cancelOperation() async {
    final requestId = _activeRequestId;
    if (requestId == null) return;
    bool accepted;
    try {
      accepted = await widget.port.cancelOperation(requestId);
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = '取消未送达；当前旅程仍在处理中：$error';
        });
      }
      return;
    }
    if (!mounted) return;
    if (!accepted) {
      _advanceOperation(
        LocalHostOperationStage.applying,
        '叙事已进入状态写入阶段，当前操作不能再取消。',
      );
      return;
    }
    await _markPendingRunOperation(false);
    setState(() {
      _activeRequestId = null;
      _busy = false;
      _error = '已取消本次行动；原旅程没有改变，可以重新选择。';
    });
    _endOperation();
  }

  @override
  void didUpdateWidget(covariant PlayPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.runId != oldWidget.runId) _load();
  }

  Future<void> _load() async {
    final runId = widget.runId;
    if (runId == null) return;
    final changingRun = shouldResetRetriableAction(_run?.runId, runId);
    if (changingRun) {
      // A retry closure captures the old Run and must never cross a Run boundary.
      _activeRequestId = null;
      _retryAction = null;
      _destination = null;
    }
    _beginOperation('正在读取本机旅程…');
    setState(() {
      _busy = true;
      _error = null;
      _run = null;
    });
    try {
      final run = await widget.port.getRun(runId);
      if (mounted) {
        setState(() {
          _run = run;
          _destination = _initialDestination(run);
        });
        if (run.status != 'completed') _scrollToLatest();
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      _endOperation();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _choose(Map<String, dynamic> choice) async {
    final run = _run;
    if (run == null) return;
    final requestId = 'choice-${DateTime.now().microsecondsSinceEpoch}';
    _retryAction = () => _choose(choice);
    _activeRequestId = requestId;
    await _markPendingRunOperation(true);
    _beginOperation('正在生成后续故事；成功前不会写入半个回合。');
    setState(() => _busy = true);
    try {
      await _showModelGeneration();
      final next = await widget.port.choose(run.runId, {
        'request_id': requestId,
        'expected_revision': run.state['revision'],
        'choice_id': choice['id'],
        'player_input': choice['label'],
      });
      if (_activeRequestId != requestId) return;
      _advanceOperation(LocalHostOperationStage.applying, '叙事已返回，正在读取保存后的状态…');
      if (mounted) {
        setState(() {
          _run = next;
          _retryAction = null;
          _error = null;
        });
        _scrollToLatest();
      }
    } catch (error) {
      if (mounted && _activeRequestId == requestId) {
        setState(() => _error = '本次行动失败，原状态未改变：$error');
      }
    } finally {
      if (mounted && _activeRequestId == requestId) {
        await _markPendingRunOperation(false);
        _activeRequestId = null;
        _endOperation();
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _playNarrative() async {
    final run = _run;
    final input = _action.text.trim();
    if (run == null || input.isEmpty) return;
    final requestId = 'narrate-${DateTime.now().microsecondsSinceEpoch}';
    _retryAction = _playNarrative;
    _activeRequestId = requestId;
    await _markPendingRunOperation(true);
    _beginOperation('正在生成后续故事；成功前不会写入半个回合。');
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _showModelGeneration();
      final next = await widget.port.playTurn(run.runId, {
        'request_id': requestId,
        'expected_revision': run.state['revision'],
        'player_input': input,
        'commands': [
          if (_destination != null)
            {
              'type': 'move',
              'payload': {'location_id': _destination},
            },
          {'type': 'narrate', 'payload': {}},
        ],
      });
      if (mounted && _activeRequestId == requestId) {
        _advanceOperation(
          LocalHostOperationStage.applying,
          '叙事已返回，正在读取保存后的状态…',
        );
        _action.clear();
        setState(() {
          _run = next;
          _retryAction = null;
          _error = null;
        });
        _scrollToLatest();
      }
    } catch (error) {
      if (mounted && _activeRequestId == requestId) {
        setState(() => _error = '本次行动失败，原状态未改变：$error');
      }
    } finally {
      if (mounted && _activeRequestId == requestId) {
        await _markPendingRunOperation(false);
        _activeRequestId = null;
        _endOperation();
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _rollback(Map<String, dynamic> turn) async {
    final run = _run;
    if (run == null) return;
    _beginOperation('正在恢复历史状态…');
    await _markPendingRunOperation(true);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final next = await widget.port.rollback(run.runId, {
        'request_id': 'rollback-${DateTime.now().microsecondsSinceEpoch}',
        'expected_revision': run.state['revision'],
        'target_turn_id': turn['id'],
      });
      if (mounted) {
        setState(() => _run = next);
        _scrollToLatest();
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      await _markPendingRunOperation(false);
      _endOperation();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.runId == null) {
      return const Center(child: Text('从世界或创作页进入一段旅程。'));
    }
    if (_run == null && !_busy && _error == null) {
      return Center(
        child: FilledButton(onPressed: _load, child: const Text('继续本机旅程')),
      );
    }
    if (_run == null && _error != null) {
      return RuntimeErrorView(error: _error, onRetry: _load);
    }
    if (_run == null) return const Center(child: CircularProgressIndicator());
    final ending = _run!.state['ending'];
    final endingKind = ending?['kind'] as String?;
    final endingLabel =
        const {
          'good': '好结局',
          'normal': '普通结局',
          'bad': '坏结局',
          'hidden': '隐藏结局',
        }[endingKind] ??
        '结局';
    final endingBeat = _run!.storyBeats
        .cast<Map<String, dynamic>?>()
        .firstWhere((beat) => beat?['kind'] == 'ending', orElse: () => null);
    final currentBeat = _run!.storyBeats.isEmpty ? null : _run!.storyBeats.last;
    final currentLocation = currentBeat?['location'] as String?;
    final presentation = _run!.presentation;
    final route = _mapValue(_run!.state['route']);
    final routeLabel = route.isEmpty
        ? null
        : _presentationLabel(presentation, 'routes', route['id'], '未命名路线');
    final inventorySummary =
        (_run!.state['inventory'] as List<dynamic>? ?? const [])
            .map((item) => _mapValue(item))
            .where((item) => item.isNotEmpty)
            .map(
              (item) =>
                  '${_presentationLabel(presentation, 'resources', item['id'], '未知物品')} ×${item['quantity']}',
            )
            .join('，');
    final relationshipSummary = _mapValue(_run!.state['relationships']).entries
        .map((entry) {
          final relationship = _mapValue(entry.value);
          final dimensions = _mapValue(relationship['dimensions']).entries
              .map(
                (dimension) =>
                    '${_relationshipDimensionLabel(dimension.key)} ${dimension.value}',
              )
              .join('、');
          final character = _presentationLabel(
            presentation,
            'relationships',
            entry.key,
            '未知角色',
          );
          return '$character：$dimensions';
        })
        .toList(growable: false);
    final npcSummary = _mapValue(_run!.state['npc_state']).values
        .map(_mapValue)
        .where((npc) => npc.isNotEmpty)
        .map((npc) {
          final name = npc['name'] as String? ?? npc['id'] as String? ?? 'NPC';
          final reputation = npc['reputation'];
          final faction = npc['faction_id'];
          final details = <String>[
            if (reputation is num)
              '声誉 ${reputation >= 0 ? '+' : ''}${reputation.toInt()}',
            if (faction is String && faction.isNotEmpty) '势力 $faction',
          ];
          return details.isEmpty ? name : '$name：${details.join(' · ')}';
        })
        .toList(growable: false);
    final memorySummary = [
      ...(_run!.state['plot_threads'] as List<dynamic>? ?? const [])
          .whereType<Map>()
          .where((item) => item['status'] == 'active')
          .map((item) => '线索：${item['description'] ?? '未命名线索'}'),
      ...(_run!.state['active_events'] as List<dynamic>? ?? const [])
          .whereType<Map>()
          .where((item) => item['status'] == 'active')
          .map(
            (item) => '事件：${item['description'] ?? item['name'] ?? '未命名事件'}',
          ),
    ].where((item) => item.trim().isNotEmpty).take(6).toList(growable: false);
    final completedTurns = _run!.completedTurns;
    final recentActions = completedTurns.reversed
        .take(3)
        .map((turn) => turn['player_input'] as String? ?? '')
        .where((action) => action.isNotEmpty)
        .toList(growable: false)
        .reversed
        .toList(growable: false);
    final visibleBeats = _run!.storyBeats
        .where((beat) => beat['kind'] != 'ending')
        .toList(growable: false);
    final latestBeat = visibleBeats.isEmpty ? null : visibleBeats.last;
    final historyBeats = visibleBeats.length > 1
        ? visibleBeats.sublist(0, visibleBeats.length - 1)
        : const <Map<String, dynamic>>[];
    final stateEvents = visibleBeats
        .where(
          (beat) =>
              (beat['state_feedback'] as List<dynamic>?)?.isNotEmpty ?? false,
        )
        .toList(growable: false);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '游玩',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
              ),
              Text(currentLocation ?? '当前旅程'),
            ],
          ),
        ),
        Expanded(
          child: Scrollbar(
            controller: _storyScroll,
            thumbVisibility: true,
            child: ListView(
              controller: _storyScroll,
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
              children: [
                _StatePanel(
                  location: currentLocation,
                  chapter: latestBeat?['title'] as String?,
                  routeLabel: routeLabel,
                  inventorySummary: inventorySummary,
                  relationshipSummary: relationshipSummary,
                  npcSummary: npcSummary,
                  memorySummary: memorySummary,
                  turnCount: completedTurns.length,
                ),
                if (ending != null)
                  _EndingSummary(
                    endingLabel: endingLabel,
                    endingBeat: endingBeat,
                    completedTurns: completedTurns.length,
                    routeLabel: routeLabel,
                    inventorySummary: inventorySummary,
                    relationshipSummary: relationshipSummary,
                    recentActions: recentActions,
                    busy: _busy,
                    onStartNewRun: () => widget.onStartNewRun(_run!.worldId),
                    onReturnToWorlds: widget.onReturnToWorlds,
                  ),
                _EventHistoryPanel(
                  events: stateEvents,
                  turns: _run!.turns,
                  busy: _busy,
                  onRollback: _rollback,
                ),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '历史叙事${historyBeats.isEmpty ? '' : ' · ${historyBeats.length} 段'}',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                    TextButton.icon(
                      onPressed: _busy ? null : _scrollToLatest,
                      icon: const Icon(Icons.vertical_align_bottom),
                      label: const Text('回到最新'),
                    ),
                  ],
                ),
                const Text('这里只回看已经发生的内容；当前新场景和操作固定在下方。'),
                const SizedBox(height: 6),
                if (historyBeats.isEmpty)
                  const Text('还没有可回看的历史内容。完成一次行动后，旧内容会保留在这里。')
                else
                  for (final beat in historyBeats) _StoryBeatCard(beat: beat),
                TextButton.icon(
                  onPressed: _busy ? null : _load,
                  icon: const Icon(Icons.refresh),
                  label: const Text('重新读取本机存档'),
                ),
              ],
            ),
          ),
        ),
        if (ending == null)
          SafeArea(
            top: false,
            child: Material(
              elevation: 12,
              color: Theme.of(context).colorScheme.surface,
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.sizeOf(context).height * 0.46,
                ),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Icon(
                            Icons.auto_awesome,
                            size: 18,
                            color: Theme.of(context).colorScheme.primary,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            '当前新内容',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const Spacer(),
                          Text(
                            '选项固定在这里',
                            style: Theme.of(context).textTheme.labelSmall,
                          ),
                        ],
                      ),
                      if (_operationLabel != null)
                        OperationStatusCard(
                          stage: _operationStage,
                          label: _operationLabel!,
                          elapsedMs: _operationElapsedMs,
                          cancellable:
                              _activeRequestId != null &&
                              LocalHostOperationStage.cancellable.contains(
                                _operationStage,
                              ),
                          onCancel: _cancelOperation,
                        ),
                      if (_error != null) ...[
                        InlineError(_error!),
                        if (_retryAction != null && !_busy)
                          Align(
                            alignment: Alignment.centerLeft,
                            child: TextButton.icon(
                              onPressed: _retryAction,
                              icon: const Icon(Icons.refresh),
                              label: const Text('重试上次行动'),
                            ),
                          ),
                      ],
                      if (latestBeat != null) ...[
                        const SizedBox(height: 8),
                        _StoryBeatCard(beat: latestBeat, current: true),
                      ],
                      if (_run!.availableChoices.isEmpty)
                        _FreeActionPanel(
                          presentation: presentation,
                          destination: _destination,
                          action: _action,
                          busy: _busy,
                          onDestination: (value) =>
                              setState(() => _destination = value),
                          onSubmit: _playNarrative,
                        )
                      else
                        for (final choice in _run!.availableChoices)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: FilledButton.tonal(
                              onPressed: _busy ? null : () => _choose(choice),
                              child: Text(choice['label'] as String),
                            ),
                          ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _StatePanel extends StatelessWidget {
  const _StatePanel({
    required this.location,
    required this.chapter,
    required this.routeLabel,
    required this.inventorySummary,
    required this.relationshipSummary,
    required this.npcSummary,
    required this.memorySummary,
    required this.turnCount,
  });

  final String? location;
  final String? chapter;
  final String? routeLabel;
  final String inventorySummary;
  final List<String> relationshipSummary;
  final List<String> npcSummary;
  final List<String> memorySummary;
  final int turnCount;

  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 8),
    child: ExpansionTile(
      initiallyExpanded: false,
      leading: const Icon(Icons.tune),
      title: const Text('当前状态'),
      subtitle: Text('${location ?? '未知地点'} · 第 $turnCount 回合'),
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      children: [
        if (chapter != null) _StateLine(label: '场景', value: chapter!),
        if (routeLabel != null) _StateLine(label: '路线', value: routeLabel!),
        if (inventorySummary.isNotEmpty)
          _StateLine(label: '物品', value: inventorySummary),
        for (final relationship in relationshipSummary)
          _StateLine(label: '关系', value: relationship),
        for (final npc in npcSummary) _StateLine(label: '人物', value: npc),
        for (final memory in memorySummary)
          _StateLine(label: '线索', value: memory),
        if (chapter == null &&
            routeLabel == null &&
            inventorySummary.isEmpty &&
            relationshipSummary.isEmpty &&
            npcSummary.isEmpty &&
            memorySummary.isEmpty)
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('暂无可展开的常驻状态。'),
          ),
      ],
    ),
  );
}

class _StateLine extends StatelessWidget {
  const _StateLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 6),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 48,
          child: Text(label, style: Theme.of(context).textTheme.labelMedium),
        ),
        Expanded(child: Text(value)),
      ],
    ),
  );
}

class _EventHistoryPanel extends StatelessWidget {
  const _EventHistoryPanel({
    required this.events,
    required this.turns,
    required this.busy,
    required this.onRollback,
  });

  final List<Map<String, dynamic>> events;
  final List<Map<String, dynamic>> turns;
  final bool busy;
  final Future<void> Function(Map<String, dynamic>) onRollback;

  @override
  Widget build(BuildContext context) {
    final count =
        events.length +
        turns.where((turn) {
          return (turn['kind'] as String? ?? 'turn') == 'turn';
        }).length;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        initiallyExpanded: count > 0,
        leading: const Icon(Icons.auto_stories),
        title: const Text('事件与行动记录'),
        subtitle: Text(count == 0 ? '还没有事件' : '$count 条记录 · 可回看并回滚'),
        children: [
          if (events.isEmpty && turns.isEmpty)
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('状态变化和大事件会集中显示在这里。'),
              ),
            ),
          for (final event in events)
            ListTile(
              dense: true,
              title: Text(event['title'] as String? ?? '状态更新'),
              subtitle: Text(
                ((event['state_feedback'] as List<dynamic>?) ?? const [])
                    .whereType<String>()
                    .join(' · '),
              ),
            ),
          for (final turn in turns.reversed)
            if ((turn['kind'] as String? ?? 'turn') == 'turn')
              ListTile(
                dense: true,
                leading: const Icon(Icons.touch_app, size: 18),
                title: Text('第 ${turn['sequence']} 回合'),
                subtitle: Text(turn['player_input'] as String? ?? '未记录行动'),
                trailing: TextButton(
                  onPressed: busy ? null : () => onRollback(turn),
                  child: const Text('回滚'),
                ),
              )
            else
              ListTile(
                dense: true,
                leading: const Icon(Icons.history, size: 18),
                title: Text(_rollbackRecordLabel(turns, turn)),
              ),
        ],
      ),
    );
  }
}

class _StoryBeatCard extends StatelessWidget {
  const _StoryBeatCard({required this.beat, this.current = false});

  final Map<String, dynamic> beat;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final dialogue = _mapValue(beat['dialogue']);
    final dialogues = (beat['dialogues'] as List<dynamic>? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList(growable: false);
    final title = beat['title'] as String? ?? '未命名场景';
    final narrative = beat['narrative'] as String? ?? '';
    final objective = beat['objective'] as String? ?? '';
    final guidance = beat['guidance'] as String? ?? '';
    final stateFeedback = (beat['state_feedback'] as List<dynamic>? ?? const [])
        .whereType<String>()
        .toList(growable: false);
    final compactCurrent = current && beat['kind'] != 'opening';
    // NPC 主动联系是需要玩家马上理解的上下文；即使当前卡片采用紧凑布局，
    // 也不能把“为什么现在要回应”藏起来。
    final showCurrentPrompt = current && objective.contains('主动找到了');
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color: current ? Theme.of(context).colorScheme.primaryContainer : null,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            if (current && narrative.length > 140) ...[
              Text(narrative, maxLines: 3, overflow: TextOverflow.ellipsis),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: () =>
                      _showFullNarrative(context, title, narrative),
                  icon: const Icon(Icons.open_in_new, size: 18),
                  label: const Text('展开本回合全文'),
                ),
              ),
            ] else
              Text(narrative),
            if (current && stateFeedback.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('结果：${stateFeedback.first}'),
              if (stateFeedback.length > 1)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: () => _showAllFeedback(context, stateFeedback),
                    child: Text('查看其他变化（${stateFeedback.length}）'),
                  ),
                ),
            ],
            if (dialogues.isNotEmpty) ...[
              const SizedBox(height: 10),
              for (final item
                  in (compactCurrent ? dialogues.take(1) : dialogues))
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    '${item['speaker'] ?? '角色'}：${item['text'] ?? ''}',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                ),
            ] else if (dialogue.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(
                '${dialogue['speaker'] ?? '角色'}：${dialogue['text'] ?? ''}',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(fontStyle: FontStyle.italic),
              ),
            ],
            if ((!compactCurrent || showCurrentPrompt) &&
                objective.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(objective, style: Theme.of(context).textTheme.titleSmall),
            ],
            if ((!compactCurrent || showCurrentPrompt) &&
                guidance.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(guidance),
            ],
          ],
        ),
      ),
    );
  }

  void _showFullNarrative(
    BuildContext context,
    String title,
    String narrative,
  ) {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: SingleChildScrollView(child: Text(narrative)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
  }

  void _showAllFeedback(BuildContext context, List<String> feedback) {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('这次行动带来的变化'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [for (final item in feedback) Text('· $item')],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
  }
}

class _EndingSummary extends StatelessWidget {
  const _EndingSummary({
    required this.endingLabel,
    required this.endingBeat,
    required this.completedTurns,
    required this.routeLabel,
    required this.inventorySummary,
    required this.relationshipSummary,
    required this.recentActions,
    required this.busy,
    required this.onStartNewRun,
    required this.onReturnToWorlds,
  });

  final String endingLabel;
  final Map<String, dynamic>? endingBeat;
  final int completedTurns;
  final String? routeLabel;
  final String inventorySummary;
  final List<String> relationshipSummary;
  final List<String> recentActions;
  final bool busy;
  final VoidCallback onStartNewRun;
  final VoidCallback onReturnToWorlds;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '旅程完成 · $endingLabel',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          if (endingBeat != null) ...[
            const SizedBox(height: 8),
            Text(
              endingBeat!['title'] as String? ?? '结局',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 6),
            Text(endingBeat!['narrative'] as String? ?? ''),
          ],
          const SizedBox(height: 10),
          Text('这段旅程已正式结算，共完成 $completedTurns 个回合。'),
          if (routeLabel != null) Text('最终路线：$routeLabel'),
          const SizedBox(height: 6),
          const Text('这段旅程留下了'),
          if (inventorySummary.isNotEmpty) Text('持有物品：$inventorySummary'),
          for (final relationship in relationshipSummary)
            Text('人物关系：$relationship'),
          if (recentActions.isNotEmpty) ...[
            const SizedBox(height: 6),
            const Text('关键行动'),
            for (final action in recentActions) Text('• $action'),
          ],
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: busy ? null : onStartNewRun,
            icon: const Icon(Icons.replay),
            label: const Text('从同一世界开始新旅程'),
          ),
          TextButton(
            onPressed: busy ? null : onReturnToWorlds,
            child: const Text('返回世界'),
          ),
        ],
      ),
    ),
  );
}

class _FreeActionPanel extends StatelessWidget {
  const _FreeActionPanel({
    required this.presentation,
    required this.destination,
    required this.action,
    required this.busy,
    required this.onDestination,
    required this.onSubmit,
  });

  final Map<String, dynamic> presentation;
  final String? destination;
  final TextEditingController action;
  final bool busy;
  final ValueChanged<String?> onDestination;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final locations = _mapValue(presentation['locations']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (locations.length > 1) ...[
          DropdownButtonFormField<String>(
            initialValue: destination,
            decoration: const InputDecoration(labelText: '目的地'),
            items: [
              for (final entry in locations.entries)
                DropdownMenuItem(
                  value: entry.key,
                  child: Text(entry.value as String),
                ),
            ],
            onChanged: busy ? null : onDestination,
          ),
          const SizedBox(height: 8),
        ],
        TextField(
          controller: action,
          minLines: 1,
          maxLines: 3,
          decoration: const InputDecoration(
            labelText: '记录行动',
            hintText: '例如：观察码头的灯号，再向前走一步',
          ),
          onSubmitted: (_) => onSubmit(),
        ),
        const SizedBox(height: 8),
        FilledButton.icon(
          onPressed: busy ? null : onSubmit,
          icon: const Icon(Icons.send),
          label: const Text('提交行动'),
        ),
      ],
    );
  }
}

String _rollbackRecordLabel(
  List<Map<String, dynamic>> turns,
  Map<String, dynamic> rollback,
) {
  final targetId = rollback['rollback_target_id'] as String?;
  final target = turns.cast<Map<String, dynamic>?>().firstWhere(
    (turn) => turn?['id'] == targetId,
    orElse: () => null,
  );
  return target == null ? '已恢复至先前回合' : '已恢复至第 ${target['sequence']} 回合之后';
}

String? _initialDestination(RunSnapshot run) {
  final locations = _mapValue(run.presentation['locations']);
  final current = run.state['location_id'];
  if (current is String && locations.containsKey(current)) return current;
  return locations.isEmpty ? null : locations.keys.first;
}

Map<String, dynamic> _mapValue(Object? value) {
  if (value is! Map) return const <String, dynamic>{};
  return Map<String, dynamic>.from(value);
}

String _presentationLabel(
  Map<String, dynamic> presentation,
  String group,
  Object? id,
  String fallback,
) {
  final labels = _mapValue(presentation[group]);
  return labels[id] as String? ?? fallback;
}

String _relationshipDimensionLabel(String dimension) {
  return const {'affection': '好感', 'trust': '信任'}[dimension] ?? '关系';
}

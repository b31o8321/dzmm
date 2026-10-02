import 'dart:async';

import 'package:flutter/material.dart';

import '../local_host_port.dart';
import '../widgets/loop_hud.dart';
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
  String? _lastFeedback;
  String? _destination;
  Future<void> Function()? _retryAction;
  final _action = TextEditingController();
  final _storyScroll = ScrollController();
  final _actionScroll = ScrollController();

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
    _actionScroll.dispose();
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

  void _scrollActionToLatest() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_actionScroll.hasClients) return;
      final target = _actionScroll.position.maxScrollExtent;
      _actionScroll.jumpTo(target);
      Future<void>.delayed(const Duration(milliseconds: 80), () {
        if (!mounted || !_actionScroll.hasClients) return;
        final latestTarget = _actionScroll.position.maxScrollExtent;
        if ((_actionScroll.offset - latestTarget).abs() > 1) {
          _actionScroll.animateTo(
            latestTarget,
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOutCubic,
          );
        }
      });
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
        if (run.status != 'completed') {
          _scrollToLatest();
          _scrollActionToLatest();
        }
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
        _scrollActionToLatest();
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

  List<({String id, String name, int quantity})> get _usableInventory {
    final run = _run;
    if (run == null) return const [];
    final effects = _mapValue(run.presentation['resource_effects']);
    final names = _mapValue(run.presentation['resources']);
    final items = <({String id, String name, int quantity})>[];
    for (final entry in run.state['inventory'] as List<dynamic>? ?? const []) {
      final item = _mapValue(entry);
      final id = item['id']?.toString();
      if (id == null || !effects.containsKey(id)) continue;
      final quantity = item['quantity'];
      if (quantity is! num || quantity <= 0) continue;
      items.add((
        id: id,
        name: names[id]?.toString() ?? id,
        quantity: quantity.toInt(),
      ));
    }
    return items;
  }

  List<_CombatTarget> get _combatTargets {
    final run = _run;
    if (run == null) return const [];
    final state = run.state;
    final ruleset = _mapValue(state['ruleset']);
    final capabilities =
        ruleset['enabled_capabilities'] as List<dynamic>? ?? const [];
    if (!capabilities.contains('combat')) return const [];
    final participants = _mapValue(_mapValue(state['combat'])['participants']);
    final location = state['location_id'];
    final targets = <_CombatTarget>[];
    _mapValue(state['npc_state']).forEach((id, raw) {
      final npc = _mapValue(raw);
      if (npc['met'] != true) return;
      final npcLocation = npc['location_id'];
      if (npcLocation != null && npcLocation != location) return;
      final participant = _mapValue(participants[id.toString()]);
      targets.add(
        _CombatTarget(
          id: id.toString(),
          name: npc['name']?.toString() ?? id.toString(),
          hp: participant['hp'] as int?,
          maxHp: participant['max_hp'] as int?,
          defeated: participant['defeated'] == true,
        ),
      );
    });
    return targets;
  }

  List<String> get _availableSkills {
    final run = _run;
    if (run == null) return const [];
    final skills = _mapValue(run.presentation['skills']);
    final base = (skills['base'] as List<dynamic>? ?? const [])
        .map((skill) => skill.toString())
        .toSet();
    final world = (skills['world'] as List<dynamic>? ?? const [])
        .map((skill) => skill.toString())
        .toSet();
    return {...base, ...world, ..._trainedSkills}.toList()..sort();
  }

  Set<String> get _trainedSkills {
    final run = _run;
    if (run == null) return const {};
    final hero = _mapValue(run.state['hero']);
    return (hero['skills'] as List<dynamic>? ?? const [])
        .map((skill) => skill.toString())
        .toSet();
  }

  /// 从最新回合的引擎裁决结果提取玩家可感知反馈（战斗/检定/物品）。
  void _extractFeedback(RunSnapshot next) {
    final turns = next.turns;
    if (turns.isEmpty) return;
    final outcomes = (turns.last['outcomes'] as List<dynamic>? ?? const [])
        .whereType<Map>()
        .map((o) => Map<String, dynamic>.from(o))
        .toList(growable: false);
    final parts = <String>[];
    for (final o in outcomes) {
      final type = o['type'];
      if (type == 'attack') {
        final hit = o['hit'] == true;
        parts.add(
          hit
              ? '攻击命中：d20 掷出 ${o['roll']}，伤害 ${o['damage']}'
              : '攻击未命中：d20 掷出 ${o['roll']}',
        );
      } else if (type == 'skill_check_result') {
        parts.add(
          '${o['skill']} 检定：${o['total']} vs DC ${o['dc']} · '
          '${o['success'] == true ? '成功' : '失败'}',
        );
      } else if (type == 'item_used') {
        final healed = o['healed'];
        if (healed is num && healed > 0) {
          parts.add('使用了物品，恢复 $healed 点');
        } else {
          parts.add('使用了物品');
        }
      }
    }
    if (parts.isNotEmpty && mounted) {
      setState(() => _lastFeedback = parts.join('；'));
    }
  }

  /// 带前置引擎命令的回合（攻击/检定/物品使用），命令先于 narrate 结算。
  Future<void> _playWithCommand(
    String input,
    Map<String, dynamic> command,
  ) async {
    final run = _run;
    if (run == null || input.trim().isEmpty) return;
    final requestId = 'cmd-${DateTime.now().microsecondsSinceEpoch}';
    _retryAction = () => _playWithCommand(input, command);
    _activeRequestId = requestId;
    await _markPendingRunOperation(true);
    _beginOperation('正在结算本回合；成功前不会写入半个回合。');
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
        'commands': [command, {'type': 'narrate', 'payload': {}}],
      });
      if (mounted && _activeRequestId == requestId) {
        _advanceOperation(
          LocalHostOperationStage.applying,
          '叙事已返回，正在读取保存后的状态…',
        );
      }
      if (!mounted) return;
      setState(() {
        _run = next;
        _destination = _initialDestination(next);
      });
      _extractFeedback(next);
      _scrollToLatest();
    } catch (error) {
      if (mounted && _activeRequestId == requestId) {
        setState(() => _error = error.toString());
      }
    } finally {
      if (mounted && _activeRequestId == requestId) {
        _activeRequestId = null;
      }
      _endOperation();
      if (mounted) setState(() => _busy = false);
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
        _scrollActionToLatest();
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
                LoopHud(state: _run!.state),
                _QuestPanel(
                  questState: _mapValue(_run!.state['quests']),
                  titles: _mapValue(_run!.presentation['quests']),
                ),
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
              child: SizedBox(
                height: MediaQuery.sizeOf(context).height * 0.5,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
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
                      if (_error == null)
                      Expanded(
                        child: SingleChildScrollView(
                          controller: _actionScroll,
                          padding: const EdgeInsets.only(top: 8),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              if (latestBeat != null)
                                _StoryBeatCard(beat: latestBeat, current: true),
                              if (_lastFeedback != null)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 6),
                                  child: Align(
                                    alignment: Alignment.centerLeft,
                                    child: Text(
                                      _lastFeedback!,
                                      style: TextStyle(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .primary,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ),
                              if (_combatTargets.isNotEmpty)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 6),
                                  child: _CombatDeck(
                                    targets: _combatTargets,
                                    busy: _busy,
                                    onAttack: (targetId, targetName) =>
                                        _playWithCommand('攻击$targetName', {
                                      'type': 'attack',
                                      'payload': {'target_id': targetId},
                                    }),
                                  ),
                                ),
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
                                      onPressed: _busy
                                          ? null
                                          : () => _choose(choice),
                                      child: Text(choice['label'] as String),
                                    ),
                                  ),
                              _SkillsItemsPanel(
                                availableSkills: _availableSkills,
                                trainedSkills: _trainedSkills,
                                inventoryItems: _usableInventory,
                                busy: _busy,
                                onSkillCheck: (skill, dc) => _playWithCommand(
                                  '$skill 检定',
                                  {
                                    'type': 'skill_check',
                                    'payload': {'skill': skill, 'dc': dc},
                                  },
                                ),
                                onUseItem: (itemId, itemName) =>
                                    _playWithCommand('使用$itemName', {
                                  'type': 'use_item',
                                  'payload': {'item_id': itemId},
                                }),
                              ),
                            ],
                          ),
                        ),
                      ),
                    if (_error != null) const Spacer(),
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
          maxLength: 4000,
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

class _CombatTarget {
  const _CombatTarget({
    required this.id,
    required this.name,
    required this.hp,
    required this.maxHp,
    required this.defeated,
  });

  final String id;
  final String name;
  final int? hp;
  final int? maxHp;
  final bool defeated;
}

/// 战斗入口：与桌面 combat deck 对齐（目标 + HP + 倒下态 + 空目标提示）。
class _CombatDeck extends StatelessWidget {
  const _CombatDeck({
    required this.targets,
    required this.busy,
    required this.onAttack,
  });

  final List<_CombatTarget> targets;
  final bool busy;
  final void Function(String targetId, String targetName) onAttack;

  @override
  Widget build(BuildContext context) {
    if (targets.isEmpty) {
      return const Align(
        alignment: Alignment.centerLeft,
        child: Text(
          '当前地点没有可攻击的目标——先探索触发遭遇，或继续推进剧情。',
          style: TextStyle(fontSize: 12),
        ),
      );
    }
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final target in targets)
          if (target.defeated)
            Chip(label: Text('${target.name}（已倒下）'))
          else
            FilledButton.tonalIcon(
              onPressed: busy ? null : () => onAttack(target.id, target.name),
              icon: const Icon(Icons.gavel, size: 16),
              label: Text(
                target.hp != null && target.maxHp != null
                    ? '攻击 ${target.name} · ${target.hp}/${target.maxHp}'
                    : '攻击 ${target.name}',
              ),
            ),
      ],
    );
  }
}

/// 任务进度：状态来自引擎 quests 硬状态，标题来自世界定义。
class _QuestPanel extends StatelessWidget {
  const _QuestPanel({required this.questState, required this.titles});

  final Map<String, dynamic> questState;
  final Map<String, dynamic> titles;

  static const _statusLabels = {
    'active': '进行中',
    'pending': '待激活',
    'completed': '已完成',
    'expired': '已过期',
  };

  @override
  Widget build(BuildContext context) {
    if (questState.isEmpty) return const SizedBox.shrink();
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('任务', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            for (final entry in questState.entries)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        titles[entry.key]?.toString() ?? entry.key,
                      ),
                    ),
                    Text(
                      _statusLabels[
                              _mapValue(entry.value)['status']?.toString()] ??
                          '进行中',
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 技能检定 + 物品使用：引擎能力（skill_check / use_item）的手机入口。
class _SkillsItemsPanel extends StatefulWidget {
  const _SkillsItemsPanel({
    required this.availableSkills,
    required this.trainedSkills,
    required this.inventoryItems,
    required this.busy,
    required this.onSkillCheck,
    required this.onUseItem,
  });

  final List<String> availableSkills;
  final Set<String> trainedSkills;
  final List<({String id, String name, int quantity})> inventoryItems;
  final bool busy;
  final void Function(String skill, int dc) onSkillCheck;
  final void Function(String itemId, String itemName) onUseItem;

  @override
  State<_SkillsItemsPanel> createState() => _SkillsItemsPanelState();
}

class _SkillsItemsPanelState extends State<_SkillsItemsPanel> {
  String? _skill;
  final TextEditingController _dc = TextEditingController(text: '12');

  @override
  void dispose() {
    _dc.dispose();
    super.dispose();
  }

  int get _dcValue {
    final parsed = int.tryParse(_dc.text.trim());
    if (parsed == null || parsed < 5 || parsed > 25) return 12;
    return parsed;
  }

  @override
  Widget build(BuildContext context) {
    final skills = widget.availableSkills;
    return ExpansionTile(
      title: const Text('检定与物品'),
      subtitle: const Text('技能检定与带效果的物品使用'),
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      children: [
        if (skills.isEmpty)
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('当前世界没有可用技能。'),
          )
        else ...[
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _skill ?? skills.first,
                  decoration: const InputDecoration(labelText: '技能'),
                  items: [
                    for (final skill in skills)
                      DropdownMenuItem(
                        value: skill,
                        child: Text(
                          widget.trainedSkills.contains(skill)
                              ? '$skill（受训 +3）'
                              : skill,
                        ),
                      ),
                  ],
                  onChanged: (value) => setState(() => _skill = value),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 88,
                child: TextField(
                  controller: _dc,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'DC',
                    helperText: '5-25',
                  ),
                ),
              ),
            ],
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: widget.busy
                  ? null
                  : () => widget.onSkillCheck(
                      _skill ?? skills.first, _dcValue),
              icon: const Icon(Icons.casino),
              label: const Text('掷骰检定'),
            ),
          ),
        ],
        if (widget.inventoryItems.isEmpty)
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('背包里没有可使用的物品。'),
          )
        else ...[
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('可使用物品'),
          ),
          for (final item in widget.inventoryItems)
            ListTile(
              dense: true,
              title: Text('${item.name} ×${item.quantity}'),
              trailing: TextButton(
                onPressed: widget.busy
                    ? null
                    : () => widget.onUseItem(item.id, item.name),
                child: const Text('使用'),
              ),
            ),
        ],
      ],
    );
  }
}

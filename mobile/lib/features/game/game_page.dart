import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../../api/api_error.dart';
import '../../api/dzmm_api.dart';
import '../../api/sse_client.dart';
import '../sessions/session_models.dart';
import '../sessions/session_repository.dart';
import 'turn_run_client.dart';

class GamePage extends StatefulWidget {
  const GamePage({
    required this.session,
    required this.repository,
    required this.turnClient,
    super.key,
  });

  final GameSessionSummary session;
  final SessionRepository repository;
  final TurnRunClient turnClient;

  @override
  State<GamePage> createState() => _GamePageState();
}

class _GamePageState extends State<GamePage> with WidgetsBindingObserver {
  final _composer = TextEditingController();
  final _scroll = ScrollController();
  CancellationToken? _turnCancellation;
  SessionHydration? _hydration;
  Object? _loadError;
  String? _activeRunId;
  String? _pendingAction;
  String _streamingNarrative = '';
  List<String> _choices = const [];
  String? _turnError;
  var _sending = false;
  var _checkingResume = false;
  var _showJump = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _scroll.addListener(_trackScroll);
    unawaited(_hydrate());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _activeRunId != null) {
      unawaited(_checkActiveRun());
    }
  }

  Future<void> _hydrate() async {
    setState(() {
      _loadError = null;
      if (_hydration == null) _turnError = null;
    });
    try {
      final value = await widget.repository.hydrate(widget.session.id);
      if (!mounted) return;
      setState(() => _hydration = value);
      _jumpToLatest(force: true);
    } on Object catch (error) {
      if (mounted) setState(() => _loadError = error);
    }
  }

  Future<void> _send([String? suggestion]) async {
    final action = (suggestion ?? _composer.text).trim();
    if (action.isEmpty || _sending || _checkingResume) return;
    _composer.clear();
    final cancellation = CancellationToken();
    _turnCancellation = cancellation;
    setState(() {
      _sending = true;
      _pendingAction = action;
      _streamingNarrative = '';
      _choices = const [];
      _turnError = null;
    });
    _jumpToLatest(force: true);
    try {
      await widget.turnClient.run(
        widget.session.id,
        action,
        cancellationToken: cancellation,
        onStarted: (run) {
          if (mounted) setState(() => _activeRunId = run.runId);
        },
        onEvent: _applyEvent,
      );
      if (!mounted) return;
      await _hydrate();
      if (!mounted) return;
      setState(() {
        _activeRunId = null;
        _pendingAction = null;
        _streamingNarrative = '';
      });
    } on TurnRehydrateRequired {
      await _hydrate();
      if (mounted) {
        setState(() {
          _activeRunId = null;
          _pendingAction = null;
          _streamingNarrative = '';
          _turnError = '连接恢复后已重新载入本回合。';
        });
      }
    } on ApiError catch (error) {
      if (mounted && error.code != 'cancelled') {
        await _hydrate();
        if (mounted) {
          setState(() {
            _activeRunId = null;
            _pendingAction = null;
            _streamingNarrative = '';
            _turnError = _turnErrorText(error);
          });
        }
      }
    } finally {
      if (mounted) setState(() => _sending = false);
      if (identical(_turnCancellation, cancellation)) {
        _turnCancellation = null;
      }
    }
  }

  void _applyEvent(SseEvent event) {
    if (!mounted) return;
    try {
      final decoded = jsonDecode(event.data);
      if (decoded is! Map) return;
      final payload = decoded.cast<String, Object?>();
      if (event.event == 'narrative' && payload['text'] is String) {
        setState(() => _streamingNarrative += payload['text']! as String);
        _jumpToLatest();
      } else if (event.event == 'tag' && payload['name'] == 'choices') {
        setState(() => _choices = _parseChoices(payload['content']));
      } else if (event.event == 'error') {
        setState(
          () => _turnError = payload['message'] as String? ?? '模型生成失败，请重试。',
        );
      }
    } on FormatException {
      // Malformed diagnostic events do not invalidate the persisted turn.
    }
  }

  Future<void> _checkActiveRun() async {
    if (_checkingResume || _activeRunId == null) return;
    setState(() => _checkingResume = true);
    try {
      final run = await widget.turnClient.check(
        widget.session.id,
        _activeRunId!,
      );
      if (run.status != TurnRunStatus.running) {
        await _hydrate();
        if (mounted) setState(() => _activeRunId = null);
      }
    } on ApiError catch (error) {
      if (mounted) setState(() => _turnError = _turnErrorText(error));
    } finally {
      if (mounted) setState(() => _checkingResume = false);
    }
  }

  void _trackScroll() {
    if (!_scroll.hasClients) return;
    final away = _scroll.position.maxScrollExtent - _scroll.offset > 160;
    if (away != _showJump && mounted) setState(() => _showJump = away);
  }

  void _jumpToLatest({bool force = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients || (!force && _showJump)) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _turnCancellation?.cancel();
    _composer.dispose();
    _scroll
      ..removeListener(_trackScroll)
      ..dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hydration = _hydration;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.session.name),
        actions: [
          IconButton(
            tooltip: '角色与世界状态',
            onPressed: hydration == null
                ? null
                : () => _showState(hydration.state),
            icon: const Icon(Icons.shield_outlined),
          ),
        ],
      ),
      body: switch ((_loadError, hydration)) {
        (final Object error, _) => _LoadFailure(
          error: error,
          onRetry: _hydrate,
        ),
        (_, null) => const Center(child: CircularProgressIndicator()),
        (_, final SessionHydration value) => Stack(
          children: [
            Column(
              children: [
                Expanded(child: _buildMessages(value)),
                _buildComposer(),
              ],
            ),
            if (_showJump)
              Positioned(
                right: 18,
                bottom: 118,
                child: FloatingActionButton.small(
                  tooltip: '跳到最新',
                  onPressed: () => _jumpToLatest(force: true),
                  child: const Icon(Icons.arrow_downward),
                ),
              ),
          ],
        ),
      },
    );
  }

  Widget _buildMessages(SessionHydration hydration) {
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
      children: [
        for (final message in hydration.messages)
          _MessageCard(message: message),
        if (_pendingAction != null) _PlayerActionCard(action: _pendingAction!),
        if (_sending || _streamingNarrative.isNotEmpty)
          _StreamingCard(
            narrative: _streamingNarrative,
            waiting: _streamingNarrative.isEmpty,
          ),
        if (_turnError != null)
          Card(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Text(_turnError!),
            ),
          ),
      ],
    );
  }

  Widget _buildComposer() {
    return SafeArea(
      top: false,
      child: Material(
        color: Theme.of(context).colorScheme.surface,
        elevation: 8,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_choices.isNotEmpty)
                SizedBox(
                  height: 42,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: _choices.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 8),
                    itemBuilder: (_, index) => ActionChip(
                      label: Text(_choices[index]),
                      onPressed: _sending ? null : () => _send(_choices[index]),
                    ),
                  ),
                ),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: TextField(
                      controller: _composer,
                      enabled: !_sending && !_checkingResume,
                      minLines: 1,
                      maxLines: 5,
                      textInputAction: TextInputAction.newline,
                      decoration: const InputDecoration(
                        hintText: '描述你的行动…',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: '发送行动',
                    onPressed: _sending || _checkingResume ? null : _send,
                    icon: _sending
                        ? const SizedBox.square(
                            dimension: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.arrow_upward),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _showState(SessionGameState state) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _StateSheet(state: state),
  );

  static List<String> _parseChoices(Object? content) {
    if (content is! String) return const [];
    try {
      final decoded = jsonDecode(content);
      if (decoded is List) {
        return decoded
            .whereType<String>()
            .where((item) => item.trim().isNotEmpty)
            .toList();
      }
    } on FormatException {
      // Fall back to one choice per non-empty line.
    }
    return content
        .split(RegExp(r'[\r\n]+'))
        .map(
          (line) => line.replaceFirst(RegExp(r'^\s*[-*\d.)]+\s*'), '').trim(),
        )
        .where((line) => line.isNotEmpty)
        .toList();
  }

  static String _turnErrorText(ApiError error) => switch (error.code) {
    'session_busy' => '另一个客户端正在生成本回合。完成后刷新即可继续。',
    'token_revoked' || 'unauthorized' => '设备授权已失效，请重新配对。',
    'offline' || 'timeout' => '连接暂时中断，恢复 Wi-Fi 后会继续同一回合。',
    _ => error.message,
  };
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({required this.message});

  final GameMessage message;

  @override
  Widget build(BuildContext context) {
    if (message.role == 'user') {
      return _PlayerActionCard(action: message.content);
    }
    final text = _displayText(message.content);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '守秘人 · 第 ${message.turn} 回合',
              style: Theme.of(context).textTheme.labelMedium,
            ),
            const SizedBox(height: 8),
            MarkdownBody(data: text),
            for (final event in message.events.where(
              (event) =>
                  {'dice', 'choices', 'state_change'}.contains(event['type']),
            ))
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Chip(label: Text('${event['type']}')),
              ),
          ],
        ),
      ),
    );
  }

  static String _displayText(String raw) {
    final parts = <String>[];
    final tag = RegExp(
      r'<(narrative|narriative|say)\b([^>]*)>([\s\S]*?)</(?:narrative|narriative|say)>',
      caseSensitive: false,
    );
    for (final match in tag.allMatches(raw)) {
      final kind = match.group(1)?.toLowerCase();
      final content = match.group(3)?.trim() ?? '';
      if (content.isEmpty) continue;
      if (kind == 'say') {
        final speaker = RegExp(
          "speaker=[\"']([^\"']+)[\"']",
        ).firstMatch(match.group(2) ?? '')?.group(1);
        parts.add(speaker == null ? '> $content' : '**$speaker**：$content');
      } else {
        parts.add(content);
      }
    }
    if (parts.isNotEmpty) return parts.join('\n\n');
    return raw.replaceAll(RegExp(r'<[^>]+>'), '').trim();
  }
}

class _PlayerActionCard extends StatelessWidget {
  const _PlayerActionCard({required this.action});

  final String action;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Card(
        color: Theme.of(context).colorScheme.primaryContainer,
        margin: const EdgeInsets.only(left: 38, bottom: 12),
        child: Padding(padding: const EdgeInsets.all(14), child: Text(action)),
      ),
    );
  }
}

class _StreamingCard extends StatelessWidget {
  const _StreamingCard({required this.narrative, required this.waiting});

  final String narrative;
  final bool waiting;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: waiting
            ? const Row(
                children: [
                  SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  SizedBox(width: 12),
                  Text('世界正在回应…'),
                ],
              )
            : MarkdownBody(data: narrative),
      ),
    );
  }
}

class _StateSheet extends StatelessWidget {
  const _StateSheet({required this.state});

  final SessionGameState state;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('当前状态', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          _StateSection(
            title: '生命与状态',
            values: state.vitals.isEmpty ? state.stats : state.vitals,
          ),
          _StateSection(title: '装备', values: state.equipment),
          if (state.inventory.isNotEmpty)
            Text('物品：${state.inventory.join('、')}'),
          if (state.npcs.isNotEmpty)
            Text('人物：${state.npcs.map((npc) => npc['name']).join('、')}'),
          if (state.threads.isNotEmpty)
            Text(
              '目标：${state.threads.map((item) => item['description']).join('、')}',
            ),
          if (state.goals.isNotEmpty)
            Text(
              '角色目标：${state.goals.where((goal) => goal['status'] == 'active').map((goal) => goal['description']).join('、')}',
            ),
          if (state.locations.isNotEmpty)
            Text(
              '当前位置：${state.locations.where((location) => location['is_current'] == true).map((location) => location['name']).join('、')}',
            ),
        ],
      ),
    );
  }
}

class _StateSection extends StatelessWidget {
  const _StateSection({required this.title, required this.values});

  final String title;
  final Map<String, Object?> values;

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Text(
        '$title：${values.entries.map((entry) => '${entry.key} ${entry.value}').join(' · ')}',
      ),
    );
  }
}

class _LoadFailure extends StatelessWidget {
  const _LoadFailure({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('无法载入跑团记录。'),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: onRetry, child: const Text('重试')),
        ],
      ),
    );
  }
}

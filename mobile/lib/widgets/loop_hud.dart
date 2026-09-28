import 'package:flutter/material.dart';

/// Loop/time HUD for worlds with the time/loop/countdown capabilities.
///
/// Renders nothing when the run state carries neither a clock nor a loop
/// block, so ordinary worlds are unaffected.
class LoopHud extends StatelessWidget {
  const LoopHud({super.key, required this.state});

  final Map<String, dynamic> state;

  @override
  Widget build(BuildContext context) {
    final clock = state['clock'];
    final loop = state['loop'];
    final hasMemory = state['loop_memory'] is Map<String, dynamic>;
    if (clock is! Map<String, dynamic> &&
        loop is! Map<String, dynamic> &&
        !hasMemory) {
      return const SizedBox.shrink();
    }
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (clock is Map<String, dynamic>) ...[
              Row(
                children: [
                  const Icon(Icons.schedule, size: 16),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      _clockLabel(clock),
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                  ),
                  if (loop is Map<String, dynamic>) _loopBadge(loop),
                ],
              ),
              const SizedBox(height: 6),
              LinearProgressIndicator(
                value: _clockFraction(clock),
                minHeight: 6,
                borderRadius: BorderRadius.circular(3),
              ),
              if (_warn(clock)) ...[
                const SizedBox(height: 4),
                Text(
                  _warnText(clock),
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.error,
                    fontSize: 12,
                  ),
                ),
              ],
            ] else if (loop is Map<String, dynamic>)
              _loopBadge(loop),
            if (state['loop_memory'] is Map<String, dynamic>)
              _knowledgePanel(context, state['loop_memory'] as Map<String, dynamic>),
          ],
        ),
      ),
    );
  }

  String _clockLabel(Map<String, dynamic> clock) {
    final minutes = ((clock['now_minutes'] as num?)?.toInt() ?? 0) % 1440;
    final day = (clock['day'] as num?)?.toInt() ?? 1;
    final unit = (clock['unit'] as String?) ?? '分钟';
    final hh = (minutes ~/ 60).toString().padLeft(2, '0');
    final mm = (minutes % 60).toString().padLeft(2, '0');
    return '第 $day 天 · $hh:$mm $unit';
  }

  double? _clockFraction(Map<String, dynamic> clock) {
    final now = (clock['now_minutes'] as num?)?.toInt() ?? 0;
    final countdown = clock['countdown'];
    if (countdown is Map<String, dynamic>) {
      final start = (clock['start_minutes'] as num?)?.toInt();
      if (start != null && start > 0) {
        return (now / start).clamp(0.0, 1.0);
      }
      return null;
    }
    final loopAt = (clock['loop_at_minutes'] as num?)?.toInt();
    if (loopAt != null && loopAt > 0) {
      return (now / loopAt).clamp(0.0, 1.0);
    }
    return (now % 1440) / 1440;
  }

  bool _warn(Map<String, dynamic> clock) {
    final now = (clock['now_minutes'] as num?)?.toInt() ?? 0;
    final loopAt = (clock['loop_at_minutes'] as num?)?.toInt();
    if (loopAt != null && now >= loopAt) return true;
    final countdown = clock['countdown'];
    if (countdown is Map<String, dynamic>) {
      final warnAt = (countdown['warn_at'] as num?)?.toInt();
      if (warnAt != null && now <= warnAt) return true;
    }
    return false;
  }

  String _warnText(Map<String, dynamic> clock) {
    final countdown = clock['countdown'];
    if (countdown is Map<String, dynamic>) {
      final warnAt = (countdown['warn_at'] as num?)?.toInt();
      final now = (clock['now_minutes'] as num?)?.toInt() ?? 0;
      if (warnAt != null && now <= warnAt) return '余量告急';
    }
    return '已到达循环边界';
  }

  Widget _loopBadge(Map<String, dynamic> loop) {
    final count = (loop['count'] as num?)?.toInt() ?? 1;
    final maxLoops = (loop['max_loops'] as num?)?.toInt() ?? 1;
    final finalLoop = count >= maxLoops;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: finalLoop ? Colors.deepPurple.shade100 : Colors.indigo.shade50,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        finalLoop ? '最终循环 $count/$maxLoops' : '第 $count/$maxLoops 次循环',
        style: TextStyle(
          fontSize: 12,
          color: finalLoop ? Colors.deepPurple.shade900 : Colors.indigo.shade900,
        ),
      ),
    );
  }

  Widget _knowledgePanel(BuildContext context, Map<String, dynamic> memory) {
    final knowledge = (memory['knowledge'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList(growable: false);
    final summaries = (memory['summaries'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList(growable: false);
    if (knowledge.isEmpty && summaries.isEmpty) {
      return const SizedBox.shrink();
    }
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 8),
        leading: const Icon(Icons.psychology_alt, size: 18),
        title: const Text('跨循环记忆', style: TextStyle(fontSize: 14)),
        subtitle: Text(
          '${knowledge.length} 条知识 · ${summaries.length} 段循环摘要',
          style: const TextStyle(fontSize: 12),
        ),
        children: [
          for (final item in knowledge)
            Align(
              alignment: Alignment.centerLeft,
              child: Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('• ${item['text'] ?? ''}'),
              ),
            ),
          for (final item in summaries)
            Align(
              alignment: Alignment.centerLeft,
              child: Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '第 ${item['loop_no']} 次循环：${item['summary'] ?? ''}',
                  style: const TextStyle(fontSize: 13, color: Colors.black54),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

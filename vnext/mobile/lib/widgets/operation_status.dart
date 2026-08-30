import 'package:flutter/material.dart';

import '../local_host_port.dart';

class OperationStatusCard extends StatelessWidget {
  const OperationStatusCard({
    super.key,
    required this.stage,
    required this.label,
    required this.elapsedMs,
    this.cancellable = false,
    this.onCancel,
  });

  final String stage;
  final String label;
  final int elapsedMs;
  final bool cancellable;
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final seconds = (elapsedMs / 1000).toStringAsFixed(1);
    return Semantics(
      container: true,
      liveRegion: true,
      label: '$label，已耗时 $seconds 秒',
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const LinearProgressIndicator(),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text('$seconds 秒'),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  for (final step in LocalHostOperationStage.values.take(4))
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.only(right: 4),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: step == stage
                                ? colors.primaryContainer
                                : colors.surfaceContainerHighest,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 4,
                              vertical: 7,
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(
                                  step == LocalHostOperationStage.preparing
                                      ? Icons.check_circle_outline
                                      : Icons.more_horiz,
                                  size: 14,
                                ),
                                const SizedBox(width: 2),
                                Flexible(
                                  child: Text(
                                    LocalHostOperationStage.labels[step]!,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    textAlign: TextAlign.center,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
              if (elapsedMs > 8000) const Text('本地模型可能仍在加载；失败前不会写入半个回合。'),
              if (cancellable && onCancel != null) ...[
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: onCancel,
                  icon: const Icon(Icons.stop_circle_outlined),
                  label: const Text('取消本次行动'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

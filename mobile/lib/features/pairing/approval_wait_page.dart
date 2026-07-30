import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'pairing_controller.dart';

class ApprovalWaitPage extends ConsumerWidget {
  const ApprovalWaitPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(pairingControllerProvider);
    final waiting =
        state.status == PairingStatus.submitting ||
        state.status == PairingStatus.waitingApproval;
    final paired = state.status == PairingStatus.paired;
    return Scaffold(
      appBar: AppBar(title: const Text('等待 Mac 批准')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Icon(
              paired ? Icons.check_circle : Icons.devices,
              size: 56,
              color: paired ? Theme.of(context).colorScheme.secondary : null,
            ),
            const SizedBox(height: 24),
            Text(
              _message(state.status),
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            if (waiting) const LinearProgressIndicator(),
            const SizedBox(height: 24),
            if (waiting)
              OutlinedButton(
                onPressed: () {
                  ref.read(pairingControllerProvider.notifier).cancel();
                  Navigator.of(context).pop(false);
                },
                child: const Text('取消配对'),
              )
            else
              FilledButton(
                onPressed: () => Navigator.of(context).pop(paired),
                child: Text(paired ? '继续' : '返回'),
              ),
          ],
        ),
      ),
    );
  }

  static String _message(PairingStatus status) => switch (status) {
    PairingStatus.paired => '这台手机已与 Mac 配对。',
    PairingStatus.denied => 'Mac 拒绝了这次配对请求。',
    PairingStatus.expired => '配对请求已过期，请重新发起。',
    PairingStatus.rateLimited => '请求过于频繁，请稍后再试。',
    PairingStatus.offline => 'Mac 已离线或关闭了局域网访问。',
    PairingStatus.failed => '配对失败，请返回后重试。',
    _ => '请回到 Mac，在 dzmm 设置中批准这台手机。',
  };
}

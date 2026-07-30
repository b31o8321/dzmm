import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../connection/lan_scanner.dart';
import 'approval_wait_page.dart';
import 'pairing_controller.dart';
import 'pin_pair_sheet.dart';
import 'qr_scan_page.dart';

class PairingMethodPage extends ConsumerWidget {
  const PairingMethodPage({required this.discovered, super.key});

  final DiscoveredServer discovered;

  Future<void> _approval(BuildContext context, WidgetRef ref) async {
    final operation = ref
        .read(pairingControllerProvider.notifier)
        .requestMacApproval(discovered);
    final paired = await Navigator.of(
      context,
    ).push<bool>(MaterialPageRoute(builder: (_) => const ApprovalWaitPage()));
    if (paired != true) {
      ref.read(pairingControllerProvider.notifier).cancel();
    }
    await operation;
    if (paired == true && context.mounted) {
      Navigator.of(context).pop(true);
    }
  }

  Future<void> _pin(BuildContext context, WidgetRef ref) async {
    final pin = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const PinPairSheet(),
    );
    if (pin == null || !context.mounted) return;
    await ref
        .read(pairingControllerProvider.notifier)
        .pairWithPin(discovered, pin);
    if (context.mounted &&
        ref.read(pairingControllerProvider).status == PairingStatus.paired) {
      Navigator.of(context).pop(true);
    }
  }

  Future<void> _qr(BuildContext context, WidgetRef ref) async {
    final payload = await Navigator.of(context).push<DzmmQrPayload>(
      MaterialPageRoute(builder: (_) => const QrScanPage()),
    );
    if (payload == null || !context.mounted) return;
    if (payload.serverId != discovered.serverId) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('二维码属于另一台 Mac，请重新选择主机。')));
      return;
    }
    await ref
        .read(pairingControllerProvider.notifier)
        .pairWithQr(discovered, payload.claim);
    if (context.mounted &&
        ref.read(pairingControllerProvider).status == PairingStatus.paired) {
      Navigator.of(context).pop(true);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(pairingControllerProvider);
    final busy =
        state.status == PairingStatus.submitting ||
        state.status == PairingStatus.waitingApproval;
    return Scaffold(
      appBar: AppBar(title: Text(discovered.name)),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('选择配对方式', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Text('${discovered.endpoint.host}:${discovered.endpoint.port}'),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: busy ? null : () => _approval(context, ref),
            icon: const Icon(Icons.approval_outlined),
            label: const Text('请求 Mac 批准'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: busy ? null : () => _qr(context, ref),
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('扫描二维码'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: busy ? null : () => _pin(context, ref),
            icon: const Icon(Icons.pin_outlined),
            label: const Text('输入六位 PIN'),
          ),
          if (_errorMessage(state) case final message?) ...[
            const SizedBox(height: 20),
            Text(
              message,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
        ],
      ),
    );
  }

  static String? _errorMessage(PairingState state) => switch (state.status) {
    PairingStatus.denied => 'Mac 拒绝了配对请求。',
    PairingStatus.expired => '配对码已过期或已使用。',
    PairingStatus.rateLimited => '尝试过于频繁，请稍后再试。',
    PairingStatus.offline => '无法连接 Mac，请检查局域网访问。',
    PairingStatus.failed => switch (state.errorCode) {
      'bad_pin' || 'bad_pin_format' => 'PIN 不正确，请输入 Mac 上显示的六位数字。',
      'pairing_closed' => 'Mac 当前没有开启 PIN 配对窗口。',
      _ => '配对失败，请重试。',
    },
    _ => null,
  };
}

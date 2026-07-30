import 'package:flutter/material.dart';

import '../../connection/lan_scanner.dart';
import '../../connection/paired_server.dart';
import 'lan_scan_sheet.dart';
import 'qr_scan_page.dart';

class ConnectionOnboardingPage extends StatelessWidget {
  const ConnectionOnboardingPage({
    this.scanner,
    this.pairedServers = const [],
    this.onSelected,
    this.onQrPayload,
    super.key,
  });

  final LanScanner? scanner;
  final List<PairedServer> pairedServers;
  final ValueChanged<DiscoveredServer>? onSelected;
  final ValueChanged<DzmmQrPayload>? onQrPayload;

  Future<void> _openScan(BuildContext context) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => LanScanSheet(
        scanner: scanner ?? LanScanner(),
        pairedServers: pairedServers,
        onSelected: (result) {
          Navigator.of(sheetContext).pop();
          onSelected?.call(result);
        },
      ),
    );
  }

  Future<void> _scanQr(BuildContext context) async {
    final payload = await Navigator.of(context).push<DzmmQrPayload>(
      MaterialPageRoute(builder: (_) => const QrScanPage()),
    );
    if (payload != null) onQrPayload?.call(payload);
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 120),
      children: [
        Icon(
          Icons.wifi_tethering,
          size: 52,
          color: Theme.of(context).colorScheme.primary,
        ),
        const SizedBox(height: 24),
        Text('连接你的 Mac', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 12),
        Text(
          '在 Mac 版 dzmm 的设置中开启局域网访问，然后从这里查找并配对。',
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: 28),
        FilledButton.icon(
          onPressed: () => _openScan(context),
          icon: const Icon(Icons.radar),
          label: const Text('查找 Mac'),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: onQrPayload == null ? null : () => _scanQr(context),
          icon: const Icon(Icons.qr_code_scanner),
          label: const Text('扫描 Mac 配对码'),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.shield_outlined,
                  color: Theme.of(context).colorScheme.secondary,
                ),
                const SizedBox(width: 12),
                const Expanded(
                  child: Text('Android v1 使用局域网 HTTP，只应在你信任的家庭或个人网络中开启。'),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

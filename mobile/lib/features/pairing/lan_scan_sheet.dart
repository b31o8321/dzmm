import 'dart:async';

import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../connection/lan_scanner.dart';
import '../../connection/paired_server.dart';
import 'manual_address_sheet.dart';

class LanScanSheet extends StatefulWidget {
  const LanScanSheet({
    required this.scanner,
    required this.onSelected,
    this.pairedServers = const [],
    super.key,
  });

  final LanScanner scanner;
  final ValueChanged<DiscoveredServer> onSelected;
  final List<PairedServer> pairedServers;

  @override
  State<LanScanSheet> createState() => _LanScanSheetState();
}

class _LanScanSheetState extends State<LanScanSheet> {
  final _results = <String, DiscoveredServer>{};
  StreamSubscription<DiscoveredServer>? _subscription;
  var _scanning = false;
  NearbyPermissionException? _permissionError;
  Object? _scanError;

  @override
  void initState() {
    super.initState();
    unawaited(_scan());
  }

  Future<void> _scan() async {
    await _subscription?.cancel();
    setState(() {
      _scanning = true;
      _permissionError = null;
      _scanError = null;
    });
    _subscription = widget.scanner
        .scan(recentServers: widget.pairedServers)
        .listen(
          (result) => setState(() => _results[result.serverId] = result),
          onError: (Object error) {
            if (!mounted) return;
            setState(() {
              _scanning = false;
              if (error is NearbyPermissionException) {
                _permissionError = error;
              } else {
                _scanError = error;
              }
            });
          },
          onDone: () {
            if (mounted) setState(() => _scanning = false);
          },
        );
  }

  Future<void> _manual() async {
    final endpoint = await showModalBottomSheet<HostEndpoint>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const ManualAddressSheet(),
    );
    if (endpoint == null || !mounted) return;
    final result = await widget.scanner.probeManual(endpoint.uri.toString());
    if (!mounted) return;
    if (result == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('该地址没有返回兼容的 dzmm 服务')));
      return;
    }
    widget.onSelected(result);
  }

  @override
  void dispose() {
    unawaited(_subscription?.cancel());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '查找 Mac',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  tooltip: '重新扫描',
                  onPressed: _scanning ? null : _scan,
                  icon: const Icon(Icons.refresh),
                ),
              ],
            ),
            if (_scanning) const LinearProgressIndicator(),
            const SizedBox(height: 12),
            if (_permissionError != null)
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('需要附近设备权限才能自动查找 Mac。'),
                      if (_permissionError!.permanentlyDenied)
                        TextButton(
                          onPressed: openAppSettings,
                          child: const Text('打开系统设置'),
                        ),
                    ],
                  ),
                ),
              ),
            if (_scanError != null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: Text('扫描中断。请检查 Wi-Fi 后重新扫描。'),
              ),
            if (_results.isEmpty &&
                !_scanning &&
                _permissionError == null &&
                _scanError == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 20),
                child: Text('没有找到主机。确认 Mac 已开启局域网访问，或手动输入地址。'),
              ),
            for (final result in _results.values)
              _DiscoveredHostTile(
                result: result,
                paired: widget.pairedServers.any(
                  (server) => server.serverId == result.serverId,
                ),
                onSelected: widget.onSelected,
              ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _manual,
              icon: const Icon(Icons.keyboard),
              label: const Text('手动输入地址'),
            ),
          ],
        ),
      ),
    );
  }
}

class _DiscoveredHostTile extends StatelessWidget {
  const _DiscoveredHostTile({
    required this.result,
    required this.paired,
    required this.onSelected,
  });

  final DiscoveredServer result;
  final bool paired;
  final ValueChanged<DiscoveredServer> onSelected;

  @override
  Widget build(BuildContext context) {
    final compatible =
        result.health.apiVersion == 1 &&
        result.health.capabilities.contains('session_hydration');
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.laptop_mac),
      title: Text(result.name),
      subtitle: Text(
        compatible
            ? '${result.endpoint.host}:${result.endpoint.port}${paired ? ' · 已配对' : ''}'
            : '版本不兼容',
      ),
      trailing: const Icon(Icons.chevron_right),
      enabled: compatible,
      onTap: compatible ? () => onSelected(result) : null,
    );
  }
}

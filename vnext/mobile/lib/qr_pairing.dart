import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'host_discovery.dart';
import 'mobile_api.dart';

DiscoveredHost parseQrPairingPayload(String raw) {
  final payload = Uri.tryParse(raw);
  if (payload == null ||
      payload.scheme != 'dzmm-next' ||
      payload.host != 'pair') {
    throw const HostApiError(0, '这不是 DZMM 配对二维码。');
  }
  final host = payload.queryParameters['host'];
  final hostId = payload.queryParameters['host_id'];
  if (host == null || hostId == null || hostId.isEmpty) {
    throw const HostApiError(0, '二维码缺少安全配对信息。');
  }
  final uri = localHostUri(host);
  if ((uri.path.isNotEmpty && uri.path != '/') ||
      uri.hasQuery ||
      uri.hasFragment) {
    throw const HostApiError(0, '二维码中的 Host 地址无效。');
  }
  return DiscoveredHost(
    host: uri.host,
    port: uri.hasPort ? uri.port : 8765,
    name: '扫码发现的 DZMM Host',
    hostId: hostId,
  );
}

class QrPairingPage extends StatefulWidget {
  const QrPairingPage({super.key});

  @override
  State<QrPairingPage> createState() => _QrPairingPageState();
}

class _QrPairingPageState extends State<QrPairingPage> {
  bool _handled = false;
  String? _error;

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    final raw = capture.barcodes.firstOrNull?.rawValue;
    if (raw == null) return;
    try {
      final host = parseQrPairingPayload(raw);
      _handled = true;
      Navigator.of(context).pop(host);
    } on HostApiError catch (error) {
      setState(() => _error = error.detail);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('扫描 DZMM 配对码')),
    body: Stack(
      fit: StackFit.expand,
      children: [
        MobileScanner(onDetect: _onDetect),
        Align(
          alignment: Alignment.bottomCenter,
          child: SafeArea(
            child: Container(
              color: Colors.black87,
              padding: const EdgeInsets.all(16),
              child: Text(_error ?? '在 Mac 或 Windows Host 的“手机配对”中扫描二维码。'),
            ),
          ),
        ),
      ],
    ),
  );
}

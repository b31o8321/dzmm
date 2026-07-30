import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../connection/lan_scanner.dart';

class DzmmQrPayload {
  const DzmmQrPayload({
    required this.serverId,
    required this.apiVersion,
    required this.claim,
    required this.expiresAt,
    required this.hosts,
  });

  final String serverId;
  final int apiVersion;
  final String claim;
  final DateTime expiresAt;
  final List<HostEndpoint> hosts;

  static DzmmQrPayload parse(String raw, {DateTime? now}) {
    final decoded = jsonDecode(raw);
    if (decoded is! Map) throw const FormatException('Not a dzmm QR payload');
    final json = decoded.cast<String, Object?>();
    final serverId = json['server_id'];
    final apiVersion = json['api_version'];
    final claim = json['claim'];
    final expiresAtValue = json['expires_at'];
    final hostValues = json['hosts'];
    final expiresAt = expiresAtValue is String
        ? DateTime.tryParse(expiresAtValue)?.toUtc()
        : null;
    if (json['type'] != 'dzmm_pair' ||
        json['version'] != 1 ||
        serverId is! String ||
        serverId.isEmpty ||
        apiVersion != 1 ||
        claim is! String ||
        claim.length < 20 ||
        expiresAt == null ||
        !expiresAt.isAfter((now ?? DateTime.now()).toUtc()) ||
        hostValues is! List) {
      throw const FormatException('Invalid or expired dzmm QR payload');
    }
    final hosts = <HostEndpoint>[];
    for (final value in hostValues) {
      if (value is! String) continue;
      final uri = Uri.tryParse(value.contains('://') ? value : 'http://$value');
      if (uri == null ||
          uri.scheme != 'http' ||
          uri.host.isEmpty ||
          (!isPrivateIpv4(uri.host) &&
              !uri.host.toLowerCase().endsWith('.local'))) {
        continue;
      }
      hosts.add(
        HostEndpoint(
          host: uri.host,
          port: uri.hasPort ? uri.port : 8765,
          source: DiscoverySource.manual,
          expectedServerId: serverId,
        ),
      );
    }
    if (hosts.isEmpty) {
      throw const FormatException('QR payload has no private LAN host');
    }
    return DzmmQrPayload(
      serverId: serverId,
      apiVersion: apiVersion as int,
      claim: claim,
      expiresAt: expiresAt,
      hosts: hosts,
    );
  }

  @override
  String toString() =>
      'DzmmQrPayload(serverId: $serverId, apiVersion: $apiVersion, '
      'expiresAt: $expiresAt, claim: <redacted>)';
}

class QrScanPage extends StatefulWidget {
  const QrScanPage({super.key});

  @override
  State<QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<QrScanPage> {
  final _controller = MobileScannerController();
  var _handled = false;
  String? _error;

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    for (final barcode in capture.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null) continue;
      try {
        final payload = DzmmQrPayload.parse(raw);
        _handled = true;
        Navigator.of(context).pop(payload);
        return;
      } on FormatException {
        setState(() => _error = '这不是有效的 dzmm 配对码');
      }
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text('扫描 Mac 配对码'),
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
      ),
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(
            controller: _controller,
            onDetect: _onDetect,
            errorBuilder: (context, error) => Center(
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: Text(
                  '无法使用相机。请在系统设置中允许 dzmm 使用相机。',
                  textAlign: TextAlign.center,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyLarge?.copyWith(color: Colors.white),
                ),
              ),
            ),
          ),
          Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              margin: const EdgeInsets.all(24),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.72),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Text(
                _error ?? '将 Mac 设置页中的二维码放入取景框',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

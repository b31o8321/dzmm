import 'package:flutter/material.dart';

import '../../connection/lan_scanner.dart';

class ManualAddressSheet extends StatefulWidget {
  const ManualAddressSheet({super.key});

  @override
  State<ManualAddressSheet> createState() => _ManualAddressSheetState();
}

class _ManualAddressSheetState extends State<ManualAddressSheet> {
  final _controller = TextEditingController();
  var _submitting = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final endpoint = await parseManualEndpoint(_controller.text);
      if (mounted) {
        Navigator.of(context).pop(endpoint);
      }
    } on FormatException {
      if (mounted) {
        setState(() => _error = '请输入 10.x、172.16–31.x 或 192.168.x.x 局域网地址');
      }
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          24,
          20,
          24,
          20 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('手动输入 Mac 地址', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            const Text('仅允许可信局域网地址，例如 192.168.31.169:8765。'),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              autofocus: true,
              keyboardType: TextInputType.url,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => _submit(),
              decoration: InputDecoration(
                labelText: 'IP 或 .local 主机名',
                errorText: _error,
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _submitting ? null : _submit,
              child: Text(_submitting ? '验证中…' : '连接'),
            ),
          ],
        ),
      ),
    );
  }
}

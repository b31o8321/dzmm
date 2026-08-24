import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../app_theme.dart';
import '../local_host_port.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({
    super.key,
    required this.theme,
    required this.onTheme,
    required this.port,
    required this.runId,
    required this.onImported,
  });

  final AppTheme theme;
  final Future<void> Function(AppTheme) onTheme;
  final LocalHostPort port;
  final String? runId;
  final Future<void> Function(String) onImported;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool _busy = false;
  String? _notice;

  Future<void> _exportRun() async {
    final runId = widget.runId;
    if (runId == null) return;
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final bundle = await widget.port.exportRun(runId);
      final path = await FilePicker.platform.saveFile(
        fileName: 'dzmm-run-$runId.json',
        bytes: Uint8List.fromList(utf8.encode(jsonEncode(bundle))),
      );
      if (mounted) {
        setState(
          () => _notice = path == null ? '已取消导出。' : '旅程快照已导出；导入后会生成一段独立旅程。',
        );
      }
    } catch (error) {
      if (mounted) setState(() => _notice = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _importBundle() async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['json'],
        withData: true,
      );
      final bytes = result?.files.single.bytes;
      if (bytes == null) {
        if (mounted) setState(() => _notice = '已取消导入。');
        return;
      }
      final bundle = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      final composed = bundle['kind'] == 'run'
          ? await widget.port.cloneRun({
              'request_id':
                  'android-clone-${DateTime.now().microsecondsSinceEpoch}',
              'bundle': bundle,
            })
          : await widget.port.importWorld({
              'request_id':
                  'android-import-${DateTime.now().microsecondsSinceEpoch}',
              'bundle': bundle,
            });
      await widget.onImported(composed.runId);
      if (mounted) setState(() => _notice = '已导入本机；原来的世界和旅程不会被覆盖。');
    } catch (error) {
      if (mounted) setState(() => _notice = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 20, 20, 128),
    children: [
      Text('设置', style: Theme.of(context).textTheme.headlineMedium),
      const SizedBox(height: 8),
      const Card(
        child: Padding(
          padding: EdgeInsets.all(16),
          child: Text('此设备独立保存并运行游戏。不会扫描电脑、局域网服务或二维码，也不会自动同步正在游玩的旅程。'),
        ),
      ),
      const SizedBox(height: 20),
      Text('数据携带', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 8),
      const Text('内容只在你主动导出或导入时移动；不会自动同步，也不会让两台设备同时改写同一段旅程。'),
      const SizedBox(height: 10),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          FilledButton.tonal(
            onPressed: _busy || widget.runId == null ? null : _exportRun,
            child: const Text('导出当前旅程'),
          ),
          OutlinedButton(
            onPressed: _busy ? null : _importBundle,
            child: const Text('导入世界 / 复制旅程'),
          ),
        ],
      ),
      if (_notice != null) ...[const SizedBox(height: 8), Text(_notice!)],
      const SizedBox(height: 20),
      Text('外观', style: Theme.of(context).textTheme.titleLarge),
      for (final value in AppTheme.values)
        ListTile(
          selected: value == widget.theme,
          onTap: () => widget.onTheme(value),
          trailing: value == widget.theme ? const Icon(Icons.check) : null,
          title: Text(switch (value) {
            AppTheme.fog => '雾夜',
            AppTheme.paper => '纸页',
            AppTheme.amber => '琥珀',
          }),
        ),
    ],
  );
}

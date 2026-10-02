import 'dart:async';

import 'package:flutter/material.dart';

import '../local_host_port.dart';
import '../widgets/operation_status.dart';
import '../widgets/runtime_error.dart';
import 'model_edit_page.dart';

/// 模型档案列表页：只负责展示与操作既有档案；
/// 新建/编辑跳转 [ModelEditPage] 表单页。
class ModelsPage extends StatefulWidget {
  const ModelsPage({super.key, required this.port});

  final LocalHostPort port;

  @override
  State<ModelsPage> createState() => _ModelsPageState();
}

class _ModelsPageState extends State<ModelsPage> {
  late Future<List<ModelProfile>> _profiles = widget.port.listModelProfiles();
  final Map<String, ModelProbeResult> _probes = {};
  String? _probingProfileId;
  bool _busy = false;
  String? _error;
  Timer? _operationTicker;
  DateTime? _operationStartedAt;
  String? _operationLabel;
  String _operationStage = LocalHostOperationStage.preparing;
  int _operationElapsedMs = 0;

  @override
  void dispose() {
    _operationTicker?.cancel();
    super.dispose();
  }

  void _beginProbeOperation() {
    _operationTicker?.cancel();
    _operationStartedAt = DateTime.now();
    setState(() {
      _operationStage = LocalHostOperationStage.connecting;
      _operationLabel = '正在连接本地模型…';
      _operationElapsedMs = 0;
    });
    _operationTicker = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (!mounted || _operationStartedAt == null) return;
      setState(() {
        _operationElapsedMs = DateTime.now()
            .difference(_operationStartedAt!)
            .inMilliseconds;
        _operationStage = LocalHostOperationStage.generating;
        _operationLabel = '正在等待模型返回测试结果；已耗时会持续显示。';
      });
    });
  }

  void _endProbeOperation() {
    _operationTicker?.cancel();
    _operationTicker = null;
    _operationStartedAt = null;
    if (!mounted) return;
    setState(() {
      _operationLabel = null;
      _operationElapsedMs = 0;
    });
  }

  void _reload() {
    setState(() {
      _profiles = widget.port.listModelProfiles();
    });
  }

  Future<void> _openEditor([ModelProfile? profile]) async {
    final saved = await Navigator.push<bool>(
      context,
      MaterialPageRoute<bool>(
        builder: (_) => ModelEditPage(port: widget.port, profile: profile),
      ),
    );
    if (saved == true) {
      _reload();
    }
  }

  bool _isAndroidLoopback(String baseUrl) {
    final normalized = baseUrl.trim().toLowerCase();
    return normalized.contains('127.0.0.1') || normalized.contains('localhost');
  }

  Future<void> _setDefault(ModelProfile profile) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.port.setDefaultModelProfile(profile.id);
      _reload();
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete(ModelProfile profile) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除模型档案？'),
        content: Text('“${profile.name}”将从设置中移除，但不会删除模型文件。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.port.deleteModelProfile(profile.id);
      _reload();
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _probe(ModelProfile profile) async {
    setState(() {
      _busy = true;
      _probingProfileId = profile.id;
    });
    _beginProbeOperation();
    try {
      final result = await widget.port.probeModelProfile(profile.id);
      if (mounted) setState(() => _probes[profile.id] = result);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) {
        setState(() {
          _probingProfileId = null;
          _busy = false;
        });
      }
      _endProbeOperation();
    }
  }

  String _contextLabel(ModelProfile profile) {
    final size = profile.contextSize;
    if (size != null) return '上下文 $size';
    return '上下文 自动';
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List<ModelProfile>>(
    future: _profiles,
    builder: (context, snapshot) {
      if (snapshot.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snapshot.hasError) {
        return RuntimeErrorView(error: snapshot.error, onRetry: _reload);
      }
      final profiles = snapshot.requireData;
      return Stack(
        children: [
          ListView(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 128),
            children: [
              if (_operationLabel != null)
                OperationStatusCard(
                  stage: _operationStage,
                  label: _operationLabel!,
                  elapsedMs: _operationElapsedMs,
                ),
              for (final profile in profiles)
                Card(
                  child: Column(
                    children: [
                      ListTile(
                        title: Row(
                          children: [
                            Expanded(child: Text(profile.name)),
                            if (profile.isDefault) const Chip(label: Text('默认')),
                          ],
                        ),
                        subtitle: Text(
                          '${profile.providerType} · ${profile.modelName}\n'
                          '${_contextLabel(profile)} · ${profile.baseUrl}'
                          '${profile.hasApiKey ? '\n凭据已保存' : ''}',
                        ),
                        onTap: _busy ? null : () => _openEditor(profile),
                      ),
                      if (_isAndroidLoopback(profile.baseUrl))
                        const Padding(
                          padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
                          child: Align(
                            alignment: Alignment.centerLeft,
                            child: Text(
                              '该地址只在本机可用；真机请填写电脑局域网 IP（可用表单页的“扫描局域网”发现）。',
                            ),
                          ),
                        ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            TextButton(
                              onPressed: _busy ? null : () => _probe(profile),
                              child: Text(
                                _probingProfileId == profile.id ? '测试中…' : '测试连接',
                              ),
                            ),
                            TextButton(
                              onPressed: _busy ? null : () => _openEditor(profile),
                              child: const Text('编辑'),
                            ),
                            if (!profile.isDefault)
                              TextButton(
                                onPressed: _busy
                                    ? null
                                    : () => _setDefault(profile),
                                child: const Text('设为默认'),
                              ),
                            TextButton(
                              onPressed: _busy ? null : () => _delete(profile),
                              child: const Text('删除'),
                            ),
                            if (_probes[profile.id] != null)
                              Text(
                                _probes[profile.id]!.success
                                    ? '可用 · ${_probes[profile.id]!.detail}'
                                    : '未通过 · ${_probes[profile.id]!.detail}',
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              if (profiles.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('尚未创建模型档案。点击右下角“新建”，可以扫描局域网自动发现电脑上的模型服务。'),
                  ),
                ),
              if (_error != null) InlineError(_error!),
            ],
          ),
          Positioned(
            right: 20,
            bottom: 20,
            child: FloatingActionButton.extended(
              onPressed: _busy ? null : () => _openEditor(),
              icon: const Icon(Icons.add),
              label: const Text('新建'),
            ),
          ),
        ],
      );
    },
  );
}

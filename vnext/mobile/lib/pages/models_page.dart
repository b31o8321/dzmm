import 'dart:async';

import 'package:flutter/material.dart';

import '../local_host_port.dart';
import '../widgets/operation_status.dart';
import '../widgets/runtime_error.dart';

class ModelsPage extends StatefulWidget {
  const ModelsPage({super.key, required this.port});

  final LocalHostPort port;

  @override
  State<ModelsPage> createState() => _ModelsPageState();
}

class _ModelsPageState extends State<ModelsPage> {
  static const _providerBaseUrls = {
    'ollama': 'http://127.0.0.1:11434',
    'lm_studio': 'http://127.0.0.1:1234/v1',
    'openai_compat': '',
  };
  late Future<List<ModelProfile>> _profiles = widget.port.listModelProfiles();
  final _name = TextEditingController(text: '本机模型');
  final _baseUrl = TextEditingController(text: _providerBaseUrls['ollama']);
  final _modelName = TextEditingController();
  final _apiKey = TextEditingController();
  final Map<String, ModelProbeResult> _probes = {};
  String? _probingProfileId;
  String _provider = 'ollama';
  String? _editingProfileId;
  bool _busy = false;
  String? _error;
  final Map<String, String> _fieldErrors = {};
  Timer? _operationTicker;
  DateTime? _operationStartedAt;
  String? _operationLabel;
  String _operationStage = LocalHostOperationStage.preparing;
  int _operationElapsedMs = 0;

  @override
  void dispose() {
    _operationTicker?.cancel();
    _name.dispose();
    _baseUrl.dispose();
    _modelName.dispose();
    _apiKey.dispose();
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
    final profiles = widget.port.listModelProfiles();
    setState(() => _profiles = profiles);
  }

  void _clearFieldError(String field) {
    if (_fieldErrors.remove(field) != null && mounted) setState(() {});
  }

  Future<void> _save() async {
    final fieldErrors = <String, String>{
      if (_name.text.trim().isEmpty) 'name': '请输入模型名称',
      if (_baseUrl.text.trim().isEmpty) 'base_url': '请输入 Base URL',
      if (_modelName.text.trim().isEmpty) 'model_name': '请输入模型名',
    };
    if (fieldErrors.isNotEmpty) {
      setState(() {
        _fieldErrors
          ..clear()
          ..addAll(fieldErrors);
        _error = null;
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _fieldErrors.clear();
    });
    try {
      final payload = {
        'name': _name.text.trim(),
        'provider_type': _provider,
        'base_url': _baseUrl.text.trim(),
        'model_name': _modelName.text.trim(),
        if (_apiKey.text.trim().isNotEmpty) 'api_key': _apiKey.text.trim(),
      };
      if (_editingProfileId == null) {
        await widget.port.createModelProfile(payload);
      } else {
        await widget.port.updateModelProfile(_editingProfileId!, payload);
      }
      _editingProfileId = null;
      _name.text = '本机模型';
      _baseUrl.text = _providerBaseUrls['ollama']!;
      _modelName.clear();
      _apiKey.clear();
      _provider = 'ollama';
      _reload();
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _edit(ModelProfile profile) {
    setState(() {
      _editingProfileId = profile.id;
      _name.text = profile.name;
      _baseUrl.text = profile.baseUrl;
      _modelName.text = profile.modelName;
      _provider = profile.providerType;
      _apiKey.clear();
      _error = null;
    });
  }

  void _selectProvider(String? provider) {
    final next = provider ?? 'ollama';
    setState(() {
      _provider = next;
      _baseUrl.text = _providerBaseUrls[next] ?? '';
      _fieldErrors.remove('base_url');
    });
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
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 128),
        children: [
          if (_operationLabel != null)
            OperationStatusCard(
              stage: _operationStage,
              label: _operationLabel!,
              elapsedMs: _operationElapsedMs,
            ),
          for (final profile in snapshot.requireData)
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
                      '${profile.providerType} · ${profile.modelName}'
                      '${profile.hasApiKey ? ' · 凭据已保存' : ''}\n${profile.baseUrl}',
                    ),
                  ),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Wrap(
                      children: [
                        TextButton(
                          onPressed: _busy ? null : () => _probe(profile),
                          child: Text(
                            _probingProfileId == profile.id ? '测试中…' : '测试连接',
                          ),
                        ),
                        TextButton(
                          onPressed: _busy ? null : () => _edit(profile),
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
          if (_error != null) InlineError(_error!),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _editingProfileId == null ? '添加模型档案' : '编辑模型档案',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _name,
                    onChanged: (_) => _clearFieldError('name'),
                    decoration: InputDecoration(
                      labelText: '名称',
                      errorText: _fieldErrors['name'],
                      suffixIcon: IconButton(
                        onPressed: _name.clear,
                        icon: const Icon(Icons.clear),
                        tooltip: '清空名称',
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  DropdownButtonFormField<String>(
                    initialValue: _provider,
                    decoration: const InputDecoration(labelText: '协议'),
                    items: const [
                      DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
                      DropdownMenuItem(
                        value: 'lm_studio',
                        child: Text('LM Studio / OpenAI'),
                      ),
                      DropdownMenuItem(
                        value: 'openai_compat',
                        child: Text('OpenAI-compatible'),
                      ),
                    ],
                    onChanged: _selectProvider,
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _baseUrl,
                    onChanged: (_) => _clearFieldError('base_url'),
                    decoration: InputDecoration(
                      labelText: 'Base URL',
                      errorText: _fieldErrors['base_url'],
                      suffixIcon: IconButton(
                        onPressed: _baseUrl.clear,
                        icon: const Icon(Icons.clear),
                        tooltip: '清空地址',
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _modelName,
                    onChanged: (_) => _clearFieldError('model_name'),
                    decoration: InputDecoration(
                      labelText: '模型名',
                      errorText: _fieldErrors['model_name'],
                      suffixIcon: IconButton(
                        onPressed: _modelName.clear,
                        icon: const Icon(Icons.clear),
                        tooltip: '清空模型名',
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _apiKey,
                    obscureText: true,
                    enableSuggestions: false,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: 'API Key（可选）',
                      hintText: _editingProfileId == null
                          ? '仅需要鉴权的服务填写'
                          : '留空则保留已保存凭据',
                      helperText: '仅保存在系统安全存储中，不会写入存档或导出包。',
                    ),
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: _busy ? null : _save,
                    child: Text(_editingProfileId == null ? '保存模型档案' : '保存修改'),
                  ),
                ],
              ),
            ),
          ),
          if (snapshot.requireData.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text('尚未创建模型档案。'),
              ),
            ),
        ],
      );
    },
  );
}

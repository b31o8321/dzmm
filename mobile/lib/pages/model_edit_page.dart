import 'dart:io' show Platform;

import 'package:flutter/material.dart';

import '../local_host_port.dart';

/// 模型档案表单页：新建与编辑共用。
///
/// 支持局域网扫描发现服务、拉取远端模型目录下拉选择、
/// 上下文长度配置（未指定时后端按模型名推断，默认 16384）。
class ModelEditPage extends StatefulWidget {
  const ModelEditPage({
    super.key,
    required this.port,
    this.profile,
  });

  final LocalHostPort port;
  final ModelProfile? profile;

  @override
  State<ModelEditPage> createState() => _ModelEditPageState();
}

class _ModelEditPageState extends State<ModelEditPage> {
  static const _providerLabels = {
    'ollama': 'Ollama',
    'lm_studio': 'LM Studio / OpenAI',
    'openai_compat': 'OpenAI-compatible',
  };
  static const _contextChoices = <int?>[
    null,
    4096,
    8192,
    16384,
    32768,
    65536,
    131072,
  ];
  static String get _ollamaBaseUrl =>
      Platform.isAndroid ? 'http://10.0.2.2:11434' : 'http://127.0.0.1:11434';
  static String get _lmStudioBaseUrl => Platform.isAndroid
      ? 'http://10.0.2.2:1234/v1'
      : 'http://127.0.0.1:1234/v1';
  static Map<String, String> get _providerBaseUrls => {
    'ollama': _ollamaBaseUrl,
    'lm_studio': _lmStudioBaseUrl,
    'openai_compat': '',
  };

  late final TextEditingController _name;
  late final TextEditingController _baseUrl;
  late final TextEditingController _modelName;
  final TextEditingController _apiKey = TextEditingController();

  String _provider = 'ollama';
  int? _contextSize;
  bool _busy = false;
  bool _scanning = false;
  bool _loadingModels = false;
  String? _error;
  String? _apiKeySavedHint;
  final Map<String, String> _fieldErrors = {};
  List<String> _remoteModels = const [];

  bool get _editing => widget.profile != null;

  @override
  void initState() {
    super.initState();
    final profile = widget.profile;
    _name = TextEditingController(text: profile?.name ?? '');
    _baseUrl = TextEditingController(text: profile?.baseUrl ?? '');
    _modelName = TextEditingController(text: profile?.modelName ?? '');
    _provider = profile?.providerType ?? 'ollama';
    _contextSize = profile?.contextSize;
    if (_baseUrl.text.trim().isEmpty) {
      _baseUrl.text = _providerBaseUrls[_provider] ?? '';
    }
    if (profile?.hasApiKey ?? false) {
      _apiKeySavedHint = '已保存凭据；留空则保留';
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _baseUrl.dispose();
    _modelName.dispose();
    _apiKey.dispose();
    super.dispose();
  }

  void _selectProvider(String? provider) {
    final next = provider ?? 'ollama';
    setState(() {
      _provider = next;
      // 仅在地址为空或仍是其他协议默认值时预填，避免覆盖手填的局域网地址
      if (_baseUrl.text.trim().isEmpty ||
          _providerBaseUrls.values.contains(_baseUrl.text.trim())) {
        _baseUrl.text = _providerBaseUrls[next] ?? '';
      }
      _remoteModels = const [];
      _fieldErrors.remove('base_url');
    });
  }

  Future<void> _scanLan() async {
    setState(() {
      _scanning = true;
      _error = null;
    });
    try {
      final servers = await widget.port.scanLanModelServers();
      if (!mounted) return;
      if (servers.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('未在局域网发现模型服务；请确认电脑和手机在同一网络，且服务监听了局域网地址。')),
        );
        return;
      }
      final picked = await showModalBottomSheet<DiscoveredModelServer>(
        context: context,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            children: [
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('发现以下模型服务', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
              for (final server in servers)
                ListTile(
                  leading: const Icon(Icons.dns_outlined),
                  title: Text('${server.host}:${server.port}'),
                  subtitle: Text(
                    '${_providerLabels[server.providerHint] ?? server.providerHint}'
                    ' · ${server.models.length} 个模型',
                  ),
                  onTap: () => Navigator.pop(context, server),
                ),
            ],
          ),
        ),
      );
      if (picked == null) return;
      setState(() {
        _provider = picked.providerHint;
        _baseUrl.text = picked.baseUrl;
        _remoteModels = picked.models;
        if (_modelName.text.isEmpty && picked.models.isNotEmpty) {
          _modelName.text = picked.models.first;
        }
      });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  Future<void> _fetchModels() async {
    if (_baseUrl.text.trim().isEmpty) {
      setState(() => _fieldErrors['base_url'] = '先填写 Base URL 再获取模型列表');
      return;
    }
    setState(() {
      _loadingModels = true;
      _fieldErrors.remove('base_url');
      _error = null;
    });
    try {
      final apiKey = _apiKey.text.trim();
      final models = await widget.port.listRemoteModels(
        _provider,
        _baseUrl.text.trim(),
        apiKey: apiKey.isNotEmpty ? apiKey : null,
      );
      if (!mounted) return;
      setState(() => _remoteModels = models);
      if (models.isEmpty) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('服务可达，但未返回模型；可手动输入模型名。')));
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loadingModels = false);
    }
  }

  Future<void> _save() async {
    final fieldErrors = <String, String>{
      if (_name.text.trim().isEmpty) 'name': '请输入模型名称',
      if (_baseUrl.text.trim().isEmpty) 'base_url': '请输入 Base URL',
      if (_modelName.text.trim().isEmpty) 'model_name': '请输入或选择模型名',
    };
    if (fieldErrors.isNotEmpty) {
      setState(() {
        _fieldErrors
          ..clear()
          ..addAll(fieldErrors)
          ..remove('api_key');
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final payload = {
        'name': _name.text.trim(),
        'provider_type': _provider,
        'base_url': _baseUrl.text.trim(),
        'model_name': _modelName.text.trim(),
        if (_contextSize != null) 'context_size': _contextSize,
        if (_apiKey.text.trim().isNotEmpty) 'api_key': _apiKey.text.trim(),
      };
      if (_editing) {
        await widget.port.updateModelProfile(widget.profile!.id, payload);
      } else {
        await widget.port.createModelProfile(payload);
      }
      if (!mounted) return;
      Navigator.pop(context, true);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(_editing ? '编辑模型' : '新建模型')),
    body: ListView(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
      children: [
        OutlinedButton.icon(
          onPressed: _busy || _scanning ? null : _scanLan,
          icon: _scanning
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.radar),
          label: Text(_scanning ? '正在扫描局域网…' : '扫描局域网自动发现服务'),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _name,
          decoration: InputDecoration(
            labelText: '名称',
            errorText: _fieldErrors['name'],
            suffixIcon: IconButton(onPressed: _name.clear, icon: const Icon(Icons.clear)),
          ),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _provider,
          decoration: const InputDecoration(labelText: '协议'),
          items: [
            for (final entry in _providerLabels.entries)
              DropdownMenuItem(value: entry.key, child: Text(entry.value)),
          ],
          onChanged: _selectProvider,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _baseUrl,
          keyboardType: TextInputType.url,
          decoration: InputDecoration(
            labelText: 'Base URL',
            errorText: _fieldErrors['base_url'],
            hintText: _provider == 'ollama' ? 'http://192.168.x.x:11434' : 'http://192.168.x.x:1234/v1',
            suffixIcon: IconButton(onPressed: _baseUrl.clear, icon: const Icon(Icons.clear)),
          ),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<int?>(
          initialValue: _contextSize,
          decoration: const InputDecoration(
            labelText: '上下文长度',
            helperText: '不指定时按模型名推断（默认 16384）；测试连接也会使用该值加载模型',
          ),
          items: [
            for (final choice in _contextChoices)
              DropdownMenuItem(
                value: choice,
                child: Text(
                  choice == null ? '自动（按模型名推断）' : '$choice',
                ),
              ),
          ],
          onChanged: (value) => setState(() => _contextSize = value),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _modelName,
          decoration: InputDecoration(
            labelText: '模型名',
            errorText: _fieldErrors['model_name'],
            helperText: _remoteModels.isEmpty ? '可手动输入，或先扫描/获取模型列表' : '点击下方候选快速填入',
            suffixIcon: IconButton(
              onPressed: _busy || _loadingModels ? null : _fetchModels,
              icon: _loadingModels
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh),
              tooltip: '从服务获取模型列表',
            ),
          ),
        ),
        if (_remoteModels.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final model in _remoteModels)
                  ActionChip(
                    label: Text(model),
                    onPressed: () => setState(() => _modelName.text = model),
                  ),
              ],
            ),
          ),
        const SizedBox(height: 12),
        TextField(
          controller: _apiKey,
          obscureText: true,
          enableSuggestions: false,
          autocorrect: false,
          decoration: InputDecoration(
            labelText: 'API Key（可选）',
            helperText: _apiKeySavedHint ?? '仅保存在系统安全存储中，不会写入存档或导出包。',
          ),
        ),
        const SizedBox(height: 16),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: Text(_editing ? '保存修改' : '保存模型档案'),
        ),
      ],
    ),
  );
}

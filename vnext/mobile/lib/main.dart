import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import 'app_theme.dart';
import 'local_host_port.dart';
import 'pages/models_page.dart';
import 'widgets/operation_status.dart';
import 'pages/play_page.dart';
import 'pages/settings_page.dart';
import 'session_store.dart';
import 'widgets/runtime_error.dart';

void main() => runApp(const DzmmMobileApp());

class DzmmMobileApp extends StatefulWidget {
  const DzmmMobileApp({super.key, this.port, this.sessionStore});

  final LocalHostPort? port;
  final SessionStore? sessionStore;

  @override
  State<DzmmMobileApp> createState() => _DzmmMobileAppState();
}

class _DzmmMobileAppState extends State<DzmmMobileApp> {
  late final LocalHostPort _port = widget.port ?? EmbeddedPythonLocalHostPort();
  late final SessionStore _store =
      widget.sessionStore ?? const SecureSessionStore();
  AppTheme _theme = AppTheme.fog;

  @override
  void initState() {
    super.initState();
    _restoreTheme();
  }

  Future<void> _restoreTheme() async {
    final stored = await _store.readTheme();
    if (!mounted) return;
    setState(
      () => _theme = AppTheme.values.byName(stored ?? AppTheme.fog.name),
    );
  }

  Future<void> _setTheme(AppTheme theme) async {
    setState(() => _theme = theme);
    await _store.saveTheme(theme.name);
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'DZMM Next',
    debugShowCheckedModeBanner: false,
    theme: themeDataFor(_theme),
    home: _LocalShell(
      port: _port,
      store: _store,
      theme: _theme,
      onTheme: _setTheme,
    ),
  );
}

Future<ComposeResult?> _createRunForWorld(
  BuildContext context,
  LocalHostPort port,
  WorldDetail detail,
) async {
  final controller = TextEditingController(text: '旅行者');
  final profiles = await port.listModelProfiles();
  if (!context.mounted) {
    controller.dispose();
    return null;
  }
  final defaultIndex = profiles.indexWhere((profile) => profile.isDefault);
  String? selectedModelProfileId = profiles.isEmpty
      ? null
      : profiles[defaultIndex >= 0 ? defaultIndex : 0].id;
  final heroName = await showDialog<String>(
    context: context,
    builder: (context) => StatefulBuilder(
      builder: (context, setDialogState) => AlertDialog(
        title: Text('在「${detail.name}」开始新旅程'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: controller,
              maxLength: 120,
              decoration: const InputDecoration(labelText: '主角名称'),
            ),
            DropdownButtonFormField<String?>(
              initialValue: selectedModelProfileId,
              decoration: const InputDecoration(labelText: '叙事模型'),
              items: [
                const DropdownMenuItem(value: null, child: Text('暂不使用模型')),
                for (final profile in profiles)
                  DropdownMenuItem(
                    value: profile.id,
                    child: Text(
                      profile.isDefault ? '${profile.name}（默认）' : profile.name,
                    ),
                  ),
              ],
              onChanged: (value) =>
                  setDialogState(() => selectedModelProfileId = value),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              final name = controller.text.trim();
              if (name.isNotEmpty) Navigator.pop(context, name);
            },
            child: const Text('进入开场'),
          ),
        ],
      ),
    ),
  );
  controller.dispose();
  if (heroName == null) return null;
  return port.createRun(detail.id, {
    'request_id': 'run-${DateTime.now().microsecondsSinceEpoch}',
    'world_version_id': detail.worldVersionId,
    'hero': {'name': heroName, 'profile': <String, dynamic>{}},
    'model_profile_id': selectedModelProfileId,
  });
}

class _LocalShell extends StatefulWidget {
  const _LocalShell({
    required this.port,
    required this.store,
    required this.theme,
    required this.onTheme,
  });

  final LocalHostPort port;
  final SessionStore store;
  final AppTheme theme;
  final Future<void> Function(AppTheme) onTheme;

  @override
  State<_LocalShell> createState() => _LocalShellState();
}

class _LocalShellState extends State<_LocalShell> {
  int _tab = 0;
  String? _activeRunId;
  String? _recoveryNotice;
  late final Future<Map<String, dynamic>> _health = widget.port.runtimeHealth();

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final session = await widget.store.read();
    if (session.pendingRunOperation) {
      await widget.store.save(
        LocalSession(
          runId: session.runId,
          modelProfileId: session.modelProfileId,
          pendingRunOperation: false,
        ),
      );
    }
    if (mounted) {
      setState(() {
        _activeRunId = session.runId;
        if (session.runId != null) _tab = 2;
        _recoveryNotice = session.pendingRunOperation
            ? '上一次旅程操作在应用关闭前没有完成；本机没有写入半个回合，你可以重新选择。'
            : null;
      });
    }
    if (session.runId == null) {
      final profiles = await widget.port.listModelProfiles();
      if (mounted && profiles.isEmpty) setState(() => _tab = 3);
    }
  }

  Future<void> _openRun(String runId) async {
    setState(() {
      _activeRunId = runId;
      _tab = 2;
    });
    final previous = await widget.store.read();
    await widget.store.save(
      LocalSession(
        runId: runId,
        modelProfileId: previous.modelProfileId,
        pendingRunOperation: false,
      ),
    );
  }

  Future<void> _setPendingRunOperation(bool pending) async {
    final previous = await widget.store.read();
    await widget.store.save(
      LocalSession(
        runId: previous.runId,
        modelProfileId: previous.modelProfileId,
        pendingRunOperation: pending,
      ),
    );
  }

  Future<void> _startNewRun(String worldId) async {
    final detail = await widget.port.getWorld(worldId);
    if (!mounted) return;
    final created = await _createRunForWorld(context, widget.port, detail);
    if (created != null) await _openRun(created.runId);
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      _WorldsPage(
        port: widget.port,
        onOpenRun: _openRun,
        onCreate: () => setState(() => _tab = 1),
      ),
      _CreatePage(port: widget.port, onCreated: _openRun),
      PlayPage(
        port: widget.port,
        runId: _activeRunId,
        onStartNewRun: _startNewRun,
        onReturnToWorlds: () => setState(() => _tab = 0),
        onPendingRunOperation: _setPendingRunOperation,
      ),
      ModelsPage(port: widget.port),
      SettingsPage(
        theme: widget.theme,
        onTheme: widget.onTheme,
        port: widget.port,
        runId: _activeRunId,
        onImported: _openRun,
      ),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('DZMM Next'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(24),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: FutureBuilder<Map<String, dynamic>>(
              future: _health,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Text('正在准备本机游戏服务…');
                }
                if (snapshot.hasError) {
                  return const Text('本机游戏服务需要恢复');
                }
                return const Text('本机游戏服务已就绪 · 存档只保存在此设备');
              },
            ),
          ),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (_recoveryNotice != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                child: Card(
                  color: Theme.of(context).colorScheme.secondaryContainer,
                  child: ListTile(
                    leading: const Icon(Icons.history_toggle_off_outlined),
                    title: Text(_recoveryNotice!),
                    trailing: IconButton(
                      tooltip: '关闭提示',
                      onPressed: () => setState(() => _recoveryNotice = null),
                      icon: const Icon(Icons.close),
                    ),
                  ),
                ),
              ),
            Expanded(child: pages[_tab]),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (index) => setState(() => _tab = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.public_outlined), label: '世界'),
          NavigationDestination(
            icon: Icon(Icons.auto_awesome_outlined),
            label: '创作',
          ),
          NavigationDestination(
            icon: Icon(Icons.menu_book_outlined),
            label: '游玩',
          ),
          NavigationDestination(icon: Icon(Icons.memory_outlined), label: '模型'),
          NavigationDestination(icon: Icon(Icons.tune_outlined), label: '设置'),
        ],
      ),
    );
  }
}

class _WorldsPage extends StatefulWidget {
  const _WorldsPage({
    required this.port,
    required this.onOpenRun,
    required this.onCreate,
  });

  final LocalHostPort port;
  final Future<void> Function(String) onOpenRun;
  final VoidCallback onCreate;

  @override
  State<_WorldsPage> createState() => _WorldsPageState();
}

class _WorldsPageState extends State<_WorldsPage> {
  late Future<List<WorldSummary>> _worlds = widget.port.listWorlds();

  void _reload() {
    final worlds = widget.port.listWorlds();
    setState(() {
      _worlds = worlds;
    });
  }

  Future<void> _openWorld(WorldSummary world) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _WorldRunsSheet(
        port: widget.port,
        world: world,
        onOpenRun: widget.onOpenRun,
      ),
    );
    _reload();
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List<WorldSummary>>(
    future: _worlds,
    builder: (context, snapshot) {
      if (snapshot.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snapshot.hasError) {
        return RuntimeErrorView(error: snapshot.error, onRetry: _reload);
      }
      final worlds = snapshot.requireData;
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 128),
        children: [
          Text('你的世界', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 8),
          const Text('每台设备各自保存世界、旅程和模型档案。需要迁移时，再由你主动导入或导出。'),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: widget.onCreate,
            icon: const Icon(Icons.add),
            label: const Text('创建本机世界'),
          ),
          const SizedBox(height: 16),
          if (worlds.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(20),
                child: Text('还没有世界。从雾港模板或 AI 草案开始。'),
              ),
            ),
          for (final world in worlds)
            Card(
              child: ListTile(
                title: Text(world.name),
                subtitle: Text(
                  '${world.status == 'active' ? '可游玩' : '已归档'} · ${world.runCount} 段旅程',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _openWorld(world),
              ),
            ),
        ],
      );
    },
  );
}

class _WorldRunsSheet extends StatefulWidget {
  const _WorldRunsSheet({
    required this.port,
    required this.world,
    required this.onOpenRun,
  });

  final LocalHostPort port;
  final WorldSummary world;
  final Future<void> Function(String) onOpenRun;

  @override
  State<_WorldRunsSheet> createState() => _WorldRunsSheetState();
}

class _WorldRunsSheetState extends State<_WorldRunsSheet> {
  late Future<WorldDetail> _detail = widget.port.getWorld(widget.world.id);
  bool _creating = false;
  String? _error;

  Future<void> _exportWorld() async {
    setState(() {
      _creating = true;
      _error = null;
    });
    try {
      final bundle = await widget.port.exportWorld(widget.world.id);
      final path = await FilePicker.platform.saveFile(
        fileName: 'dzmm-world-${widget.world.id}.json',
        bytes: Uint8List.fromList(utf8.encode(jsonEncode(bundle))),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(path == null ? '已取消导出。' : '世界包已导出；导入后会创建独立的新世界与旅程。'),
          ),
        );
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _toggleArchive() async {
    final archived = widget.world.status == 'archived';
    if (!archived) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('归档这个世界？'),
          content: const Text('已有旅程会保留，但归档期间不能继续或开始新的旅程。之后可以恢复。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('归档'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    setState(() {
      _creating = true;
      _error = null;
    });
    try {
      if (archived) {
        await widget.port.restoreWorld(widget.world.id);
      } else {
        await widget.port.archiveWorld(widget.world.id);
      }
      if (mounted) Navigator.of(context).pop();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _deleteWorld() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('永久删除这个世界？'),
        content: Text(
          '“${widget.world.name}”及其 ${widget.world.runCount} 段旅程、回合记录和历史内容都会从本机删除，无法恢复。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除世界及旅程'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _creating = true;
      _error = null;
    });
    try {
      await widget.port.deleteWorld(widget.world.id);
      if (mounted) Navigator.of(context).pop();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _continue(String runId) async {
    Navigator.of(context).pop();
    await widget.onOpenRun(runId);
  }

  Future<void> _newRun(WorldDetail detail) async {
    setState(() {
      _creating = true;
      _error = null;
    });
    try {
      final result = await _createRunForWorld(context, widget.port, detail);
      if (!mounted || result == null) return;
      Navigator.of(context).pop();
      await widget.onOpenRun(result.runId);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    child: Padding(
      padding: EdgeInsets.fromLTRB(
        20,
        20,
        20,
        MediaQuery.viewInsetsOf(context).bottom + 24,
      ),
      child: FutureBuilder<WorldDetail>(
        future: _detail,
        builder: (context, snapshot) {
          if (!snapshot.hasData &&
              snapshot.connectionState != ConnectionState.done) {
            return const SizedBox(
              height: 240,
              child: Center(child: CircularProgressIndicator()),
            );
          }
          if (snapshot.hasError) {
            return RuntimeErrorView(
              error: snapshot.error,
              onRetry: () => setState(
                () => _detail = widget.port.getWorld(widget.world.id),
              ),
            );
          }
          final detail = snapshot.requireData;
          return ListView(
            shrinkWrap: true,
            children: [
              Text(
                detail.name,
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 6),
              Text('${detail.runs.length} 段旅程；同一个世界可以重复游玩，彼此存档独立。'),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _creating || widget.world.status != 'active'
                    ? null
                    : () => _newRun(detail),
                icon: const Icon(Icons.add),
                label: Text(
                  _creating
                      ? '正在处理…'
                      : widget.world.status == 'active'
                      ? '开始新旅程'
                      : '世界已归档，暂不可开始',
                ),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: _creating ? null : _toggleArchive,
                icon: Icon(
                  widget.world.status == 'active'
                      ? Icons.archive_outlined
                      : Icons.unarchive_outlined,
                ),
                label: Text(widget.world.status == 'active' ? '归档世界' : '恢复世界'),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: _creating ? null : _exportWorld,
                icon: const Icon(Icons.file_download_outlined),
                label: const Text('导出世界包'),
              ),
              const SizedBox(height: 8),
              TextButton.icon(
                onPressed: _creating ? null : _deleteWorld,
                style: TextButton.styleFrom(
                  foregroundColor: Theme.of(context).colorScheme.error,
                ),
                icon: const Icon(Icons.delete_forever_outlined),
                label: const Text('删除世界及全部旅程'),
              ),
              const SizedBox(height: 10),
              for (final run in detail.runs)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.book_outlined),
                  title: Text(run.heroName),
                  subtitle: Text(run.status == 'completed' ? '旅程已完成' : '旅程进行中'),
                  trailing: Text(
                    widget.world.status == 'active' ? '继续' : '世界已归档',
                  ),
                  enabled: !_creating && widget.world.status == 'active',
                  onTap: _creating || widget.world.status != 'active'
                      ? null
                      : () => _continue(run.id),
                ),
              if (_error != null) InlineError(_error!),
            ],
          );
        },
      ),
    ),
  );
}

class _CreatePage extends StatefulWidget {
  const _CreatePage({required this.port, required this.onCreated});

  final LocalHostPort port;
  final Future<void> Function(String) onCreated;

  @override
  State<_CreatePage> createState() => _CreatePageState();
}

class _CreatePageState extends State<_CreatePage> {
  static const _templateProfile = '__local_template__';
  final _genre = TextEditingController(text: '潮汐悬疑恋爱冒险');
  final _tone = TextEditingController(text: '温柔、危险');
  final _conflict = TextEditingController(text: '失踪航图正在重开潮门。');
  final _draftWorldName = TextEditingController();
  final _draftHeroName = TextEditingController();
  AIWorldDraft? _draft;
  AIWorldDraft? _lastValidDraft;
  late final Future<List<ModelProfile>> _profiles = widget.port
      .listModelProfiles();
  String? _modelProfileId;
  String? _draftModelProfileId;
  bool _busy = false;
  bool _generating = false;
  String? _draftRequestId;
  String? _error;
  String _operationStage = LocalHostOperationStage.preparing;
  String? _operationLabel;
  int _operationElapsedMs = 0;
  Timer? _operationTicker;
  DateTime? _operationStartedAt;

  @override
  void dispose() {
    _operationTicker?.cancel();
    _genre.dispose();
    _tone.dispose();
    _conflict.dispose();
    _draftWorldName.dispose();
    _draftHeroName.dispose();
    super.dispose();
  }

  void _beginOperation(
    String label, {
    String stage = LocalHostOperationStage.preparing,
  }) {
    _operationTicker?.cancel();
    _operationStartedAt = DateTime.now();
    setState(() {
      _operationStage = stage;
      _operationLabel = label;
      _operationElapsedMs = 0;
    });
    _operationTicker = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (!mounted || _operationStartedAt == null) return;
      setState(() {
        _operationElapsedMs = DateTime.now()
            .difference(_operationStartedAt!)
            .inMilliseconds;
      });
    });
  }

  void _advanceOperation(String stage, String label) {
    if (!mounted) return;
    setState(() {
      _operationStage = stage;
      _operationLabel = label;
    });
  }

  void _endOperation() {
    _operationTicker?.cancel();
    _operationTicker = null;
    _operationStartedAt = null;
    if (!mounted) return;
    setState(() {
      _operationLabel = null;
      _operationElapsedMs = 0;
    });
  }

  Future<void> _showModelGeneration() async {
    _advanceOperation(LocalHostOperationStage.connecting, '正在连接本机模型…');
    await Future<void>.delayed(const Duration(milliseconds: 16));
    if (mounted) {
      _advanceOperation(
        LocalHostOperationStage.generating,
        '模型正在起草世界；已耗时会持续显示。',
      );
    }
  }

  Future<void> _generate() async {
    final draftRequestId = 'draft-${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _busy = true;
      _generating = true;
      _draftRequestId = draftRequestId;
      _error = null;
    });
    _beginOperation('正在准备世界草案…');
    try {
      final profiles = await _profiles;
      final preferredProfile = profiles.isEmpty
          ? null
          : profiles.firstWhere(
              (profile) => profile.isDefault,
              orElse: () => profiles.first,
            );
      final selectedProfile = _modelProfileId == _templateProfile
          ? null
          : _modelProfileId ?? preferredProfile?.id;
      _draftModelProfileId = selectedProfile;
      await _showModelGeneration();
      final draft = await widget.port.generateDraft({
        'genre': _genre.text,
        'tone': _tone.text,
        'core_conflict': _conflict.text,
        'ruleset': 'hybrid',
        'model_profile_id': selectedProfile,
        'request_id': draftRequestId,
      });
      if (!mounted || _draftRequestId != draftRequestId) return;
      _advanceOperation(LocalHostOperationStage.applying, '草案已返回，正在读取校验结果…');
      await Future<void>.delayed(const Duration(milliseconds: 16));
      setState(() {
        _draft = draft;
        _syncDraftEditors(draft);
        if (draft.valid) _lastValidDraft = draft;
      });
    } catch (error) {
      if (mounted && _draftRequestId == draftRequestId) {
        setState(() => _error = playerSafeDraftError(error));
      }
    } finally {
      if (mounted) {
        _endOperation();
        if (_draftRequestId == draftRequestId) {
          setState(() {
            _draftRequestId = null;
            _busy = false;
            _generating = false;
          });
        }
      }
    }
  }

  Future<void> _cancelGenerate() async {
    if (!_generating) return;
    final requestId = _draftRequestId;
    var cancellationDelivered = true;
    if (requestId != null) {
      try {
        await widget.port.cancelOperation(requestId);
      } catch (_) {
        cancellationDelivered = false;
      }
    }
    _endOperation();
    setState(() {
      _draftRequestId = null;
      _generating = false;
      _busy = false;
      _error = cancellationDelivered
          ? '已取消本次起草；没有创建世界、旅程或其他存档。'
          : '已停止等待本次起草；没有创建世界、旅程或其他存档。';
    });
  }

  void _syncDraftEditors(AIWorldDraft draft) {
    _draftWorldName.text = (draft.worldDefinition?['name'] as String?) ?? '';
    _draftHeroName.text = (draft.hero?['name'] as String?) ?? '';
  }

  Future<void> _validateDraftEdits() async {
    final draft = _draft;
    final definition = draft?.worldDefinition;
    final hero = draft?.hero;
    if (definition == null || hero == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final editedDefinition = Map<String, dynamic>.from(definition)
        ..['name'] = _draftWorldName.text.trim();
      final editedHero = Map<String, dynamic>.from(hero)
        ..['name'] = _draftHeroName.text.trim();
      final validated = await widget.port.validateDraft({
        'world_definition': editedDefinition,
        'hero': editedHero,
      });
      if (!mounted) return;
      setState(() {
        _draft = validated;
        _syncDraftEditors(validated);
        if (validated.valid) _lastValidDraft = validated;
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _composeDraft() async {
    final draft = _draft;
    if (draft == null ||
        !draft.valid ||
        draft.worldDefinition == null ||
        draft.hero == null) {
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.port.composeWorld({
        'request_id': 'android-${DateTime.now().microsecondsSinceEpoch}',
        'world_definition': draft.worldDefinition,
        'hero': draft.hero,
        'model_profile_id': _draftModelProfileId,
      });
      await widget.onCreated(result.runId);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 128),
      children: [
        Text('AI 世界创作', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        const Text('模型只生成待审阅草案；确认前不会创建世界、旅程或修改真实存档。'),
        const SizedBox(height: 20),
        TextField(
          controller: _genre,
          decoration: const InputDecoration(labelText: '题材'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _tone,
          decoration: const InputDecoration(labelText: '基调'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _conflict,
          decoration: const InputDecoration(labelText: '核心冲突'),
        ),
        const SizedBox(height: 12),
        FutureBuilder<List<ModelProfile>>(
          future: _profiles,
          builder: (context, snapshot) {
            final profiles = snapshot.data ?? const <ModelProfile>[];
            if (profiles.isEmpty) {
              return const Text('尚未配置本机模型档案；可先在“模型”入口添加。');
            }
            final preferredProfile = profiles.firstWhere(
              (profile) => profile.isDefault,
              orElse: () => profiles.first,
            );
            return DropdownButtonFormField<String>(
              initialValue: _modelProfileId ?? preferredProfile.id,
              decoration: const InputDecoration(labelText: '草案模型'),
              items: [
                const DropdownMenuItem(
                  value: _templateProfile,
                  child: Text('本机模板（不调用模型）'),
                ),
                for (final profile in profiles)
                  DropdownMenuItem(
                    value: profile.id,
                    child: Text(
                      profile.isDefault ? '${profile.name}（默认）' : profile.name,
                    ),
                  ),
              ],
              onChanged: (value) => setState(() => _modelProfileId = value),
            );
          },
        ),
        if (_modelProfileId == _templateProfile)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              '本机模板是固定的雾港离线示例，不会使用上面的题材、基调和冲突；要生成匹配当前设定的世界，请选择一个模型档案。',
            ),
          ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy ? null : _generate,
          child: Text(_busy ? '正在起草…' : '生成待审阅草案'),
        ),
        if (_generating)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: _cancelGenerate,
              child: const Text('取消起草'),
            ),
          ),
        if (_operationLabel != null)
          OperationStatusCard(
            stage: _operationStage,
            label: _operationLabel!,
            elapsedMs: _operationElapsedMs,
          ),
        if (_error != null) InlineError(_error!),
        if (_draft != null) ...[
          const SizedBox(height: 20),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _draft!.valid ? '草案已通过本机规则校验' : '草案暂不能创建',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  Text(_draft!.summary ?? '模型没有提供摘要。'),
                  if (_draft!.worldDefinition != null &&
                      _draft!.hero != null) ...[
                    const SizedBox(height: 12),
                    _DraftMaterialSummary(definition: _draft!.worldDefinition!),
                    const SizedBox(height: 12),
                    TextField(
                      key: const ValueKey('draft-world-name'),
                      controller: _draftWorldName,
                      enabled: !_busy,
                      decoration: const InputDecoration(
                        labelText: '世界名称（草案编辑）',
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      key: const ValueKey('draft-hero-name'),
                      controller: _draftHeroName,
                      enabled: !_busy,
                      decoration: const InputDecoration(
                        labelText: '主角名称（草案编辑）',
                      ),
                    ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: OutlinedButton(
                        onPressed: _busy ? null : _validateDraftEdits,
                        child: const Text('验证编辑'),
                      ),
                    ),
                  ],
                  if (_draft!.valid && _draft!.repairs.isNotEmpty)
                    const _DraftPlayerNotice(
                      valid: true,
                      message: '模型提供的部分规则不能直接使用，已由本机规则接管章节、选项和结局；这份世界仍然可以正常游玩。',
                    ),
                  if (!_draft!.valid)
                    const _DraftPlayerNotice(
                      valid: false,
                      message: '这份草案缺少可安全游玩的必要内容，暂时不能创建世界。请重新生成，或补充主角、地点和角色素材。',
                    ),
                  if (!_draft!.valid && _lastValidDraft != null)
                    OutlinedButton(
                      onPressed: () => setState(() {
                        _draft = _lastValidDraft;
                        if (_draft != null) _syncDraftEditors(_draft!);
                      }),
                      child: const Text('恢复上一次有效草案'),
                    ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: _busy || !_draft!.valid ? null : _composeDraft,
                    child: const Text('确认并创建本机世界'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

String playerSafeDraftError(Object error) {
  final message = error.toString();
  if (message.contains('model draft is not valid JSON') ||
      message.contains('model draft is not a single JSON object')) {
    return '模型返回的世界草案格式不完整，未创建世界。请重试或切换模型。';
  }
  if (message.contains('model returned no draft content')) {
    return '模型没有返回世界草案，未创建世界。请重试或切换模型。';
  }
  return message;
}

class _DraftMaterialSummary extends StatelessWidget {
  const _DraftMaterialSummary({required this.definition});

  final Map<String, dynamic> definition;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('生成素材摘要', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          for (final entry in _materialEntries)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('${entry.$1}：${entry.$2}'),
            ),
          const SizedBox(height: 4),
          Text(
            '章节、选项、关系、路线和结局由本机 hybrid 规则校验与接管；模型素材只在确认前展示并映射。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }

  List<(String, String)> get _materialEntries => [
    _entry('地点', definition['locations']),
    _entry('角色/NPC', [
      ..._asList(definition['character_cards']),
      ..._asList(definition['npcs']),
    ]),
    _entry('势力', definition['factions']),
    _entry('事件', definition['events']),
  ];

  (String, String) _entry(String label, Object? value) {
    final items = _asList(value);
    if (items.isEmpty) return (label, '暂无模型素材（将使用受控骨架）');
    final names = items
        .map((item) => item is Map ? item['name'] : null)
        .whereType<String>()
        .where((name) => name.trim().isNotEmpty)
        .map((name) => name.trim())
        .toSet()
        .toList(growable: false);
    if (names.isEmpty) return (label, '${items.length} 项');
    final preview = names.take(4).join('、');
    final suffix = names.length > 4 ? ' 等 ${names.length} 项' : '';
    return (label, '$preview$suffix');
  }

  List<dynamic> _asList(Object? value) =>
      value is List<dynamic> ? value : const <dynamic>[];
}

class _DraftPlayerNotice extends StatelessWidget {
  const _DraftPlayerNotice({required this.valid, required this.message});

  final bool valid;
  final String message;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(top: 8),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: valid
          ? Theme.of(context).colorScheme.secondaryContainer
          : Theme.of(context).colorScheme.errorContainer,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(valid ? Icons.info_outline : Icons.block_outlined),
        const SizedBox(width: 8),
        Expanded(child: Text(message)),
      ],
    ),
  );
}

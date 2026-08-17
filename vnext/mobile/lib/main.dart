import 'package:flutter/material.dart';

import 'host_discovery.dart';
import 'mobile_api.dart';
import 'qr_pairing.dart';
import 'session_store.dart';

void main() => runApp(const DzmmMobileApp());

class DzmmMobileApp extends StatelessWidget {
  const DzmmMobileApp({super.key, this.api, this.sessionStore, this.discovery});

  final MobileApi? api;
  final SessionStore? sessionStore;
  final HostDiscovery? discovery;

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'DZMM Next',
    theme: ThemeData(
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        brightness: Brightness.dark,
        seedColor: const Color(0xff75d6b5),
        surface: const Color(0xff112321),
      ),
      useMaterial3: true,
    ),
    home: MobileHome(
      api: api ?? MobileApi(),
      sessionStore: sessionStore ?? const SecureSessionStore(),
      discovery: discovery ?? const NsdHostDiscovery(),
    ),
  );
}

class MobileHome extends StatefulWidget {
  const MobileHome({
    required this.api,
    required this.sessionStore,
    required this.discovery,
    super.key,
  });

  final MobileApi api;
  final SessionStore sessionStore;
  final HostDiscovery discovery;

  @override
  State<MobileHome> createState() => _MobileHomeState();
}

class _MobileHomeState extends State<MobileHome> {
  final _host = TextEditingController();
  final _name = TextEditingController(text: 'Android Player');
  final _runId = TextEditingController();
  String? _token;
  String? _hostId;
  PairingRequest? _pairing;
  RunSnapshot? _run;
  List<DiscoveredHost> _hosts = const [];
  List<MobileRunSummary> _availableRuns = const [];
  String _status = '正在查找同一局域网内已开启玩法的 DZMM Host。';
  bool _busy = false;
  bool _discovering = false;

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final session = await widget.sessionStore.read();
    if (!mounted) {
      return;
    }
    if (session == null) {
      await _discoverHosts();
      return;
    }
    setState(() {
      _host.text = session.host;
      _token = session.token;
      _hostId = session.hostId;
      _runId.text = session.runId ?? '';
      _status = session.runId == null || session.runId!.isEmpty
          ? '已恢复手机凭证，正在查找可继续的游戏。'
          : '已恢复手机凭证，正在恢复上次游戏。';
    });
    if (session.runId != null && session.runId!.isNotEmpty) {
      await _loadRun(silent: true);
      if (_run == null && mounted) {
        await _discoverHosts(restoreHostId: session.hostId);
      }
    } else {
      await _withBusy(() => _restoreLatestRun(silent: true));
    }
  }

  Future<void> _discoverHosts({String? restoreHostId}) async {
    if (_discovering) return;
    setState(() {
      _discovering = true;
      _status = '正在查找局域网中的 DZMM Host…';
    });
    final hosts = <DiscoveredHost>[];
    try {
      await for (final host in widget.discovery.discover()) {
        if (!hosts.any((item) => item.url == host.url)) hosts.add(host);
        if (mounted) setState(() => _hosts = List.unmodifiable(hosts));
      }
      DiscoveredHost? matching;
      if (restoreHostId != null) {
        for (final host in hosts) {
          if (host.hostId == restoreHostId) {
            matching = host;
            break;
          }
        }
      }
      if (matching != null && _token != null) {
        _selectHost(matching, announce: false);
        await _withBusy(() => _restoreLatestRun(silent: true));
      } else if (mounted) {
        setState(() {
          _status = hosts.isEmpty
              ? '未发现 Host。请确认桌面端已开启“局域网玩法”，或手动填写地址。'
              : '已发现 ${hosts.length} 个 DZMM Host。选择一个后申请配对。';
        });
      }
    } finally {
      if (mounted) setState(() => _discovering = false);
    }
  }

  void _selectHost(DiscoveredHost candidate, {bool announce = true}) {
    setState(() {
      _host.text = candidate.url;
      if (announce) _status = '已选择 ${candidate.name}。';
    });
  }

  Future<void> _scanPairingCode() async {
    final candidate = await Navigator.of(context).push<DiscoveredHost>(
      MaterialPageRoute(builder: (_) => const QrPairingPage()),
    );
    if (candidate != null && mounted) _selectHost(candidate);
  }

  String get _base => _host.text.trim().replaceFirst(RegExp(r'/$'), '');

  Future<void> _requestPairing() => _withBusy(() async {
    final name = _name.text.trim();
    if (name.isEmpty) throw const HostApiError(0, '请填写设备名称。');
    final pairing = await widget.api.requestPairing(
      host: _base,
      deviceName: name,
    );
    if (!mounted) return;
    setState(() {
      _pairing = pairing;
      _status = '请求已发送。请在桌面端“管理手机配对”中批准此设备，再回来完成配对。';
    });
  });

  Future<void> _completePairing() => _withBusy(() async {
    final pairing = _pairing;
    if (pairing == null) throw const HostApiError(0, '请先申请配对。');
    final credential = await widget.api.completePairing(
      host: _base,
      request: pairing,
    );
    await widget.sessionStore.save(
      StoredSession(
        host: _base,
        token: credential.accessToken,
        hostId: credential.hostId,
      ),
    );
    if (!mounted) return;
    setState(() {
      _token = credential.accessToken;
      _hostId = credential.hostId;
      _pairing = null;
      _status = '配对完成。正在打开最近的可玩游戏。';
    });
    await _restoreLatestRun(silent: true);
  });

  Future<void> _restoreLatestRun({bool silent = false}) async {
    final token = _token;
    if (token == null) throw const HostApiError(401, '请先完成手机配对。');
    final runs = await widget.api.listRuns(host: _base, token: token);
    if (!mounted) return;
    setState(() => _availableRuns = runs);
    if (runs.isEmpty) {
      setState(() => _status = '桌面 Host 还没有可继续的游戏，请先在桌面端创建世界。');
      return;
    }
    _runId.text = runs.first.runId;
    await _loadRunCurrent(silent: silent);
  }

  Future<void> _selectRun(String runId) => _withBusy(() async {
    _runId.text = runId;
    await _loadRunCurrent(silent: true);
  });

  Future<void> _loadRun({bool silent = false}) =>
      _withBusy(() => _loadRunCurrent(silent: silent));

  Future<void> _loadRunCurrent({bool silent = false}) async {
    final token = _token;
    final runId = _runId.text.trim();
    if (token == null) throw const HostApiError(401, '请先完成手机配对。');
    if (runId.isEmpty) throw const HostApiError(0, '请输入要继续的 Run ID。');
    final run = await widget.api.loadRun(
      host: _base,
      token: token,
      runId: runId,
    );
    await widget.sessionStore.save(
      StoredSession(
        host: _base,
        token: token,
        runId: run.runId,
        hostId: _hostId,
      ),
    );
    if (!mounted) return;
    setState(() {
      _run = run;
      _status = silent ? '已恢复最近的游戏。' : '已从桌面 Host 恢复当前状态。';
    });
  }

  Future<void> _choose(Map<String, dynamic> choice) => _withBusy(() async {
    final token = _token;
    final run = _run;
    if (token == null || run == null) throw const HostApiError(401, '请先恢复游戏。');
    final selected = await widget.api.choose(
      host: _base,
      token: token,
      runId: run.runId,
      expectedRevision: run.state['revision'] as int,
      choiceId: choice['id'] as String,
      playerInput: choice['label'] as String,
      requestId: 'android-${DateTime.now().microsecondsSinceEpoch}',
    );
    await widget.sessionStore.save(
      StoredSession(
        host: _base,
        token: token,
        runId: selected.runId,
        hostId: _hostId,
      ),
    );
    if (!mounted) return;
    setState(() {
      _run = selected;
      _status = '桌面 Host 已结算这个选择并返回新的状态版本。';
    });
  });

  Future<void> _forgetDevice() => _withBusy(() async {
    await widget.sessionStore.clear();
    if (!mounted) return;
    setState(() {
      _token = null;
      _hostId = null;
      _pairing = null;
      _run = null;
      _availableRuns = const [];
      _runId.clear();
      _status = '已清除本机凭证。桌面端的设备权限仍可由 Host 撤销。';
    });
  });

  Future<void> _withBusy(Future<void> Function() operation) async {
    setState(() => _busy = true);
    try {
      await operation();
    } on HostApiError catch (error) {
      if (error.isUnauthorized) {
        await widget.sessionStore.clear();
        if (mounted) {
          setState(() {
            _token = null;
            _run = null;
            _status = '手机凭证已失效或被桌面端撤销，请重新配对。';
          });
        }
      } else if (error.isConflict) {
        if (mounted) {
          setState(() => _status = '状态已在其他设备变化。请点击“恢复当前 Run”获取桌面端的最新版本。');
        }
      } else if (mounted) {
        setState(() => _status = error.detail);
      }
    } catch (_) {
      if (mounted) setState(() => _status = '无法连接桌面 Host，请检查局域网地址和 Host 开关。');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _host.dispose();
    _name.dispose();
    _runId.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('DZMM Next'),
      actions: [
        if (_token != null)
          IconButton(
            tooltip: '清除本机凭证',
            onPressed: _busy ? null : _forgetDevice,
            icon: const Icon(Icons.phonelink_erase_outlined),
          ),
      ],
    ),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
        children: [
          Text(
            '你的故事，只在这台桌面 Host 上继续。',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          const Text('手机只能读取和提交当前 Run 的受限玩法选择；世界、模型和删除操作只在桌面端管理。'),
          const SizedBox(height: 20),
          _ConnectionCard(
            host: _host,
            name: _name,
            busy: _busy || _discovering,
            paired: _token != null,
            pairingPending: _pairing != null,
            hosts: _hosts,
            onDiscover: _discoverHosts,
            onHostSelected: _selectHost,
            onScanCode: _scanPairingCode,
            onRequestPairing: _requestPairing,
            onCompletePairing: _completePairing,
          ),
          const SizedBox(height: 16),
          _StatusCard(message: _status, busy: _busy),
          const SizedBox(height: 20),
          if (_token != null)
            _RunEntryCard(
              runId: _runId,
              runs: _availableRuns,
              busy: _busy,
              onLoad: _loadRun,
              onSelect: _selectRun,
            ),
          if (_run != null) ...[
            const SizedBox(height: 20),
            _GameView(run: _run!, busy: _busy, onChoose: _choose),
          ],
        ],
      ),
    ),
  );
}

class _ConnectionCard extends StatelessWidget {
  const _ConnectionCard({
    required this.host,
    required this.name,
    required this.busy,
    required this.paired,
    required this.pairingPending,
    required this.hosts,
    required this.onDiscover,
    required this.onHostSelected,
    required this.onScanCode,
    required this.onRequestPairing,
    required this.onCompletePairing,
  });
  final TextEditingController host;
  final TextEditingController name;
  final bool busy;
  final bool paired;
  final bool pairingPending;
  final List<DiscoveredHost> hosts;
  final VoidCallback onDiscover;
  final ValueChanged<DiscoveredHost> onHostSelected;
  final VoidCallback onScanCode;
  final VoidCallback onRequestPairing;
  final VoidCallback onCompletePairing;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('连接桌面 Host', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          const Text('会自动发现已开启“局域网玩法”的桌面 Host；发现失败时仍可手动填写。'),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: busy ? null : onDiscover,
            icon: const Icon(Icons.radar_outlined),
            label: const Text('重新查找局域网 Host'),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: busy ? null : onScanCode,
            icon: const Icon(Icons.qr_code_scanner_outlined),
            label: const Text('扫描桌面配对码'),
          ),
          if (hosts.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...hosts.map(
              (candidate) => ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.computer_outlined),
                title: Text(candidate.name),
                subtitle: Text(candidate.url),
                onTap: paired || busy ? null : () => onHostSelected(candidate),
              ),
            ),
          ],
          const SizedBox(height: 14),
          TextField(
            controller: host,
            enabled: !paired && !busy,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '桌面 Host 地址',
              hintText: 'http://192.168.x.x:8765',
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: name,
            enabled: !paired && !busy,
            decoration: const InputDecoration(labelText: '设备名称'),
          ),
          const SizedBox(height: 14),
          if (paired)
            const Chip(label: Text('已配对 · gameplay-only'))
          else if (pairingPending)
            FilledButton.tonal(
              onPressed: busy ? null : onCompletePairing,
              child: const Text('桌面端已批准，完成配对'),
            )
          else
            FilledButton(
              onPressed: busy ? null : onRequestPairing,
              child: const Text('申请手机配对'),
            ),
        ],
      ),
    ),
  );
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.message, required this.busy});
  final String message;
  final bool busy;
  @override
  Widget build(BuildContext context) => Card(
    color: Theme.of(context).colorScheme.surfaceContainerHighest,
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (busy)
            const Padding(
              padding: EdgeInsets.only(right: 12, top: 2),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            )
          else
            const Padding(
              padding: EdgeInsets.only(right: 12, top: 1),
              child: Icon(Icons.info_outline),
            ),
          Expanded(child: Text(message)),
        ],
      ),
    ),
  );
}

class _RunEntryCard extends StatelessWidget {
  const _RunEntryCard({
    required this.runId,
    required this.runs,
    required this.busy,
    required this.onLoad,
    required this.onSelect,
  });
  final TextEditingController runId;
  final List<MobileRunSummary> runs;
  final bool busy;
  final VoidCallback onLoad;
  final ValueChanged<String> onSelect;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('继续一局', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 10),
          if (runs.isNotEmpty) ...[
            ...runs.map(
              (run) => ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.auto_stories_outlined),
                title: Text(run.worldName),
                subtitle: Text('${run.heroName} · 状态版本 ${run.stateRevision}'),
                trailing: const Icon(Icons.chevron_right),
                onTap: busy ? null : () => onSelect(run.runId),
              ),
            ),
            const Divider(),
          ],
          TextField(
            controller: runId,
            enabled: !busy,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Run ID（手动恢复）'),
          ),
          const SizedBox(height: 12),
          FilledButton.tonal(
            onPressed: busy ? null : onLoad,
            child: const Text('恢复当前 Run'),
          ),
        ],
      ),
    ),
  );
}

class _GameView extends StatelessWidget {
  const _GameView({
    required this.run,
    required this.busy,
    required this.onChoose,
  });
  final RunSnapshot run;
  final bool busy;
  final ValueChanged<Map<String, dynamic>> onChoose;
  @override
  Widget build(BuildContext context) {
    final state = run.state;
    final chapter = state['chapter'] as Map?;
    final route = state['route'] as Map?;
    final ending = state['ending'] as Map?;
    final relationships = Map<String, dynamic>.from(
      state['relationships'] as Map,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _StateCard(
          state: state,
          chapter: chapter,
          route: route,
          ending: ending,
          relationships: relationships,
        ),
        const SizedBox(height: 16),
        if (ending != null)
          _EndingCard(ending: Map<String, dynamic>.from(ending)),
        if (ending == null && run.availableChoices.isNotEmpty) ...[
          Text('此刻可做的选择', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          ...run.availableChoices.map(
            (choice) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: FilledButton.tonal(
                onPressed: busy ? null : () => onChoose(choice),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text(choice['label'] as String),
                ),
              ),
            ),
          ),
        ] else if (ending == null)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text('这个 Run 没有可提交的手机选择，请在桌面端继续。'),
            ),
          ),
        const SizedBox(height: 16),
        Text('回合记录', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        ...run.turns.map((turn) => _TurnCard(turn: turn)),
      ],
    );
  }
}

class _StateCard extends StatelessWidget {
  const _StateCard({
    required this.state,
    required this.chapter,
    required this.route,
    required this.ending,
    required this.relationships,
  });
  final Map<String, dynamic> state;
  final Map? chapter;
  final Map? route;
  final Map? ending;
  final Map<String, dynamic> relationships;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('当前状态', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              Chip(label: Text('版本 ${state['revision']}')),
              if (chapter != null) Chip(label: Text('章节 ${chapter!['id']}')),
              if (route != null) Chip(label: Text('路线 ${route!['id']}')),
              if (ending != null) Chip(label: Text('结局 ${ending!['kind']}')),
            ],
          ),
          const SizedBox(height: 12),
          Text('地点：${state['location_id']}'),
          const SizedBox(height: 12),
          Text('关系账本', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          ...relationships.entries.map((entry) {
            final relation = Map<String, dynamic>.from(entry.value as Map);
            final dimensions = Map<String, dynamic>.from(
              relation['dimensions'] as Map,
            );
            final applied = Map<String, dynamic>.from(
              relation['applied_events'] as Map,
            );
            final reasons = applied.values
                .map((event) => (event as Map)['reason_key'].toString())
                .join('、');
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                '${entry.key} · ${dimensions.entries.map((item) => '${item.key} ${item.value}').join(' · ')}${reasons.isEmpty ? '' : '\n变化原因：$reasons'}',
              ),
            );
          }),
        ],
      ),
    ),
  );
}

class _EndingCard extends StatelessWidget {
  const _EndingCard({required this.ending});
  final Map<String, dynamic> ending;
  @override
  Widget build(BuildContext context) => Card(
    color: Theme.of(context).colorScheme.primaryContainer,
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('结局已锁定', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          Text('${ending['kind']} · ${ending['id']}'),
          const SizedBox(height: 6),
          const Text('结局由桌面 Host 的 Python 规则裁定。要改写路径，请在桌面端回滚。'),
        ],
      ),
    ),
  );
}

class _TurnCard extends StatelessWidget {
  const _TurnCard({required this.turn});
  final Map<String, dynamic> turn;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '回合 ${turn['sequence']} · 状态 ${turn['before_revision']} → ${turn['after_revision']}',
            style: Theme.of(context).textTheme.labelMedium,
          ),
          const SizedBox(height: 6),
          Text(
            turn['player_input'].toString(),
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 6),
          Text(turn['narrative'].toString()),
        ],
      ),
    ),
  );
}

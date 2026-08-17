import 'package:flutter/material.dart';

import 'mobile_api.dart';
import 'session_store.dart';

void main() => runApp(const DzmmMobileApp());

class DzmmMobileApp extends StatelessWidget {
  const DzmmMobileApp({super.key, this.api, this.sessionStore});

  final MobileApi? api;
  final SessionStore? sessionStore;

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
    ),
  );
}

class MobileHome extends StatefulWidget {
  const MobileHome({required this.api, required this.sessionStore, super.key});

  final MobileApi api;
  final SessionStore sessionStore;

  @override
  State<MobileHome> createState() => _MobileHomeState();
}

class _MobileHomeState extends State<MobileHome> {
  final _host = TextEditingController();
  final _name = TextEditingController(text: 'Android Player');
  final _runId = TextEditingController();
  String? _token;
  PairingRequest? _pairing;
  RunSnapshot? _run;
  String _status = '输入 Mac 的局域网地址后申请配对。';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final session = await widget.sessionStore.read();
    if (!mounted || session == null) return;
    setState(() {
      _host.text = session.host;
      _token = session.token;
      _runId.text = session.runId ?? '';
      _status = session.runId == null || session.runId!.isEmpty
          ? '已恢复手机凭证。输入 Run ID 继续游戏。'
          : '已恢复手机凭证，正在恢复上次游戏。';
    });
    if (session.runId != null && session.runId!.isNotEmpty) {
      await _loadRun(silent: true);
    }
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
      _status = '请求已发送。请在 Mac 的“管理手机配对”中批准此设备，再回来完成配对。';
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
      StoredSession(host: _base, token: credential.accessToken),
    );
    if (!mounted) return;
    setState(() {
      _token = credential.accessToken;
      _pairing = null;
      _status = '配对完成。此设备只拥有 gameplay 权限。';
    });
  });

  Future<void> _loadRun({bool silent = false}) => _withBusy(() async {
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
      StoredSession(host: _base, token: token, runId: run.runId),
    );
    if (!mounted) return;
    setState(() {
      _run = run;
      if (!silent) _status = '已从 Mac Host 恢复当前状态。';
    });
  });

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
      StoredSession(host: _base, token: token, runId: selected.runId),
    );
    if (!mounted) return;
    setState(() {
      _run = selected;
      _status = 'Mac Host 已结算这个选择并返回新的状态版本。';
    });
  });

  Future<void> _forgetDevice() => _withBusy(() async {
    await widget.sessionStore.clear();
    if (!mounted) return;
    setState(() {
      _token = null;
      _pairing = null;
      _run = null;
      _runId.clear();
      _status = '已清除本机凭证。Mac 上的设备权限仍可由 Host 撤销。';
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
            _status = '手机凭证已失效或被 Mac 撤销，请重新配对。';
          });
        }
      } else if (error.isConflict) {
        if (mounted) {
          setState(() => _status = '状态已在其他设备变化。请点击“恢复当前 Run”获取 Mac 的最新版本。');
        }
      } else if (mounted) {
        setState(() => _status = error.detail);
      }
    } catch (_) {
      if (mounted) setState(() => _status = '无法连接 Mac Host，请检查局域网地址和 Host 开关。');
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
            '你的故事，只在这台 Mac Host 上继续。',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          const Text('手机只能读取和提交当前 Run 的受限玩法选择；世界、模型和删除操作只在 Mac 上管理。'),
          const SizedBox(height: 20),
          _ConnectionCard(
            host: _host,
            name: _name,
            busy: _busy,
            paired: _token != null,
            pairingPending: _pairing != null,
            onRequestPairing: _requestPairing,
            onCompletePairing: _completePairing,
          ),
          const SizedBox(height: 16),
          _StatusCard(message: _status, busy: _busy),
          const SizedBox(height: 20),
          if (_token != null)
            _RunEntryCard(runId: _runId, busy: _busy, onLoad: _loadRun),
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
    required this.onRequestPairing,
    required this.onCompletePairing,
  });
  final TextEditingController host;
  final TextEditingController name;
  final bool busy;
  final bool paired;
  final bool pairingPending;
  final VoidCallback onRequestPairing;
  final VoidCallback onCompletePairing;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('连接 Mac Host', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          const Text('在 Mac 开启“局域网玩法”后，输入例如 http://192.168.x.x:8765 的地址。'),
          const SizedBox(height: 14),
          TextField(
            controller: host,
            enabled: !paired && !busy,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'Mac Host 地址',
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
              child: const Text('Mac 已批准，完成配对'),
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
    required this.busy,
    required this.onLoad,
  });
  final TextEditingController runId;
  final bool busy;
  final VoidCallback onLoad;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('继续一局', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 10),
          TextField(
            controller: runId,
            enabled: !busy,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Run ID'),
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
              child: Text('这个 Run 没有可提交的手机选择，请在 Mac 上继续。'),
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
          const Text('结局由 Mac Host 的 Python 规则裁定。要改写路径，请在 Mac 上回滚。'),
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

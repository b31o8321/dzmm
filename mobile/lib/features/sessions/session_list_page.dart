import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/api_error.dart';
import '../../api/dzmm_api.dart';
import 'session_models.dart';
import 'session_repository.dart';

class SessionListPage extends StatefulWidget {
  const SessionListPage({
    required this.repository,
    required this.onSelected,
    super.key,
  });

  final SessionRepository repository;
  final ValueChanged<GameSessionSummary> onSelected;

  @override
  State<SessionListPage> createState() => _SessionListPageState();
}

class _SessionListPageState extends State<SessionListPage> {
  final _cancellation = CancellationToken();
  List<GameSessionSummary>? _sessions;
  Object? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _sessions = null;
      _error = null;
    });
    try {
      final sessions = await widget.repository.list(
        cancellationToken: _cancellation,
      );
      if (mounted) setState(() => _sessions = sessions);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  @override
  void dispose() {
    _cancellation.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return _SessionLoadError(error: _error!, onRetry: _load);
    }
    final sessions = _sessions;
    if (sessions == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (sessions.isEmpty) {
      return _SessionEmpty(onRetry: _load);
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 120),
        itemCount: sessions.length,
        separatorBuilder: (_, _) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final session = sessions[index];
          return Card(
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 18,
                vertical: 8,
              ),
              leading: const Icon(Icons.auto_stories_outlined),
              title: Text(session.name),
              subtitle: Text('第 ${session.turnCount} 回合'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => widget.onSelected(session),
            ),
          );
        },
      ),
    );
  }
}

class _SessionEmpty extends StatelessWidget {
  const _SessionEmpty({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Mac 上还没有跑团存档。请先在桌面端创建。'),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('刷新'),
            ),
          ],
        ),
      ),
    );
  }
}

class _SessionLoadError extends StatelessWidget {
  const _SessionLoadError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final message = switch (error) {
      ApiError(code: 'unauthorized') ||
      ApiError(code: 'token_revoked') => '此设备授权已失效，请重新配对。',
      ApiError(code: 'server_incompatible') => 'Mac 版本与当前 Android 客户端不兼容。',
      ApiError(code: 'offline') ||
      ApiError(code: 'timeout') => 'Mac 当前不可达，请检查 Wi-Fi 和远程访问开关。',
      _ => '无法读取存档，请稍后重试。',
    };
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}

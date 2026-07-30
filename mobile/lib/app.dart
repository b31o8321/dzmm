import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/dzmm_api.dart';
import 'api/sse_client.dart';
import 'connection/connection_controller.dart';
import 'connection/lan_scanner.dart';
import 'connection/paired_server.dart';
import 'connection/reconnect_service.dart';
import 'features/game/game_page.dart';
import 'features/game/turn_run_client.dart';
import 'features/pairing/connection_onboarding_page.dart';
import 'features/pairing/pairing_controller.dart';
import 'features/pairing/pairing_method_page.dart';
import 'features/pairing/qr_scan_page.dart';
import 'features/sessions/session_list_page.dart';
import 'features/sessions/session_models.dart';
import 'features/sessions/session_repository.dart';

const _ink = Color(0xFF172033);
const _fog = Color(0xFFF0F3F7);
const _signal = Color(0xFF6856C8);
const _online = Color(0xFF167C72);

class DzmmApp extends StatelessWidget {
  const DzmmApp({super.key});

  @override
  Widget build(BuildContext context) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: _signal,
      brightness: Brightness.light,
      surface: _fog,
    ).copyWith(primary: _signal, secondary: _online, onSurface: _ink);
    return MaterialApp(
      title: 'dzmm',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: colorScheme,
        scaffoldBackgroundColor: _fog,
        useMaterial3: true,
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.transparent,
          foregroundColor: _ink,
          elevation: 0,
        ),
        cardTheme: const CardThemeData(elevation: 0, margin: EdgeInsets.zero),
      ),
      home: const AppShell(),
    );
  }
}

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  var _selectedIndex = 0;
  ReconnectService? _reconnectService;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final service = ReconnectService(
        store: ref.read(connectionStoreProvider),
        connect: connectionControllerConnector(
          ref.read(connectionControllerProvider.notifier),
        ),
      );
      _reconnectService = service;
      service.start();
      unawaited(service.reconnectNow());
    });
  }

  @override
  void dispose() {
    final service = _reconnectService;
    _reconnectService = null;
    if (service != null) unawaited(service.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('dzmm')),
      body: IndexedStack(
        index: _selectedIndex,
        children: [
          ConnectionHome(onConnected: () => setState(() => _selectedIndex = 1)),
          const GameLanding(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) =>
            setState(() => _selectedIndex = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.cast_outlined),
            selectedIcon: Icon(Icons.cast_connected),
            label: '连接',
          ),
          NavigationDestination(
            icon: Icon(Icons.auto_stories_outlined),
            selectedIcon: Icon(Icons.auto_stories),
            label: '跑团',
          ),
        ],
      ),
    );
  }
}

class ConnectionHome extends ConsumerStatefulWidget {
  const ConnectionHome({this.onConnected, super.key});

  final VoidCallback? onConnected;

  @override
  ConsumerState<ConnectionHome> createState() => _ConnectionHomeState();
}

class _ConnectionHomeState extends ConsumerState<ConnectionHome> {
  List<PairedServer> _pairedServers = const [];
  final _scanner = LanScanner();

  @override
  void initState() {
    super.initState();
    _loadPairedServers();
  }

  Future<void> _loadPairedServers() async {
    final servers = await ref.read(connectionStoreProvider).loadServers();
    if (mounted) setState(() => _pairedServers = servers);
  }

  Future<void> _select(DiscoveredServer discovered) async {
    final known = _pairedServers
        .where((server) => server.serverId == discovered.serverId)
        .firstOrNull;
    if (known == null || known.credentialState == CredentialState.revoked) {
      final paired = await Navigator.of(context).push<bool>(
        MaterialPageRoute(
          builder: (_) => PairingMethodPage(discovered: discovered),
        ),
      );
      if (paired != true || !mounted) return;
    }
    await _loadPairedServers();
    await _connect(discovered);
  }

  Future<void> _connect(DiscoveredServer discovered) async {
    final pairing = await ref
        .read(connectionStoreProvider)
        .loadPairing(discovered.serverId);
    if (pairing == null || !mounted) return;
    await ref
        .read(connectionControllerProvider.notifier)
        .connect(
          server: pairing.server,
          host: discovered.endpoint.uri,
          deviceToken: pairing.deviceToken,
        );
    if (!mounted) return;
    final connected =
        ref.read(connectionControllerProvider).status ==
        ConnectionStatus.connected;
    if (connected) {
      widget.onConnected?.call();
    } else {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('已配对，但当前无法建立游戏连接。')));
    }
  }

  Future<void> _pairQr(DzmmQrPayload payload) async {
    DiscoveredServer? discovered;
    for (final endpoint in payload.hosts) {
      final candidate = await _scanner.probeManual(endpoint.uri.toString());
      if (candidate?.serverId == payload.serverId) {
        discovered = candidate;
        break;
      }
    }
    if (!mounted) return;
    if (discovered == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('二维码中的 Mac 当前不可达。')));
      return;
    }
    await ref
        .read(pairingControllerProvider.notifier)
        .pairWithQr(discovered, payload.claim);
    if (!mounted) return;
    final paired =
        ref.read(pairingControllerProvider).status == PairingStatus.paired;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(paired ? '配对成功' : '配对码已过期、已使用或 Mac 不可达')),
    );
    if (paired) await _loadPairedServers();
    if (paired) await _connect(discovered);
  }

  @override
  Widget build(BuildContext context) {
    return ConnectionOnboardingPage(
      scanner: _scanner,
      pairedServers: _pairedServers,
      onSelected: _select,
      onQrPayload: _pairQr,
    );
  }
}

class GameLanding extends ConsumerStatefulWidget {
  const GameLanding({super.key});

  @override
  ConsumerState<GameLanding> createState() => _GameLandingState();
}

class _GameLandingState extends ConsumerState<GameLanding> {
  String? _connectionKey;
  Future<_GameServices?>? _services;

  Future<_GameServices?> _loadServices(DzmmConnectionState connection) async {
    final server = connection.server;
    final host = connection.host;
    if (server == null || host == null) return null;
    final pairing = await ref
        .read(connectionStoreProvider)
        .loadPairing(server.serverId);
    if (pairing == null) return null;
    final api = DzmmApi(baseUri: host, deviceToken: pairing.deviceToken);
    final repository = SessionRepository(DzmmSessionTransport(api));
    final turnClient = TurnRunClient(
      transport: DzmmTurnRunTransport(
        api: api,
        sse: HttpSseClient(baseUri: host, deviceToken: pairing.deviceToken),
      ),
    );
    return _GameServices(
      api: api,
      repository: repository,
      turnClient: turnClient,
    );
  }

  void _resetServices() {
    final previous = _services;
    _services = null;
    if (previous != null) {
      unawaited(previous.then((services) => services?.api.close()));
    }
  }

  @override
  void dispose() {
    _resetServices();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final connection = ref.watch(connectionControllerProvider);
    if (connection.status != ConnectionStatus.connected) {
      if (_connectionKey != null) {
        _connectionKey = null;
        _resetServices();
      }
      return _LandingPanel(
        icon: connection.status == ConnectionStatus.revoked
            ? Icons.link_off
            : Icons.hourglass_empty,
        title: connection.status == ConnectionStatus.revoked
            ? '需要重新配对'
            : '等待连接',
        detail: '在“连接”页选择已配对的 Mac 后，可继续已有跑团。',
      );
    }
    final key = '${connection.server?.serverId}|${connection.host}';
    if (_connectionKey != key) {
      _resetServices();
      _connectionKey = key;
      _services = _loadServices(connection);
    }
    return FutureBuilder<_GameServices?>(
      future: _services,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        final services = snapshot.data;
        if (services == null) {
          return const _LandingPanel(
            icon: Icons.link_off,
            title: '授权不可用',
            detail: '返回连接页重新配对这台 Mac。',
          );
        }
        return SessionListPage(
          repository: services.repository,
          onSelected: (session) => _openGame(context, services, session),
        );
      },
    );
  }

  Future<void> _openGame(
    BuildContext context,
    _GameServices services,
    GameSessionSummary session,
  ) => Navigator.of(context).push<void>(
    MaterialPageRoute(
      builder: (_) => GamePage(
        session: session,
        repository: services.repository,
        turnClient: services.turnClient,
      ),
    ),
  );
}

class _GameServices {
  const _GameServices({
    required this.api,
    required this.repository,
    required this.turnClient,
  });

  final DzmmApi api;
  final SessionRepository repository;
  final TurnRunClient turnClient;
}

class _LandingPanel extends StatelessWidget {
  const _LandingPanel({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Semantics(
          liveRegion: true,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 42,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: 20),
              Text(title, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(
                detail,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'connection/connection_controller.dart';
import 'connection/lan_scanner.dart';
import 'connection/paired_server.dart';
import 'features/pairing/connection_onboarding_page.dart';
import 'features/pairing/pairing_controller.dart';
import 'features/pairing/pairing_method_page.dart';
import 'features/pairing/qr_scan_page.dart';

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

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  var _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('dzmm')),
      body: IndexedStack(
        index: _selectedIndex,
        children: const [ConnectionHome(), GameLanding()],
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
  const ConnectionHome({super.key});

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
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => PairingMethodPage(discovered: discovered),
      ),
    );
    await _loadPairedServers();
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

class GameLanding extends StatelessWidget {
  const GameLanding({super.key});

  @override
  Widget build(BuildContext context) {
    return const _LandingPanel(
      icon: Icons.hourglass_empty,
      title: '等待连接',
      detail: '连接并配对后，可在这里继续已有跑团。',
    );
  }
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

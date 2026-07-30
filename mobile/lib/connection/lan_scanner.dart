import 'dart:async';
import 'dart:io';

import 'package:nsd/nsd.dart' as nsd;
import 'package:permission_handler/permission_handler.dart';

import '../api/dzmm_api.dart';
import 'paired_server.dart';

enum DiscoverySource { recent, mdns, subnet, manual }

class HostEndpoint {
  const HostEndpoint({
    required this.host,
    required this.port,
    required this.source,
    this.name,
    this.expectedServerId,
  });

  final String host;
  final int port;
  final DiscoverySource source;
  final String? name;
  final String? expectedServerId;

  Uri get uri => Uri(scheme: 'http', host: host, port: port);
}

class DiscoveredServer {
  const DiscoveredServer({
    required this.health,
    required this.endpoint,
    required this.name,
  });

  final HealthInfo health;
  final HostEndpoint endpoint;
  final String name;

  String get serverId => health.serverId;
}

class NearbyPermissionException implements Exception {
  const NearbyPermissionException({required this.permanentlyDenied});

  final bool permanentlyDenied;
}

abstract interface class HostProbe {
  Future<HealthInfo?> probe(HostEndpoint endpoint);
}

class HttpHealthProbe implements HostProbe {
  const HttpHealthProbe({this.timeout = const Duration(seconds: 1)});

  final Duration timeout;

  @override
  Future<HealthInfo?> probe(HostEndpoint endpoint) async {
    final api = DzmmApi(baseUri: endpoint.uri, timeout: timeout);
    try {
      return await api.health();
    } on Object {
      return null;
    } finally {
      api.close();
    }
  }
}

abstract interface class MdnsSource {
  Stream<HostEndpoint> discover(Duration duration);
}

class NsdMdnsSource implements MdnsSource {
  const NsdMdnsSource();

  @override
  Stream<HostEndpoint> discover(Duration duration) async* {
    nsd.Discovery? discovery;
    final controller = StreamController<HostEndpoint>();
    try {
      discovery = await nsd.startDiscovery(
        '_dzmm._tcp',
        ipLookupType: nsd.IpLookupType.v4,
      );
      discovery.addServiceListener((service, status) {
        if (status != nsd.ServiceStatus.found || service.port == null) return;
        final addresses = service.addresses ?? const <InternetAddress>[];
        for (final address in addresses) {
          if (address.type == InternetAddressType.IPv4 &&
              isPrivateIpv4(address.address)) {
            controller.add(
              HostEndpoint(
                host: address.address,
                port: service.port!,
                source: DiscoverySource.mdns,
                name: service.name,
              ),
            );
            break;
          }
        }
      });
      unawaited(Future<void>.delayed(duration).then((_) => controller.close()));
      await for (final endpoint in controller.stream) {
        yield endpoint;
      }
    } on Object {
      return;
    } finally {
      if (discovery != null) {
        try {
          await nsd.stopDiscovery(discovery);
        } on Object {
          // Discovery is best effort; subnet and manual entry remain available.
        }
      }
      await controller.close();
    }
  }
}

abstract interface class NetworkInfo {
  Future<String?> privateIpv4();
}

class DeviceNetworkInfo implements NetworkInfo {
  const DeviceNetworkInfo();

  @override
  Future<String?> privateIpv4() async {
    final interfaces = await NetworkInterface.list(
      type: InternetAddressType.IPv4,
      includeLoopback: false,
    );
    for (final interface in interfaces) {
      for (final address in interface.addresses) {
        if (isPrivateIpv4(address.address)) return address.address;
      }
    }
    return null;
  }
}

abstract interface class NearbyPermissionGate {
  Future<void> ensureGranted();
}

class AndroidNearbyPermissionGate implements NearbyPermissionGate {
  const AndroidNearbyPermissionGate();

  @override
  Future<void> ensureGranted() async {
    if (!Platform.isAndroid) return;
    final status = await Permission.nearbyWifiDevices.request();
    if (status.isGranted || status.isLimited) return;
    throw NearbyPermissionException(
      permanentlyDenied: status.isPermanentlyDenied,
    );
  }
}

class LanScanner {
  LanScanner({
    HostProbe? probe,
    MdnsSource? mdns,
    NetworkInfo? networkInfo,
    NearbyPermissionGate? permissionGate,
    this.maxConcurrent = 32,
    this.scanDuration = const Duration(seconds: 8),
  }) : _probe = probe ?? const HttpHealthProbe(),
       _mdns = mdns ?? const NsdMdnsSource(),
       _networkInfo = networkInfo ?? const DeviceNetworkInfo(),
       _permissionGate = permissionGate ?? const AndroidNearbyPermissionGate();

  final HostProbe _probe;
  final MdnsSource _mdns;
  final NetworkInfo _networkInfo;
  final NearbyPermissionGate _permissionGate;
  final int maxConcurrent;
  final Duration scanDuration;

  Stream<DiscoveredServer> scan({
    List<PairedServer> recentServers = const [],
    Set<int> ports = const {8765},
    bool requestPermission = true,
    bool includeSubnet = true,
  }) {
    final output = StreamController<DiscoveredServer>();
    final foundByServerId = <String, DiscoveredServer>{};

    Future<void> consider(HostEndpoint endpoint) async {
      final health = await _probe.probe(endpoint);
      if (health == null ||
          (endpoint.expectedServerId != null &&
              endpoint.expectedServerId != health.serverId)) {
        return;
      }
      final result = DiscoveredServer(
        health: health,
        endpoint: endpoint,
        name: endpoint.name ?? 'dzmm on ${endpoint.host}',
      );
      final previous = foundByServerId[health.serverId];
      if (previous?.endpoint.uri == endpoint.uri) return;
      foundByServerId[health.serverId] = result;
      if (!output.isClosed) output.add(result);
    }

    Future<void> probeRecent() async {
      await Future.wait(
        recentServers.map((server) async {
          for (final host in server.recentHosts) {
            final endpoint = HostEndpoint(
              host: host,
              port: server.port,
              source: DiscoverySource.recent,
              name: server.name,
              expectedServerId: server.serverId,
            );
            await consider(endpoint);
            if (foundByServerId.containsKey(server.serverId)) break;
          }
        }),
      );
    }

    Future<void> probeMdns() async {
      await for (final endpoint in _mdns.discover(scanDuration)) {
        await consider(endpoint);
      }
    }

    Future<void> probeSubnet() async {
      if (!includeSubnet || ports.isEmpty) return;
      final localIp = await _networkInfo.privateIpv4();
      if (localIp == null) return;
      final prefix = localIp.substring(0, localIp.lastIndexOf('.'));
      final targets = <HostEndpoint>[
        for (var suffix = 1; suffix <= 254; suffix++)
          for (final port in ports)
            if ('$prefix.$suffix' != localIp)
              HostEndpoint(
                host: '$prefix.$suffix',
                port: port,
                source: DiscoverySource.subnet,
              ),
      ];
      for (var offset = 0; offset < targets.length; offset += maxConcurrent) {
        final end = (offset + maxConcurrent).clamp(0, targets.length);
        await Future.wait(targets.sublist(offset, end).map(consider));
      }
    }

    Future<void> run() async {
      try {
        if (requestPermission) await _permissionGate.ensureGranted();
        await probeRecent();
        await Future.wait([probeMdns(), probeSubnet()]);
      } on Object catch (error, stackTrace) {
        if (!output.isClosed) output.addError(error, stackTrace);
      } finally {
        await output.close();
      }
    }

    unawaited(run());
    return output.stream;
  }

  Future<DiscoveredServer?> probeManual(
    String input, {
    int defaultPort = 8765,
  }) async {
    final endpoint = await parseManualEndpoint(input, defaultPort: defaultPort);
    final health = await _probe.probe(endpoint);
    if (health == null) return null;
    return DiscoveredServer(
      health: health,
      endpoint: endpoint,
      name: 'dzmm on ${endpoint.host}',
    );
  }
}

Future<HostEndpoint> parseManualEndpoint(
  String input, {
  int defaultPort = 8765,
}) async {
  final trimmed = input.trim();
  final uri = Uri.tryParse(
    trimmed.contains('://') ? trimmed : 'http://$trimmed',
  );
  if (uri == null ||
      uri.scheme != 'http' ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path.isNotEmpty && uri.path != '/')) {
    throw const FormatException(
      'Enter a private LAN IP address or .local host',
    );
  }
  final port = uri.hasPort ? uri.port : defaultPort;
  if (port < 1 || port > 65535 || !await isPrivateLanHost(uri.host)) {
    throw const FormatException('Only private LAN hosts are allowed');
  }
  return HostEndpoint(
    host: uri.host,
    port: port,
    source: DiscoverySource.manual,
  );
}

Future<bool> isPrivateLanHost(String host) async {
  if (isPrivateIpv4(host) || host.toLowerCase().endsWith('.local')) return true;
  try {
    final addresses = await InternetAddress.lookup(host);
    return addresses.isNotEmpty &&
        addresses.every(
          (address) =>
              address.type == InternetAddressType.IPv4 &&
              isPrivateIpv4(address.address),
        );
  } on SocketException {
    return false;
  }
}

bool isPrivateIpv4(String value) {
  final parts = value.split('.');
  if (parts.length != 4) return false;
  final numbers = parts.map(int.tryParse).toList();
  if (numbers.any((part) => part == null || part < 0 || part > 255)) {
    return false;
  }
  final first = numbers[0]!;
  final second = numbers[1]!;
  return first == 10 ||
      (first == 172 && second >= 16 && second <= 31) ||
      (first == 192 && second == 168);
}

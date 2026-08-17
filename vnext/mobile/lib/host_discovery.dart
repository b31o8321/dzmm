import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:nsd/nsd.dart' as nsd;
import 'package:permission_handler/permission_handler.dart';

class DiscoveredHost {
  const DiscoveredHost({
    required this.host,
    required this.port,
    required this.name,
    this.hostId,
  });

  final String host;
  final int port;
  final String name;
  final String? hostId;

  String get url => Uri(scheme: 'http', host: host, port: port).toString();
}

abstract class HostDiscovery {
  Stream<DiscoveredHost> discover({
    Duration duration = const Duration(seconds: 4),
  });
}

class NsdHostDiscovery implements HostDiscovery {
  const NsdHostDiscovery();

  @override
  Stream<DiscoveredHost> discover({
    Duration duration = const Duration(seconds: 4),
  }) async* {
    if (Platform.isAndroid) {
      final permission = await Permission.nearbyWifiDevices.request();
      if (!permission.isGranted && !permission.isLimited) return;
    }
    nsd.Discovery? discovery;
    final output = StreamController<DiscoveredHost>();
    final endpoints = <String>{};
    try {
      discovery = await nsd.startDiscovery(
        '_dzmm._tcp',
        ipLookupType: nsd.IpLookupType.v4,
      );
      discovery.addServiceListener((service, status) {
        if (status != nsd.ServiceStatus.found || service.port == null) return;
        final addresses = service.addresses ?? const <InternetAddress>[];
        final address = addresses
            .where(
              (item) =>
                  item.type == InternetAddressType.IPv4 && _isPrivateIpv4(item),
            )
            .map((item) => item.address)
            .firstOrNull;
        if (address == null) return;
        final endpoint = '$address:${service.port}';
        if (!endpoints.add(endpoint)) return;
        output.add(
          DiscoveredHost(
            host: address,
            port: service.port!,
            name: service.name ?? 'DZMM Host',
            hostId: _txtValue(service.txt, 'host_id'),
          ),
        );
      });
      unawaited(Future<void>.delayed(duration).then((_) => output.close()));
      await for (final host in output.stream) {
        yield host;
      }
    } catch (_) {
      // Discovery is best-effort. Manual address entry remains available.
    } finally {
      if (discovery != null) {
        try {
          await nsd.stopDiscovery(discovery);
        } catch (_) {
          // Android NSD may already have torn down the discovery on pause.
        }
      }
      await output.close();
    }
  }
}

bool _isPrivateIpv4(InternetAddress address) {
  if (address.isLoopback || address.isLinkLocal) return false;
  final bytes = address.rawAddress;
  if (bytes.length != 4) return false;
  final first = bytes[0];
  final second = bytes[1];
  return first == 10 ||
      (first == 172 && second >= 16 && second <= 31) ||
      (first == 192 && second == 168);
}

String? _txtValue(Map<String, Uint8List?>? values, String key) {
  final value = values?[key];
  if (value == null) return null;
  try {
    return utf8.decode(value, allowMalformed: false);
  } on FormatException {
    return null;
  }
}

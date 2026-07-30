enum CredentialState { active, revoked }

class PairedServer {
  const PairedServer({
    required this.serverId,
    required this.name,
    required this.port,
    required this.recentHosts,
    this.apiVersion = 1,
    this.credentialState = CredentialState.active,
    this.lastSeen,
  });

  final String serverId;
  final String name;
  final int port;
  final List<String> recentHosts;
  final int apiVersion;
  final CredentialState credentialState;
  final DateTime? lastSeen;

  PairedServer copyWith({
    String? name,
    int? port,
    List<String>? recentHosts,
    int? apiVersion,
    CredentialState? credentialState,
    DateTime? lastSeen,
  }) {
    return PairedServer(
      serverId: serverId,
      name: name ?? this.name,
      port: port ?? this.port,
      recentHosts: recentHosts ?? this.recentHosts,
      apiVersion: apiVersion ?? this.apiVersion,
      credentialState: credentialState ?? this.credentialState,
      lastSeen: lastSeen ?? this.lastSeen,
    );
  }

  Map<String, Object?> toJson() => {
    'server_id': serverId,
    'name': name,
    'port': port,
    'recent_hosts': recentHosts,
    'api_version': apiVersion,
    'credential_state': credentialState.name,
    'last_seen': lastSeen?.toUtc().toIso8601String(),
  };

  factory PairedServer.fromJson(Map<String, Object?> json) {
    final serverId = json['server_id'];
    final name = json['name'];
    final port = json['port'];
    final recentHosts = json['recent_hosts'];
    final apiVersion = json['api_version'];
    if (serverId is! String ||
        serverId.isEmpty ||
        name is! String ||
        name.isEmpty) {
      throw const FormatException('Invalid paired server identity');
    }
    if (port is! int || port < 1 || port > 65535) {
      throw const FormatException('Invalid paired server port');
    }
    if (recentHosts is! List || !recentHosts.every((host) => host is String)) {
      throw const FormatException('Invalid recent hosts');
    }
    final credentialStateValue = json['credential_state'];
    final parsedCredentialState = switch (credentialStateValue) {
      null => CredentialState.active,
      final String value =>
        CredentialState.values
            .where((state) => state.name == value)
            .firstOrNull,
      _ => null,
    };
    if (parsedCredentialState == null) {
      throw const FormatException('Invalid credential state');
    }
    return PairedServer(
      serverId: serverId,
      name: name,
      port: port,
      recentHosts: recentHosts.cast<String>(),
      apiVersion: apiVersion is int ? apiVersion : 1,
      credentialState: parsedCredentialState,
      lastSeen: switch (json['last_seen']) {
        final String value => DateTime.tryParse(value),
        _ => null,
      },
    );
  }

  @override
  String toString() =>
      'PairedServer(serverId: $serverId, name: $name, port: $port, '
      'credentialState: ${credentialState.name})';
}

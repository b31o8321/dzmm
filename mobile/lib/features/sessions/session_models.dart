class GameSessionSummary {
  const GameSessionSummary({
    required this.id,
    required this.name,
    required this.turnCount,
  });

  final int id;
  final String name;
  final int turnCount;

  factory GameSessionSummary.fromJson(Map<String, Object?> json) {
    return GameSessionSummary(
      id: _requiredInt(json, 'id'),
      name: _requiredString(json, 'name'),
      turnCount: _optionalInt(json['turn_count']),
    );
  }
}

class GameMessage {
  const GameMessage({
    required this.id,
    required this.role,
    required this.content,
    required this.turn,
    this.events = const [],
    this.diagnostics = const [],
  });

  final int id;
  final String role;
  final String content;
  final int turn;
  final List<Map<String, Object?>> events;
  final List<Object?> diagnostics;

  factory GameMessage.fromJson(Map<String, Object?> json) {
    final role = json['role'];
    if (role is! String || !{'user', 'assistant', 'system'}.contains(role)) {
      throw const FormatException('Invalid message role');
    }
    return GameMessage(
      id: _requiredInt(json, 'id'),
      role: role,
      content: _requiredString(json, 'content'),
      turn: _optionalInt(json['turn']),
      events: _objectList(json['events']),
      diagnostics: json['diagnostics'] is List
          ? List<Object?>.unmodifiable(json['diagnostics'] as List)
          : const [],
    );
  }
}

class SessionGameState {
  const SessionGameState({
    this.stats = const {},
    this.inventory = const [],
    this.vitals = const {},
    this.npcs = const [],
    this.threads = const [],
    this.worldTime = const {},
    this.equipment = const {},
    this.goals = const [],
    this.locations = const [],
  });

  final Map<String, Object?> stats;
  final List<Object?> inventory;
  final Map<String, Object?> vitals;
  final List<Map<String, Object?>> npcs;
  final List<Map<String, Object?>> threads;
  final Map<String, Object?> worldTime;
  final Map<String, Object?> equipment;
  final List<Map<String, Object?>> goals;
  final List<Map<String, Object?>> locations;

  factory SessionGameState.fromJson(Map<String, Object?> json) {
    return SessionGameState(
      stats: _objectMap(json['stats']),
      inventory: _valueList(json['inventory_v2'] ?? json['inventory']),
      vitals: _objectMap(json['vitals']),
      npcs: _objectList(json['npcs']),
      threads: _objectList(json['threads']),
      worldTime: _objectMap(json['world_time']),
      equipment: _objectMap(json['equipment']),
      goals: _objectList(json['goals']),
      locations: _objectList(json['locations']),
    );
  }
}

class SessionHydration {
  const SessionHydration({
    required this.session,
    required this.messages,
    required this.state,
  });

  final GameSessionSummary session;
  final List<GameMessage> messages;
  final SessionGameState state;
}

int _requiredInt(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is! int) throw FormatException('Missing integer $key');
  return value;
}

String _requiredString(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is! String) throw FormatException('Missing string $key');
  return value;
}

int _optionalInt(Object? value) => value is int ? value : 0;

Map<String, Object?> _objectMap(Object? value) => value is Map
    ? Map<String, Object?>.unmodifiable(value.cast<String, Object?>())
    : const {};

List<Object?> _valueList(Object? value) =>
    value is List ? List<Object?>.unmodifiable(value) : const [];

List<Map<String, Object?>> _objectList(Object? value) {
  if (value is! List) return const [];
  return List<Map<String, Object?>>.unmodifiable(
    value.whereType<Map>().map(
      (item) => Map<String, Object?>.unmodifiable(item.cast<String, Object?>()),
    ),
  );
}

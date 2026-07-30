import '../../api/dzmm_api.dart';
import 'session_models.dart';

abstract interface class SessionTransport {
  Future<Object?> get(String path, {CancellationToken? cancellationToken});
}

class DzmmSessionTransport implements SessionTransport {
  const DzmmSessionTransport(this.api);

  final DzmmApi api;

  @override
  Future<Object?> get(String path, {CancellationToken? cancellationToken}) =>
      api.getJson(path, cancellationToken: cancellationToken);
}

class SessionRepository {
  const SessionRepository(this._transport);

  final SessionTransport _transport;

  Future<List<GameSessionSummary>> list({
    CancellationToken? cancellationToken,
  }) async {
    final value = await _transport.get(
      '/sessions',
      cancellationToken: cancellationToken,
    );
    if (value is! List) throw const FormatException('Expected session list');
    return value
        .map(
          (item) => GameSessionSummary.fromJson(
            (item as Map).cast<String, Object?>(),
          ),
        )
        .toList(growable: false);
  }

  Future<SessionHydration> hydrate(
    int sessionId, {
    CancellationToken? cancellationToken,
  }) async {
    final values = await Future.wait([
      _transport.get(
        '/sessions/$sessionId',
        cancellationToken: cancellationToken,
      ),
      _transport.get(
        '/sessions/$sessionId/messages',
        cancellationToken: cancellationToken,
      ),
      _transport.get(
        '/sessions/$sessionId/state',
        cancellationToken: cancellationToken,
      ),
      _transport.get(
        '/sessions/$sessionId/goals',
        cancellationToken: cancellationToken,
      ),
      _transport.get(
        '/sessions/$sessionId/locations',
        cancellationToken: cancellationToken,
      ),
    ]);
    final sessionJson = _asObject(values[0], 'session');
    final messagesJson = values[1];
    final stateJson = _asObject(values[2], 'state');
    if (messagesJson is! List) {
      throw const FormatException('Expected message list');
    }
    return SessionHydration(
      session: GameSessionSummary.fromJson(sessionJson),
      messages: messagesJson
          .map(
            (item) =>
                GameMessage.fromJson((item as Map).cast<String, Object?>()),
          )
          .toList(growable: false),
      state: SessionGameState.fromJson({
        ...stateJson,
        'goals': values[3] is List ? values[3] : const <Object?>[],
        'locations': values[4] is List ? values[4] : const <Object?>[],
      }),
    );
  }

  static Map<String, Object?> _asObject(Object? value, String name) {
    if (value is! Map) throw FormatException('Expected $name object');
    return value.cast<String, Object?>();
  }
}

import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/features/sessions/session_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('lists saves and hydrates optional state defensively', () async {
    final repository = SessionRepository(
      FakeSessionTransport({
        '/sessions': [
          {'id': 7, 'name': '雾港', 'turn_count': 12},
        ],
        '/sessions/7': {'id': 7, 'name': '雾港', 'turn_count': 12},
        '/sessions/7/messages': [
          {'id': 1, 'role': 'user', 'content': '开门', 'turn': 1},
          {
            'id': 2,
            'role': 'assistant',
            'content': '门后有风。',
            'turn': 1,
            'events': [
              {'type': 'choice', 'payload': <String, Object?>{}},
            ],
          },
        ],
        '/sessions/7/state': {
          'stats': {'hp': 8},
          'inventory': ['钥匙'],
          'npcs': 'legacy malformed value',
        },
        '/sessions/7/goals': [
          {'description': '找到出口', 'status': 'active'},
        ],
        '/sessions/7/locations': [
          {'name': '雾港', 'is_current': true},
        ],
      }),
    );

    final sessions = await repository.list();
    final hydrated = await repository.hydrate(7);

    expect(sessions.single.name, '雾港');
    expect(hydrated.messages, hasLength(2));
    expect(hydrated.messages.last.events.single['type'], 'choice');
    expect(hydrated.state.stats['hp'], 8);
    expect(hydrated.state.inventory, ['钥匙']);
    expect(hydrated.state.npcs, isEmpty);
    expect(hydrated.state.goals.single['description'], '找到出口');
    expect(hydrated.state.locations.single['is_current'], isTrue);
  });

  test('rejects a response that is only HTTP-success-shaped', () async {
    final repository = SessionRepository(
      FakeSessionTransport({'/sessions': {}}),
    );

    await expectLater(repository.list(), throwsFormatException);
  });
}

class FakeSessionTransport implements SessionTransport {
  FakeSessionTransport(this.responses);

  final Map<String, Object?> responses;

  @override
  Future<Object?> get(
    String path, {
    CancellationToken? cancellationToken,
  }) async => responses[path];
}

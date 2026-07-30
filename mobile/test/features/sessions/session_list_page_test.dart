import 'package:dzmm_mobile/api/api_error.dart';
import 'package:dzmm_mobile/api/dzmm_api.dart';
import 'package:dzmm_mobile/features/sessions/session_list_page.dart';
import 'package:dzmm_mobile/features/sessions/session_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('shows saves and selects one without authoring controls', (
    tester,
  ) async {
    int? selected;
    await tester.pumpWidget(
      MaterialApp(
        home: SessionListPage(
          repository: SessionRepository(
            FakeTransport([
              {'id': 3, 'name': '余烬之城', 'turn_count': 9},
            ]),
          ),
          onSelected: (session) => selected = session.id,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('余烬之城'), findsOneWidget);
    expect(find.text('第 9 回合'), findsOneWidget);
    expect(find.textContaining('创建'), findsNothing);
    await tester.tap(find.text('余烬之城'));
    expect(selected, 3);
  });

  testWidgets('shows revoked recovery and retries', (tester) async {
    final transport = RetryTransport();
    await tester.pumpWidget(
      MaterialApp(
        home: SessionListPage(
          repository: SessionRepository(transport),
          onSelected: (_) {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('重新配对'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.textContaining('还没有跑团存档'), findsOneWidget);
  });
}

class FakeTransport implements SessionTransport {
  FakeTransport(this.response);

  final Object? response;

  @override
  Future<Object?> get(
    String path, {
    CancellationToken? cancellationToken,
  }) async => response;
}

class RetryTransport implements SessionTransport {
  var calls = 0;

  @override
  Future<Object?> get(
    String path, {
    CancellationToken? cancellationToken,
  }) async {
    calls += 1;
    if (calls == 1) {
      throw const ApiError(code: 'token_revoked', message: 'revoked');
    }
    return <Object?>[];
  }
}

import 'package:flutter_test/flutter_test.dart';

import 'package:dzmm_next_mobile/pages/play_page.dart';

void main() {
  test('resets a retry when loading another Run', () {
    expect(shouldResetRetriableAction('run-a', 'run-b'), isTrue);
    expect(shouldResetRetriableAction(null, 'run-a'), isTrue);
    expect(shouldResetRetriableAction('run-a', 'run-a'), isFalse);
  });
}

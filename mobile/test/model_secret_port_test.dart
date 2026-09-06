import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:dzmm_mobile/local_host_port.dart';
import 'package:dzmm_mobile/model_secret_store.dart';

class _MemoryModelSecrets implements ModelSecretStore {
  final values = <String, String>{};

  @override
  Future<String?> read(String profileId) async => values[profileId];

  @override
  Future<void> write(String profileId, String value) async {
    values[profileId] = value;
  }

  @override
  Future<void> delete(String profileId) async {
    values.remove(profileId);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'Android adapter keeps API keys in secure storage and forwards them ephemerally',
    () async {
      const channel = MethodChannel('dzmm/model-secret-test');
      final calls = <MethodCall>[];
      final secrets = _MemoryModelSecrets();
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            calls.add(call);
            if (call.method == LocalHostOperation.createModelProfile) {
              return jsonEncode({
                'id': 'profile-1',
                'name': '远程模型',
                'provider_type': 'openai_compat',
                'base_url': 'https://models.example/v1',
                'model_name': 'story-large',
                'is_default': true,
                'has_api_key': true,
              });
            }
            if (call.method == LocalHostOperation.probeModelProfile) {
              return jsonEncode({
                'success': true,
                'endpoint': 'https://models.example/v1/chat/completions',
                'detail': 'protocol response contains content',
              });
            }
            if (call.method == LocalHostOperation.deleteModelProfile) {
              return jsonEncode({'deleted': true});
            }
            throw MissingPluginException(call.method);
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      final port = EmbeddedPythonLocalHostPort(channel, secrets);

      final profile = await port.createModelProfile({
        'name': '远程模型',
        'provider_type': 'openai_compat',
        'base_url': 'https://models.example/v1',
        'model_name': 'story-large',
        'api_key': 'sk-android-secret',
      });

      expect(profile.hasApiKey, isTrue);
      expect(secrets.values['profile-1'], 'sk-android-secret');
      final createArguments = Map<String, dynamic>.from(
        calls.first.arguments as Map,
      );
      expect(createArguments['api_key'], isNull);
      expect(createArguments['has_api_key'], isTrue);

      await port.probeModelProfile(profile.id);
      final probeArguments = Map<String, dynamic>.from(
        calls[1].arguments as Map,
      );
      expect(probeArguments['api_key'], 'sk-android-secret');

      await port.deleteModelProfile(profile.id);
      expect(secrets.values, isEmpty);
    },
  );

  test(
    'Android adapter removes Python exception names from player errors',
    () async {
      const channel = MethodChannel('dzmm/player-error-test');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (_) async {
            throw PlatformException(
              code: 'python_error',
              message:
                  'dzmm.core_runtime_errors.CoreRuntimeError: '
                  '模型在 120 秒内没有返回内容。当前操作未完成。',
            );
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      final port = EmbeddedPythonLocalHostPort(channel, _MemoryModelSecrets());

      await expectLater(
        port.runtimeHealth(),
        throwsA(
          isA<LocalHostError>()
              .having(
                (error) => error.detail,
                'detail',
                startsWith('模型在 120 秒内没有返回内容。'),
              )
              .having(
                (error) => error.detail,
                'detail',
                isNot(contains('CoreRuntimeError')),
              ),
        ),
      );
    },
  );
}

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract interface class ModelSecretStore {
  Future<String?> read(String profileId);
  Future<void> write(String profileId, String value);
  Future<void> delete(String profileId);
}

class SecureModelSecretStore implements ModelSecretStore {
  const SecureModelSecretStore([this._storage = const FlutterSecureStorage()]);

  static const _prefix = 'model_api_key:';
  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String profileId) =>
      _storage.read(key: '$_prefix$profileId');

  @override
  Future<void> write(String profileId, String value) =>
      _storage.write(key: '$_prefix$profileId', value: value);

  @override
  Future<void> delete(String profileId) =>
      _storage.delete(key: '$_prefix$profileId');
}

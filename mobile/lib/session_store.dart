import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class LocalSession {
  const LocalSession({
    this.runId,
    this.modelProfileId,
    this.pendingRunOperation = false,
    this.draftGenre,
    this.draftTone,
    this.draftConflict,
    this.draftHeroPreference,
  });

  final String? runId;
  final String? modelProfileId;
  final bool pendingRunOperation;

  /// 创作页表单草稿——进程被杀后恢复，避免长文本丢失。
  final String? draftGenre;
  final String? draftTone;
  final String? draftConflict;
  final String? draftHeroPreference;

  bool get hasDraft =>
      (draftGenre != null && draftGenre!.isNotEmpty) ||
      (draftTone != null && draftTone!.isNotEmpty) ||
      (draftConflict != null && draftConflict!.isNotEmpty);
}

abstract class SessionStore {
  Future<LocalSession> read();
  Future<void> save(LocalSession session);
  Future<String?> readTheme();
  Future<void> saveTheme(String theme);
}

class SecureSessionStore implements SessionStore {
  const SecureSessionStore([this._storage = const FlutterSecureStorage()]);

  static const _runKey = 'active_run_id';
  static const _modelProfileKey = 'default_model_profile_id';
  static const _pendingRunKey = 'pending_run_operation';
  static const _themeKey = 'theme';
  static const _draftGenreKey = 'draft_genre';
  static const _draftToneKey = 'draft_tone';
  static const _draftConflictKey = 'draft_conflict';
  static const _draftHeroKey = 'draft_hero_preference';

  final FlutterSecureStorage _storage;

  @override
  Future<LocalSession> read() async => LocalSession(
    runId: await _storage.read(key: _runKey),
    modelProfileId: await _storage.read(key: _modelProfileKey),
    pendingRunOperation: await _storage.read(key: _pendingRunKey) == '1',
    draftGenre: await _storage.read(key: _draftGenreKey),
    draftTone: await _storage.read(key: _draftToneKey),
    draftConflict: await _storage.read(key: _draftConflictKey),
    draftHeroPreference: await _storage.read(key: _draftHeroKey),
  );

  @override
  Future<void> save(LocalSession session) async {
    await _writeOrDelete(_runKey, session.runId);
    await _writeOrDelete(_modelProfileKey, session.modelProfileId);
    if (session.pendingRunOperation) {
      await _storage.write(key: _pendingRunKey, value: '1');
    } else {
      await _storage.delete(key: _pendingRunKey);
    }
    await _writeOrDelete(_draftGenreKey, session.draftGenre);
    await _writeOrDelete(_draftToneKey, session.draftTone);
    await _writeOrDelete(_draftConflictKey, session.draftConflict);
    await _writeOrDelete(_draftHeroKey, session.draftHeroPreference);
  }

  @override
  Future<String?> readTheme() => _storage.read(key: _themeKey);

  @override
  Future<void> saveTheme(String theme) =>
      _storage.write(key: _themeKey, value: theme);

  Future<void> _writeOrDelete(String key, String? value) {
    if (value == null || value.isEmpty) return _storage.delete(key: key);
    return _storage.write(key: key, value: value);
  }
}

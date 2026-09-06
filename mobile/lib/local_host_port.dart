import 'dart:convert';

import 'package:flutter/services.dart';

import 'model_secret_store.dart';

abstract final class LocalHostOperation {
  static const runtimeHealth = 'runtime_health';
  static const listWorlds = 'list_worlds';
  static const getWorld = 'get_world';
  static const archiveWorld = 'archive_world';
  static const restoreWorld = 'restore_world';
  static const deleteWorld = 'delete_world';
  static const createRun = 'create_run';
  static const exportWorld = 'export_world';
  static const importWorld = 'import_world';
  static const exportRun = 'export_run';
  static const cloneRun = 'clone_run';
  static const worldTemplate = 'world_template';
  static const listModelProfiles = 'list_model_profiles';
  static const createModelProfile = 'create_model_profile';
  static const updateModelProfile = 'update_model_profile';
  static const setDefaultModelProfile = 'set_default_model_profile';
  static const deleteModelProfile = 'delete_model_profile';
  static const probeModelProfile = 'probe_model_profile';
  static const generateAiWorldDraft = 'generate_ai_world_draft';
  static const validateAiWorldDraft = 'validate_ai_world_draft';
  static const composeWorld = 'compose_world';
  static const getRun = 'get_run';
  static const choose = 'choose';
  static const playTurn = 'play_turn';
  static const cancelOperation = 'cancel_operation';
  static const rollback = 'rollback';
}

abstract final class LocalHostOperationStage {
  static const preparing = 'preparing';
  static const connecting = 'connecting';
  static const generating = 'generating';
  static const applying = 'applying';
  static const completed = 'completed';
  static const failed = 'failed';
  static const cancelled = 'cancelled';
  static const restored = 'restored';

  static const values = <String>[
    preparing,
    connecting,
    generating,
    applying,
    completed,
    failed,
    cancelled,
    restored,
  ];

  static const cancellable = <String>{preparing, connecting, generating};
  static const terminal = <String>{completed, failed, cancelled, restored};

  static const labels = <String, String>{
    preparing: '准备',
    connecting: '连接模型',
    generating: '生成叙事',
    applying: '状态写入',
    completed: '完成',
    failed: '失败',
    cancelled: '已取消',
    restored: '已恢复',
  };
}

class LocalHostError implements Exception {
  const LocalHostError(this.detail, {this.code});

  final String detail;
  final String? code;

  @override
  String toString() => detail;
}

class RunSnapshot {
  const RunSnapshot(this.value);

  final Map<String, dynamic> value;

  String get runId => value['run_id'] as String;
  String get worldId => value['world_id'] as String;
  String get status => value['status'] as String? ?? 'active';
  Map<String, dynamic> get state =>
      Map<String, dynamic>.from(value['state'] as Map);
  Map<String, dynamic> get presentation => Map<String, dynamic>.from(
    value['presentation'] as Map? ?? const <String, dynamic>{},
  );
  List<Map<String, dynamic>> get turns => (value['turns'] as List<dynamic>)
      .map((turn) => Map<String, dynamic>.from(turn as Map))
      .toList(growable: false);
  List<Map<String, dynamic>> get completedTurns => turns
      .where((turn) => (turn['kind'] as String? ?? 'turn') == 'turn')
      .toList(growable: false);
  List<Map<String, dynamic>> get availableChoices =>
      (value['available_choices'] as List<dynamic>? ?? const [])
          .map((choice) => Map<String, dynamic>.from(choice as Map))
          .toList(growable: false);
  List<Map<String, dynamic>> get storyBeats =>
      (value['story_beats'] as List<dynamic>? ?? const [])
          .map((beat) => Map<String, dynamic>.from(beat as Map))
          .toList(growable: false);
}

class WorldSummary {
  const WorldSummary({
    required this.id,
    required this.name,
    required this.status,
    required this.runCount,
    required this.latestRunId,
  });

  final String id;
  final String name;
  final String status;
  final int runCount;
  final String? latestRunId;

  factory WorldSummary.fromJson(Map<String, dynamic> json) => WorldSummary(
    id: json['id'] as String,
    name: json['name'] as String,
    status: json['status'] as String,
    runCount: json['run_count'] as int,
    latestRunId: json['latest_run_id'] as String?,
  );
}

class RunSummary {
  const RunSummary({
    required this.id,
    required this.heroName,
    required this.revision,
    this.status = 'active',
  });

  final String id;
  final String heroName;
  final int revision;
  final String status;

  factory RunSummary.fromJson(Map<String, dynamic> json) => RunSummary(
    id: json['id'] as String,
    heroName: json['hero_name'] as String,
    revision: json['revision'] as int,
    status: json['status'] as String? ?? 'active',
  );
}

class WorldDetail {
  const WorldDetail({
    required this.id,
    required this.name,
    required this.status,
    required this.worldVersionId,
    required this.runs,
  });

  final String id;
  final String name;
  final String status;
  final String worldVersionId;
  final List<RunSummary> runs;

  factory WorldDetail.fromJson(Map<String, dynamic> json) => WorldDetail(
    id: json['id'] as String,
    name: json['name'] as String,
    status: json['status'] as String? ?? 'active',
    worldVersionId: json['latest_world_version_id'] as String,
    runs: (json['runs'] as List<dynamic>)
        .map(
          (item) => RunSummary.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false),
  );
}

class ModelProfile {
  const ModelProfile({
    required this.id,
    required this.name,
    required this.providerType,
    required this.baseUrl,
    required this.modelName,
    this.isDefault = false,
    this.hasApiKey = false,
  });

  final String id;
  final String name;
  final String providerType;
  final String baseUrl;
  final String modelName;
  final bool isDefault;
  final bool hasApiKey;

  factory ModelProfile.fromJson(Map<String, dynamic> json) => ModelProfile(
    id: json['id'] as String,
    name: json['name'] as String,
    providerType: json['provider_type'] as String,
    baseUrl: json['base_url'] as String,
    modelName: json['model_name'] as String,
    isDefault: json['is_default'] as bool? ?? false,
    hasApiKey: json['has_api_key'] as bool? ?? false,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'provider_type': providerType,
    'base_url': baseUrl,
    'model_name': modelName,
    'is_default': isDefault,
    'has_api_key': hasApiKey,
  };
}

class ModelProbeResult {
  const ModelProbeResult({
    required this.success,
    required this.endpoint,
    required this.detail,
  });

  final bool success;
  final String endpoint;
  final String detail;

  factory ModelProbeResult.fromJson(Map<String, dynamic> json) =>
      ModelProbeResult(
        success: json['success'] as bool,
        endpoint: json['endpoint'] as String,
        detail: json['detail'] as String,
      );
}

class AIWorldDraft {
  const AIWorldDraft({
    required this.valid,
    required this.summary,
    required this.worldDefinition,
    required this.hero,
    required this.repairs,
    required this.issues,
  });

  final bool valid;
  final String? summary;
  final Map<String, dynamic>? worldDefinition;
  final Map<String, dynamic>? hero;
  final List<String> repairs;
  final List<Map<String, dynamic>> issues;

  factory AIWorldDraft.fromJson(Map<String, dynamic> json) => AIWorldDraft(
    valid: json['valid'] as bool,
    summary: json['summary'] as String?,
    worldDefinition: json['world_definition'] == null
        ? null
        : Map<String, dynamic>.from(json['world_definition'] as Map),
    hero: json['hero'] == null
        ? null
        : Map<String, dynamic>.from(json['hero'] as Map),
    repairs: (json['repairs'] as List<dynamic>).cast<String>(),
    issues: (json['issues'] as List<dynamic>)
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList(growable: false),
  );
}

class ComposeResult {
  const ComposeResult({
    required this.worldId,
    required this.worldVersionId,
    required this.runId,
  });

  final String worldId;
  final String worldVersionId;
  final String runId;

  factory ComposeResult.fromJson(Map<String, dynamic> json) => ComposeResult(
    worldId: json['world_id'] as String,
    worldVersionId: json['world_version_id'] as String? ?? '',
    runId: json['run_id'] as String,
  );
}

/// Platform-neutral operation boundary. Flutter never changes RunState directly.
abstract class LocalHostPort {
  Future<Map<String, dynamic>> runtimeHealth();
  Future<List<WorldSummary>> listWorlds();
  Future<WorldDetail> getWorld(String worldId);
  Future<void> archiveWorld(String worldId);
  Future<void> restoreWorld(String worldId);
  Future<void> deleteWorld(String worldId);
  Future<ComposeResult> createRun(String worldId, Map<String, dynamic> payload);
  Future<Map<String, dynamic>> exportWorld(String worldId);
  Future<ComposeResult> importWorld(Map<String, dynamic> payload);
  Future<Map<String, dynamic>> exportRun(String runId);
  Future<ComposeResult> cloneRun(Map<String, dynamic> payload);
  Future<Map<String, dynamic>> worldTemplate();
  Future<List<ModelProfile>> listModelProfiles();
  Future<ModelProfile> createModelProfile(Map<String, dynamic> profile);
  Future<ModelProfile> updateModelProfile(
    String profileId,
    Map<String, dynamic> profile,
  );
  Future<ModelProfile> setDefaultModelProfile(String profileId);
  Future<void> deleteModelProfile(String profileId);
  Future<ModelProbeResult> probeModelProfile(String profileId);
  Future<AIWorldDraft> generateDraft(Map<String, dynamic> brief);
  Future<AIWorldDraft> validateDraft(Map<String, dynamic> draft);
  Future<ComposeResult> composeWorld(Map<String, dynamic> payload);
  Future<RunSnapshot> getRun(String runId);
  Future<RunSnapshot> choose(String runId, Map<String, dynamic> payload);
  Future<RunSnapshot> playTurn(String runId, Map<String, dynamic> payload);
  Future<bool> cancelOperation(String requestId);
  Future<RunSnapshot> rollback(String runId, Map<String, dynamic> payload);
}

/// Android adapter for the embedded Python runtime. Its method names map to
/// Python-owned use cases, never to Dart-side state mutation.
class EmbeddedPythonLocalHostPort implements LocalHostPort {
  EmbeddedPythonLocalHostPort([
    this._channel = const MethodChannel('dzmm/local_host'),
    ModelSecretStore? modelSecrets,
  ]) : _modelSecrets = modelSecrets ?? const SecureModelSecretStore();

  final MethodChannel _channel;
  final ModelSecretStore _modelSecrets;
  final Map<String, String?> _runModelProfiles = {};

  Future<Map<String, dynamic>> _call(
    String operation, [
    Map<String, dynamic>? arguments,
  ]) async {
    try {
      final value = await _channel.invokeMethod<String>(operation, arguments);
      if (value == null) throw const LocalHostError('本机运行时返回了空结果。');
      return Map<String, dynamic>.from(jsonDecode(value) as Map);
    } on PlatformException catch (error) {
      throw LocalHostError(
        _playerSafePlatformMessage(error.message),
        code: error.code,
      );
    } on MissingPluginException {
      throw const LocalHostError(
        '本机 Python 运行时尚未安装。',
        code: 'runtime_unavailable',
      );
    }
  }

  @override
  Future<Map<String, dynamic>> runtimeHealth() =>
      _call(LocalHostOperation.runtimeHealth);

  @override
  Future<List<WorldSummary>> listWorlds() async {
    final value = await _call(LocalHostOperation.listWorlds);
    return (value['worlds'] as List<dynamic>)
        .map(
          (item) =>
              WorldSummary.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  @override
  Future<WorldDetail> getWorld(String worldId) async => WorldDetail.fromJson(
    await _call(LocalHostOperation.getWorld, {'world_id': worldId}),
  );

  @override
  Future<void> archiveWorld(String worldId) async {
    await _call(LocalHostOperation.archiveWorld, {'world_id': worldId});
  }

  @override
  Future<void> restoreWorld(String worldId) async {
    await _call(LocalHostOperation.restoreWorld, {'world_id': worldId});
  }

  @override
  Future<void> deleteWorld(String worldId) async {
    await _call(LocalHostOperation.deleteWorld, {'world_id': worldId});
  }

  @override
  Future<ComposeResult> createRun(
    String worldId,
    Map<String, dynamic> payload,
  ) async => ComposeResult.fromJson(
    await _call(LocalHostOperation.createRun, {
      'world_id': worldId,
      ...payload,
    }),
  );

  @override
  Future<Map<String, dynamic>> exportWorld(String worldId) =>
      _call(LocalHostOperation.exportWorld, {'world_id': worldId});

  @override
  Future<ComposeResult> importWorld(Map<String, dynamic> payload) async =>
      ComposeResult.fromJson(
        await _call(LocalHostOperation.importWorld, payload),
      );

  @override
  Future<Map<String, dynamic>> exportRun(String runId) =>
      _call(LocalHostOperation.exportRun, {'run_id': runId});

  @override
  Future<ComposeResult> cloneRun(Map<String, dynamic> payload) async =>
      ComposeResult.fromJson(await _call(LocalHostOperation.cloneRun, payload));

  @override
  Future<Map<String, dynamic>> worldTemplate() =>
      _call(LocalHostOperation.worldTemplate);

  @override
  Future<List<ModelProfile>> listModelProfiles() async {
    final value = await _call(LocalHostOperation.listModelProfiles);
    return (value['profiles'] as List<dynamic>)
        .map(
          (item) =>
              ModelProfile.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  @override
  Future<ModelProfile> createModelProfile(Map<String, dynamic> profile) async {
    final prepared = _prepareProfile(profile);
    final value = await _call(
      LocalHostOperation.createModelProfile,
      prepared.payload,
    );
    final created = ModelProfile.fromJson(value);
    if (prepared.apiKey != null) {
      try {
        await _modelSecrets.write(created.id, prepared.apiKey!);
      } catch (error) {
        await _call(LocalHostOperation.deleteModelProfile, {
          'profile_id': created.id,
        });
        throw LocalHostError('系统安全存储无法保存 API Key：$error');
      }
    }
    return created;
  }

  @override
  Future<ModelProfile> updateModelProfile(
    String profileId,
    Map<String, dynamic> profile,
  ) async {
    final prepared = _prepareProfile(profile);
    final value = await _call(LocalHostOperation.updateModelProfile, {
      ...prepared.payload,
      'profile_id': profileId,
    });
    if (prepared.apiKey != null) {
      try {
        await _modelSecrets.write(profileId, prepared.apiKey!);
      } catch (error) {
        await _call(LocalHostOperation.updateModelProfile, {
          ...prepared.payload,
          'profile_id': profileId,
          'has_api_key': false,
        });
        throw LocalHostError('系统安全存储无法更新 API Key：$error');
      }
    }
    return ModelProfile.fromJson(value);
  }

  @override
  Future<ModelProfile> setDefaultModelProfile(String profileId) async =>
      ModelProfile.fromJson(
        await _call(LocalHostOperation.setDefaultModelProfile, {
          'profile_id': profileId,
        }),
      );

  @override
  Future<void> deleteModelProfile(String profileId) async {
    await _call(LocalHostOperation.deleteModelProfile, {
      'profile_id': profileId,
    });
    await _modelSecrets.delete(profileId);
  }

  @override
  Future<ModelProbeResult> probeModelProfile(String profileId) async {
    final apiKey = await _modelSecrets.read(profileId);
    return ModelProbeResult.fromJson(
      await _call(LocalHostOperation.probeModelProfile, {
        'profile_id': profileId,
        if (apiKey != null && apiKey.isNotEmpty) 'api_key': apiKey,
      }),
    );
  }

  @override
  Future<AIWorldDraft> generateDraft(Map<String, dynamic> brief) async {
    final profileId = brief['model_profile_id'] as String?;
    return AIWorldDraft.fromJson(
      await _call(
        LocalHostOperation.generateAiWorldDraft,
        await _withProfileSecret(profileId, brief),
      ),
    );
  }

  @override
  Future<AIWorldDraft> validateDraft(Map<String, dynamic> draft) async =>
      AIWorldDraft.fromJson(
        await _call(LocalHostOperation.validateAiWorldDraft, draft),
      );

  @override
  Future<ComposeResult> composeWorld(Map<String, dynamic> payload) async =>
      ComposeResult.fromJson(
        await _call(LocalHostOperation.composeWorld, payload),
      );

  @override
  Future<RunSnapshot> getRun(String runId) async {
    final value = await _call(LocalHostOperation.getRun, {'run_id': runId});
    _runModelProfiles[runId] = value['model_profile_id'] as String?;
    return RunSnapshot(value);
  }

  @override
  Future<RunSnapshot> choose(
    String runId,
    Map<String, dynamic> payload,
  ) async => RunSnapshot(
    await _call(
      LocalHostOperation.choose,
      await _withRunSecret(runId, {'run_id': runId, ...payload}),
    ),
  );

  @override
  Future<RunSnapshot> playTurn(
    String runId,
    Map<String, dynamic> payload,
  ) async => RunSnapshot(
    await _call(
      LocalHostOperation.playTurn,
      await _withRunSecret(runId, {'run_id': runId, ...payload}),
    ),
  );

  @override
  Future<bool> cancelOperation(String requestId) async {
    final value = await _call(LocalHostOperation.cancelOperation, {
      'request_id': requestId,
    });
    return value['accepted'] as bool;
  }

  @override
  Future<RunSnapshot> rollback(
    String runId,
    Map<String, dynamic> payload,
  ) async => RunSnapshot(
    await _call(LocalHostOperation.rollback, {'run_id': runId, ...payload}),
  );

  ({Map<String, dynamic> payload, String? apiKey}) _prepareProfile(
    Map<String, dynamic> profile,
  ) {
    final payload = Map<String, dynamic>.from(profile);
    final apiKey = (payload.remove('api_key') as String?)?.trim();
    if (apiKey != null && apiKey.isNotEmpty) payload['has_api_key'] = true;
    return (
      payload: payload,
      apiKey: apiKey == null || apiKey.isEmpty ? null : apiKey,
    );
  }

  Future<Map<String, dynamic>> _withRunSecret(
    String runId,
    Map<String, dynamic> payload,
  ) async {
    if (!_runModelProfiles.containsKey(runId)) await getRun(runId);
    return _withProfileSecret(_runModelProfiles[runId], payload);
  }

  Future<Map<String, dynamic>> _withProfileSecret(
    String? profileId,
    Map<String, dynamic> payload,
  ) async {
    if (profileId == null || profileId.isEmpty) return payload;
    final apiKey = await _modelSecrets.read(profileId);
    if (apiKey == null || apiKey.isEmpty) return payload;
    return {...payload, 'api_key': apiKey};
  }
}

String _playerSafePlatformMessage(String? message) {
  final value = message?.trim();
  if (value == null || value.isEmpty) return '本机运行时不可用。';
  const marker = 'CoreRuntimeError:';
  final markerIndex = value.lastIndexOf(marker);
  if (markerIndex < 0) return value;
  final detail = value.substring(markerIndex + marker.length).trim();
  return detail.isEmpty ? '本机运行时不可用。' : detail;
}

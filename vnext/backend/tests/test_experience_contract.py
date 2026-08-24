import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "contracts" / "experience_contract.json"


def test_local_host_adapters_cover_every_contract_operation() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    operations = contract["properties"]["operations"]["const"]

    dart = (ROOT / "mobile" / "lib" / "local_host_port.dart").read_text(encoding="utf-8")
    kotlin = (
        ROOT
        / "mobile"
        / "android"
        / "app"
        / "src"
        / "main"
        / "kotlin"
        / "local"
        / "dzmm"
        / "dzmm_next_mobile"
        / "MainActivity.kt"
    ).read_text(encoding="utf-8")
    desktop = (ROOT / "desktop" / "src" / "api.ts").read_text(encoding="utf-8")

    dart_operation_block = dart.split("abstract final class LocalHostOperation {", 1)[1].split("\n}", 1)[0]
    dart_operations = set(re.findall(r"static const \w+ = '([^']+)';", dart_operation_block))
    kotlin_block = kotlin.split("private val supportedOperations = setOf(", 1)[1].split(")", 1)[0]
    kotlin_operations = set(re.findall(r'"([a-z_]+)"', kotlin_block))
    assert dart_operations - {"runtime_health"} == set(operations)
    assert kotlin_operations - {"runtime_health"} == set(operations)

    bridge_names = {
        "list_worlds": "list_worlds",
        "get_world": "get_world",
        "archive_world": "archive_world",
        "restore_world": "restore_world",
        "delete_world": "delete_world",
        "create_run": "create_run",
        "world_template": "world_template",
        "list_model_profiles": "list_model_profiles",
        "create_model_profile": "create_model_profile",
        "update_model_profile": "update_model_profile",
        "set_default_model_profile": "set_default_model_profile",
        "delete_model_profile": "delete_model_profile",
        "probe_model_profile": "probe_model_profile",
        "generate_ai_world_draft": "generate_ai_world_draft",
        "validate_ai_world_draft": "validate_ai_world_draft",
        "compose_world": "compose_world",
        "get_run": "get_run",
        "choose": "choose",
        "play_turn": "play_turn",
        "cancel_operation": "cancel_operation",
        "rollback": "rollback",
        "export_world": "export_world",
        "import_world": "import_world",
        "export_run": "export_run",
        "clone_run": "clone_run",
    }
    for operation, bridge_name in bridge_names.items():
        assert bridge_name in dart, f"Dart LocalHostPort missing {operation}"
        assert f'"{bridge_name}"' in kotlin, f"Android bridge missing {operation}"

    desktop_names = {
        "list_worlds": "listWorlds",
        "get_world": "getWorld",
        "archive_world": "archiveWorld",
        "restore_world": "restoreWorld",
        "delete_world": "deleteWorld",
        "create_run": "createRun",
        "world_template": "getFogHarborTemplate",
        "list_model_profiles": "listModelProfiles",
        "create_model_profile": "createModelProfile",
        "update_model_profile": "updateModelProfile",
        "set_default_model_profile": "setDefaultModelProfile",
        "delete_model_profile": "deleteModelProfile",
        "probe_model_profile": "probeModelProfile",
        "generate_ai_world_draft": "generateAIWorldDraft",
        "validate_ai_world_draft": "validateAIWorldDraft",
        "compose_world": "composeWorld",
        "get_run": "getRun",
        "choose": "chooseTurn",
        "play_turn": "createTurn",
        "cancel_operation": "cancelOperation",
        "rollback": "rollbackTurn",
        "export_world": "exportWorld",
        "import_world": "importWorld",
        "export_run": "exportRun",
        "clone_run": "cloneRun",
    }
    for operation, function_name in desktop_names.items():
        assert f"function {function_name}" in desktop, f"Desktop adapter missing {operation}"
        assert operation in operations


def test_platform_operation_stages_match_the_experience_contract() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    stages = contract["properties"]["operation_stages"]["const"]

    dart = (ROOT / "mobile" / "lib" / "local_host_port.dart").read_text(encoding="utf-8")
    dart_stage_block = dart.split("abstract final class LocalHostOperationStage {", 1)[1].split("\n}", 1)[0]
    dart_stages = re.findall(r"static const \w+ = '([^']+)';", dart_stage_block)

    desktop = (ROOT / "desktop" / "src" / "composables" / "operationStages.ts").read_text(encoding="utf-8")
    desktop_stage_block = desktop.split("OPERATION_STAGES = [", 1)[1].split("] as const", 1)[0]
    desktop_stages = re.findall(r"'([a-z_]+)'", desktop_stage_block)

    assert dart_stages == stages
    assert desktop_stages == stages


def test_android_model_operations_run_off_the_ui_thread() -> None:
    kotlin = (
        ROOT
        / "mobile"
        / "android"
        / "app"
        / "src"
        / "main"
        / "kotlin"
        / "local"
        / "dzmm"
        / "dzmm_next_mobile"
        / "MainActivity.kt"
    ).read_text(encoding="utf-8")
    background_block = kotlin.split("private val backgroundOperations = setOf(", 1)[1].split(")", 1)[0]
    background_operations = set(re.findall(r'"([a-z_]+)"', background_block))
    assert {
        "choose",
        "play_turn",
        "generate_ai_world_draft",
        "validate_ai_world_draft",
        "probe_model_profile",
    } <= background_operations


def test_contract_keeps_platform_navigation_and_recovery_states_stable() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["properties"]["navigation"]["const"] == [
        "worlds",
        "create",
        "play",
        "models",
        "settings",
    ]
    assert set(contract["properties"]["ui_states"]["const"]) >= {
        "loading",
        "success",
        "validation_error",
        "provider_error",
        "conflict",
        "cancelled",
        "restored",
    }
    assert contract["properties"]["operation_stages"]["const"] == [
        "preparing",
        "connecting",
        "generating",
        "applying",
        "completed",
        "failed",
        "cancelled",
        "restored",
    ]

    presets = contract["properties"]["model_provider_presets"]["const"]
    desktop_profiles = (
        ROOT / "desktop" / "src" / "composables" / "useModelProfiles.ts"
    ).read_text(encoding="utf-8")
    android_profiles = (ROOT / "mobile" / "lib" / "pages" / "models_page.dart").read_text(
        encoding="utf-8"
    )
    for provider, base_url in presets.items():
        assert provider in desktop_profiles and provider in android_profiles
        if base_url:
            assert base_url in desktop_profiles and base_url in android_profiles
    assert "openai_compat: ''" in desktop_profiles
    assert "'openai_compat': ''" in android_profiles


def test_desktop_player_shell_is_offline_safe_and_keyboard_visible() -> None:
    index = (ROOT / "desktop" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "desktop" / "src" / "App.vue").read_text(encoding="utf-8")
    styles = (ROOT / "desktop" / "src" / "style.css").read_text(encoding="utf-8")

    assert 'name="theme-color"' in index
    assert "user-scalable=no" not in index
    assert "maximum-scale=1" not in index
    assert 'class="skip-link" href="#main-content"' in app
    assert 'id="main-content" tabindex="-1"' in app
    assert 'role="status" aria-live="polite"' in app
    assert "fonts.googleapis.com" not in styles
    assert ":focus-visible" in styles
    assert "touch-action: manipulation" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles

    android_shell = (ROOT / "mobile" / "lib" / "main.dart").read_text(encoding="utf-8")
    assert "autofocus: true" not in android_shell

    desktop_profiles = (
        ROOT / "desktop" / "src" / "composables" / "useModelProfiles.ts"
    ).read_text(encoding="utf-8")
    assert "192.168." not in desktop_profiles
    assert "huihui" not in desktop_profiles.lower()

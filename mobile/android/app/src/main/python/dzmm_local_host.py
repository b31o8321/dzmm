"""Chaquopy adapter for the shared transport-free DZMM core runtime."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any

from dzmm.core_runtime import CoreRuntimeError, LocalCoreRuntime
from dzmm.world_templates import fog_harbor_template


_runtimes: dict[str, LocalCoreRuntime] = {}


def _result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _arguments(arguments: str) -> dict[str, Any]:
    value = json.loads(arguments or "{}")
    if not isinstance(value, dict):
        raise CoreRuntimeError("bridge arguments must be an object")
    return value


def _runtime(arguments: str) -> LocalCoreRuntime:
    data_dir = _arguments(arguments).get("data_dir")
    if not data_dir:
        raise CoreRuntimeError("Android app-private data directory is missing")
    database = str(Path(data_dir) / "dzmm.db")
    if database not in _runtimes:
        _runtimes[database] = LocalCoreRuntime(database)
    return _runtimes[database]


def runtime_health(arguments: str = "{}") -> str:
    health = _runtime(arguments).health()
    return _result(**health, python=platform.python_version(), core="shared_transport_free")


def list_worlds(arguments: str = "{}") -> str:
    return _result(worlds=_runtime(arguments).list_worlds())


def get_world(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).get_world(str(value.get("world_id") or "")))


def archive_world(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).archive_world(str(value.get("world_id") or "")))


def restore_world(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).restore_world(str(value.get("world_id") or "")))


def delete_world(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).delete_world(str(value.get("world_id") or "")))


def create_run(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).create_run(str(value.get("world_id") or ""), value))


def list_model_profiles(arguments: str = "{}") -> str:
    return _result(profiles=_runtime(arguments).list_model_profiles())


def create_model_profile(arguments: str = "{}") -> str:
    return _result(**_runtime(arguments).create_model_profile(_arguments(arguments)))


def update_model_profile(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(
        **_runtime(arguments).update_model_profile(str(value.get("profile_id") or ""), value)
    )


def set_default_model_profile(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(
        **_runtime(arguments).set_default_model_profile(str(value.get("profile_id") or ""))
    )


def delete_model_profile(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    _runtime(arguments).delete_model_profile(str(value.get("profile_id") or ""))
    return _result(deleted=True)


def probe_model_profile(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(
        **_runtime(arguments).probe_model_profile(
            str(value.get("profile_id") or ""), str(value.get("api_key") or "") or None
        )
    )


def world_template(arguments: str = "{}") -> str:
    return _result(**fog_harbor_template())


def compose_world(arguments: str = "{}") -> str:
    return _result(**_runtime(arguments).compose(_arguments(arguments)))


def get_run(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).get_run(str(value.get("run_id") or "")))


def choose(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    runtime = _runtime(arguments)
    request_id = str(value.get("request_id") or "")
    if not runtime.begin_operation(request_id):
        raise CoreRuntimeError("operation is already running")
    try:
        return _result(**runtime.choose(str(value.get("run_id") or ""), value))
    finally:
        runtime.finish_operation(request_id)


def play_turn(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    runtime = _runtime(arguments)
    request_id = str(value.get("request_id") or "")
    if not runtime.begin_operation(request_id):
        raise CoreRuntimeError("operation is already running")
    try:
        return _result(**runtime.play(str(value.get("run_id") or ""), value))
    finally:
        runtime.finish_operation(request_id)


def cancel_operation(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    request_id = str(value.get("request_id") or "")
    accepted = _runtime(arguments).cancel_operation(request_id)
    return _result(
        request_id=request_id,
        accepted=accepted,
        detail=(
            "cancellation accepted; the original Run state will be preserved"
            if accepted
            else "operation is no longer cancellable"
        ),
    )


def rollback(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).rollback(str(value.get("run_id") or ""), value))


def validate_ai_world_draft(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).validate(value.get("world_definition") or {}, value.get("hero")))


def generate_ai_world_draft(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    runtime = _runtime(arguments)
    request_id = str(value.get("request_id") or "")
    if request_id and not runtime.begin_operation(request_id):
        raise CoreRuntimeError("operation is already running")
    try:
        draft = runtime.generate_draft(value)
        if request_id:
            runtime.ensure_operation_can_complete(request_id)
        return _result(**draft)
    finally:
        if request_id:
            runtime.finish_operation(request_id)


def export_world(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).export_world(str(value.get("world_id") or "")))


def import_world(arguments: str = "{}") -> str:
    return _result(**_runtime(arguments).import_world(_arguments(arguments)))


def export_run(arguments: str = "{}") -> str:
    value = _arguments(arguments)
    return _result(**_runtime(arguments).export_run(str(value.get("run_id") or "")))


def clone_run(arguments: str = "{}") -> str:
    return _result(**_runtime(arguments).clone_run(_arguments(arguments)))


def unavailable(operation_json: str = "{}") -> str:
    operation = _arguments(operation_json).get("operation", "operation")
    raise CoreRuntimeError(f"{operation} is not implemented in the Android core slice")

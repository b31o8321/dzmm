"""SQLite model-profile repository for the embedded Local Host."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .core_runtime_errors import CoreRuntimeError
from .model_protocol import chat_content, chat_endpoint

MODEL_PROBE_TIMEOUT_SECONDS = 60


class EmbeddedModelProfileStore:
    def __init__(self, connect: Callable[[], sqlite3.Connection]) -> None:
        self._connect = connect

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM local_model_profiles ORDER BY is_default DESC, rowid DESC"
            ).fetchall()
        return [self._value(row) for row in rows]

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = self._validated(payload)
        profile = {"id": str(uuid4()), **values}
        with self._connect() as connection:
            is_default = connection.execute(
                "SELECT COUNT(*) = 0 FROM local_model_profiles"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO local_model_profiles"
                "(id, name, provider_type, base_url, model_name, has_api_key, is_default) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*profile.values(), int(bool(payload.get("has_api_key"))), int(is_default)),
            )
        return {**profile, "is_default": bool(is_default)}

    def update(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        values = self._validated(payload)
        with self._connect() as connection:
            has_api_key = connection.execute(
                "SELECT has_api_key FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if has_api_key is None:
                raise CoreRuntimeError("model profile not found")
            next_has_api_key = (
                int(bool(payload["has_api_key"]))
                if "has_api_key" in payload
                else has_api_key[0]
            )
            changed = connection.execute(
                "UPDATE local_model_profiles SET name = ?, provider_type = ?, "
                "base_url = ?, model_name = ?, has_api_key = ? WHERE id = ?",
                (*values.values(), next_has_api_key, profile_id),
            )
            if changed.rowcount != 1:
                raise CoreRuntimeError("model profile not found")
            row = connection.execute(
                "SELECT * FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        assert row is not None
        return self._value(row)

    def set_default(self, profile_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if row is None:
                raise CoreRuntimeError("model profile not found")
            connection.execute("UPDATE local_model_profiles SET is_default = 0")
            connection.execute(
                "UPDATE local_model_profiles SET is_default = 1 WHERE id = ?", (profile_id,)
            )
            profile = connection.execute(
                "SELECT * FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        assert profile is not None
        return self._value(profile)

    def delete(self, profile_id: str) -> None:
        with self._connect() as connection:
            profile = connection.execute(
                "SELECT * FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if profile is None:
                raise CoreRuntimeError("model profile not found")
            references = connection.execute(
                "SELECT COUNT(*) FROM local_runs WHERE model_profile_id = ?", (profile_id,)
            ).fetchone()[0]
            if references:
                raise CoreRuntimeError(
                    f"模型正被 {references} 个 Run 使用；请先为这些 Run 更换模型后再删除"
                )
            connection.execute("DELETE FROM local_model_profiles WHERE id = ?", (profile_id,))
            if profile["is_default"]:
                connection.execute(
                    "UPDATE local_model_profiles SET is_default = 1 WHERE id = "
                    "(SELECT id FROM local_model_profiles ORDER BY rowid LIMIT 1)"
                )

    def probe(self, profile_id: str, api_key: str | None = None) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise CoreRuntimeError("model profile not found")
        endpoint = chat_endpoint(row["provider_type"], row["base_url"])
        payload = {
            "model": row["model_name"],
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
        }
        headers = {"content-type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=MODEL_PROBE_TIMEOUT_SECONDS
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            return {"success": False, "endpoint": endpoint, "detail": str(error)}
        if isinstance(body, dict) and body.get("error"):
            return {
                "success": False,
                "endpoint": endpoint,
                "detail": f"protocol response error: {body['error']}",
            }
        if not chat_content(row["provider_type"], body):
            return {
                "success": False,
                "endpoint": endpoint,
                "detail": "protocol response contains no content",
            }
        return {
            "success": True,
            "endpoint": endpoint,
            "detail": "protocol response contains content",
        }

    @staticmethod
    def _validated(payload: dict[str, Any]) -> dict[str, str]:
        provider_type = str(payload.get("provider_type") or "")
        required = ("name", "base_url", "model_name")
        if not all(str(payload.get(key) or "").strip() for key in required):
            raise CoreRuntimeError("model profile requires name, base_url and model_name")
        values = {
            "name": str(payload["name"]).strip(),
            "provider_type": provider_type,
            "base_url": str(payload["base_url"]).rstrip("/"),
            "model_name": str(payload["model_name"]).strip(),
        }
        try:
            chat_endpoint(provider_type, values["base_url"])
        except ValueError as error:
            raise CoreRuntimeError(str(error)) from error
        return values

    @staticmethod
    def _value(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["is_default"] = bool(value["is_default"])
        value["has_api_key"] = bool(value["has_api_key"])
        return value

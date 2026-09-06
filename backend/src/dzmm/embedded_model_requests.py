from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from .core_runtime_errors import CoreRuntimeError
from .model_protocol import chat_endpoint
from .model_request_feedback import (
    is_timeout_error,
    model_connection_detail,
    model_invalid_response_detail,
    model_timeout_detail,
)
from .narrative_output import (
    NARRATIVE_OLLAMA_NUM_PREDICT,
    NARRATIVE_OPENAI_MAX_TOKENS,
    NARRATIVE_SYSTEM_PROMPT,
    clean_narrative_output,
)

MODEL_REQUEST_TIMEOUT_SECONDS = 120

WORLD_DRAFT_SCHEMA = {
    "type": "object",
    "required": ["world_definition", "hero"],
    "properties": {
        "world_definition": {
            "type": "object",
            "required": [
                "schema_version",
                "name",
                "lorebook",
                "character_cards",
                "locations",
                "factions",
                "npcs",
                "events",
                "resources",
                "ruleset",
                "story",
            ],
            "properties": {
                "schema_version": {"type": "integer"},
                "name": {"type": "string"},
                "lorebook": {"type": "object"},
                "character_cards": {"type": "array"},
                "locations": {"type": "array"},
                "factions": {"type": "array"},
                "npcs": {"type": "array"},
                "events": {"type": "array"},
                "resources": {"type": "array"},
                "ruleset": {"type": "object"},
                "story": {
                    "type": "object",
                    "required": [
                        "flags",
                        "relationships",
                        "relationship_events",
                        "routes",
                        "chapters",
                        "endings",
                    ],
                    "properties": {
                        "flags": {"type": "array"},
                        "relationships": {"type": "array"},
                        "relationship_events": {"type": "array"},
                        "routes": {"type": "array"},
                        "chapters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "id",
                                    "title",
                                    "order",
                                    "next_chapter_id",
                                    "choices",
                                ],
                            },
                        },
                        "endings": {"type": "array"},
                    },
                },
            },
        },
        "hero": {
            "type": "object",
            "required": ["name", "profile"],
            "properties": {
                "name": {"type": "string"},
                "profile": {"type": "object"},
            },
        },
    },
}


def clean_model_narrative(content: str | None) -> str:
    return clean_narrative_output(content) or ""


def strip_json_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else value[3:]
        value = value.removesuffix("```")
    return value.strip()


def request_narrative(profile: Mapping[str, Any], context: dict[str, Any]) -> Any:
    request_payload: dict[str, Any] = {
        "model": profile["model_name"],
        "messages": [
            {
                "role": "system",
                "content": NARRATIVE_SYSTEM_PROMPT,
            },
            {"role": "user", "content": "/no_think\n" + _dump(context)},
        ],
        "stream": False,
    }
    if profile["provider_type"] == "ollama":
        request_payload["options"] = {
            "temperature": 0.85,
            "top_p": 0.9,
            "num_predict": NARRATIVE_OLLAMA_NUM_PREDICT,
        }
    else:
        request_payload["temperature"] = 0.85
        request_payload["top_p"] = 0.9
        request_payload["max_tokens"] = NARRATIVE_OPENAI_MAX_TOKENS
        if profile["provider_type"] == "lm_studio" and "qwen" in str(profile["model_name"]).lower():
            request_payload["chat_template_kwargs"] = {"enable_thinking": False}
    return _post_chat(profile, request_payload)


def request_world_draft(profile: Mapping[str, Any], prompt: dict[str, Any]) -> Any:
    request_payload: dict[str, Any] = {
        "model": profile["model_name"],
        "messages": [
            {"role": "system", "content": "You are a structured DZMM world author."},
            {"role": "user", "content": _dump(prompt)},
        ],
        "stream": False,
    }
    if profile["provider_type"] == "ollama":
        is_qwen = "qwen" in str(profile.get("model_name") or "").lower()
        request_payload["options"] = {
            "temperature": 0.2,
            "num_predict": 768 if is_qwen else 2048,
        }
    else:
        request_payload["temperature"] = 0.2
        request_payload["max_tokens"] = 4096
        if profile["provider_type"] == "lm_studio":
            request_payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "dzmm_world_draft",
                    "strict": True,
                    "schema": WORLD_DRAFT_SCHEMA,
                },
            }
    return _post_chat(profile, request_payload)


def request_director_note(profile: Mapping[str, Any], prompt: dict[str, Any]) -> Any:
    request_payload: dict[str, Any] = {
        "model": profile["model_name"],
        "messages": [
            {
                "role": "system",
                "content": str(prompt.get("system") or "You are the DZMM pacing director."),
            },
            {"role": "user", "content": _dump({k: v for k, v in prompt.items() if k != "system"})},
        ],
        "stream": False,
    }
    if profile["provider_type"] == "ollama":
        request_payload["options"] = {"temperature": 0.3, "num_predict": 256}
    else:
        request_payload["temperature"] = 0.3
        request_payload["max_tokens"] = 256
    return _post_chat(profile, request_payload)


def _post_chat(profile: Mapping[str, Any], payload: dict[str, Any]) -> Any:
    headers = {"content-type": "application/json"}
    api_key = str(profile.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        chat_endpoint(str(profile["provider_type"]), str(profile["base_url"])),
        data=_dump(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=MODEL_REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        raise CoreRuntimeError(f"model HTTP {error.code}: {detail}") from error
    except TimeoutError as error:
        raise CoreRuntimeError(model_timeout_detail(MODEL_REQUEST_TIMEOUT_SECONDS)) from error
    except urllib.error.URLError as error:
        detail = (
            model_timeout_detail(MODEL_REQUEST_TIMEOUT_SECONDS)
            if is_timeout_error(error)
            else model_connection_detail()
        )
        raise CoreRuntimeError(detail) from error
    except json.JSONDecodeError as error:
        raise CoreRuntimeError(model_invalid_response_detail()) from error
    if isinstance(body, dict) and body.get("error"):
        raise CoreRuntimeError(f"model protocol error: {body['error']}")
    return body


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .persistence import model_profiles

NARRATION_TIMEOUT_SECONDS = 120.0


class ProviderType(StrEnum):
    OLLAMA = "ollama"
    LM_STUDIO = "lm_studio"
    OPENAI_COMPAT = "openai_compat"


class ModelProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    provider_type: ProviderType
    base_url: str = Field(min_length=1, max_length=500)
    model_name: str = Field(min_length=1, max_length=200)

    @field_validator("base_url")
    @classmethod
    def remove_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


class ModelProfile(ModelProfileInput):
    id: str


class ProbeResult(BaseModel):
    success: bool
    endpoint: str
    detail: str


class NarrationError(ValueError):
    pass


class NarrationRateLimitError(NarrationError):
    pass


class ModelProfileService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, payload: ModelProfileInput) -> ModelProfile:
        _chat_endpoint(payload)
        profile = ModelProfile(id=str(uuid4()), **payload.model_dump())
        async with self._session_factory() as session, session.begin():
            await session.execute(
                insert(model_profiles).values(
                    id=profile.id,
                    name=profile.name,
                    provider_type=profile.provider_type,
                    base_url=profile.base_url,
                    model_name=profile.model_name,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        return profile

    async def get(self, profile_id: str) -> ModelProfile | None:
        async with self._session_factory() as session:
            result = await session.execute(select(model_profiles).where(model_profiles.c.id == profile_id))
            row = result.mappings().one_or_none()
        if row is None:
            return None
        return ModelProfile(
            id=row["id"],
            name=row["name"],
            provider_type=row["provider_type"],
            base_url=row["base_url"],
            model_name=row["model_name"],
        )


class ModelProber:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def probe(self, profile: ModelProfile) -> ProbeResult:
        endpoint = _chat_endpoint(profile)
        body = _probe_body(profile)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=10.0) as client:
                response = await client.post(endpoint, json=body)
        except httpx.HTTPError as error:
            return ProbeResult(success=False, endpoint=endpoint, detail=f"connection failed: {error}")
        if response.status_code != 200:
            return ProbeResult(
                success=False,
                endpoint=endpoint,
                detail=f"provider returned HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError:
            return ProbeResult(success=False, endpoint=endpoint, detail="provider returned non-JSON response")
        content = _chat_content(profile.provider_type, payload)
        if isinstance(content, str) and content.strip():
            return ProbeResult(success=True, endpoint=endpoint, detail="protocol response contains content")
        return ProbeResult(
            success=False,
            endpoint=endpoint,
            detail="provider returned HTTP 200 but not a valid non-empty chat response",
        )


class ModelNarrator:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def narrate(
        self,
        profile: ModelProfile,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
        lore_entries: list[dict[str, Any]],
    ) -> str:
        endpoint = _chat_endpoint(profile)
        body = _narration_body(profile, definition, state, player_input, outcomes, lore_entries)
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=NARRATION_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(endpoint, json=body)
        except httpx.HTTPError as error:
            raise NarrationError(
                f"model connection failed: {type(error).__name__}: {error}"
            ) from error
        if response.status_code != 200:
            raise NarrationError(
                f"model returned HTTP {response.status_code}: {_response_detail(response)}"
            )
        try:
            content = _chat_content(profile.provider_type, response.json())
        except ValueError as error:
            raise NarrationError("model returned non-JSON response") from error
        narrative = _clean_narrative(content)
        if not narrative:
            raise NarrationError("model returned no valid narrative content")
        return narrative

    async def stream(
        self,
        profile: ModelProfile,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
        lore_entries: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        endpoint = _chat_endpoint(profile)
        body = _narration_body(
            profile, definition, state, player_input, outcomes, lore_entries, stream=True
        )
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport, timeout=NARRATION_TIMEOUT_SECONDS
                ) as client,
                client.stream("POST", endpoint, json=body) as response,
            ):
                if response.status_code == 429:
                    raise NarrationRateLimitError("model returned HTTP 429")
                if response.status_code != 200:
                    raise NarrationError(f"model returned HTTP {response.status_code}")
                completed = False
                async for line in response.aiter_lines():
                    piece, finished = _stream_piece(profile.provider_type, line)
                    if piece:
                        yield piece
                    completed = completed or finished
                if not completed:
                    raise NarrationError("model stream ended without a completion marker")
        except NarrationError:
            raise
        except httpx.HTTPError as error:
            raise NarrationError(
                f"model connection failed: {type(error).__name__}: {error}"
            ) from error


def _chat_endpoint(profile: ModelProfileInput) -> str:
    base_url = profile.base_url
    if profile.provider_type is ProviderType.OLLAMA:
        if base_url.endswith("/v1"):
            raise ValueError("Ollama base_url must be the server root, not an OpenAI /v1 root")
        return f"{base_url}/api/chat"
    if not base_url.endswith("/v1"):
        raise ValueError("LM Studio and OpenAI-compatible base_url must end with /v1")
    return f"{base_url}/chat/completions"


def _probe_body(profile: ModelProfile) -> dict[str, Any]:
    messages = [{"role": "user", "content": "Reply with OK."}]
    if profile.provider_type is ProviderType.OLLAMA:
        return {"model": profile.model_name, "messages": messages, "stream": False}
    return {"model": profile.model_name, "messages": messages, "stream": False, "max_tokens": 8}


def _chat_content(provider_type: ProviderType, payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    if provider_type is ProviderType.OLLAMA:
        message = payload.get("message")
        return message.get("content") if isinstance(message, dict) else None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    return message.get("content") if isinstance(message, dict) else None


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:300] or "empty response"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("detail")
            if isinstance(detail, str):
                return detail[:300]
        if isinstance(error, str):
            return error[:300]
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail[:300]
    return "unstructured response"


def _narration_body(
    profile: ModelProfile,
    definition: dict[str, Any],
    state: dict[str, Any],
    player_input: str,
    outcomes: list[dict[str, Any]],
    lore_entries: list[dict[str, Any]],
    *,
    stream: bool = False,
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是本地互动叙事的叙事者。只用简洁中文描述 Python 规则引擎已经确认的结果；"
                "你不是状态裁判：不得编造或改变物品、地点、关系、Flag、章节、路线、数值或结局，"
                "不得解释规则，也不得输出标签、命令或 JSON。"
            ),
        },
        {
            "role": "user",
            "content": "/no_think\n"
            + json.dumps(
                {
                    "world": definition["name"],
                    "hero": state["hero"]["name"],
                    "location_id": state["location_id"],
                    "ruleset": state.get("ruleset", {}).get("id"),
                    "chapter": state.get("chapter"),
                    "route": state.get("route"),
                    "relationships": state.get("relationships", {}),
                    "ending": state.get("ending"),
                    "player_input": player_input,
                    "validated_outcomes": outcomes,
                    "active_lore": [
                        {"id": entry["id"], "title": entry["title"], "body": entry["body"]}
                        for entry in lore_entries
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    if profile.provider_type is ProviderType.OLLAMA:
        return {
            "model": profile.model_name,
            "messages": messages,
            "stream": stream,
            "options": {"num_predict": 96},
        }
    body: dict[str, Any] = {
        "model": profile.model_name,
        "messages": messages,
        "stream": stream,
        "max_tokens": 160,
    }
    if profile.provider_type is ProviderType.LM_STUDIO and "qwen" in profile.model_name.lower():
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def _clean_narrative(content: str | None) -> str | None:
    if not isinstance(content, str):
        return None
    value = content.strip()
    if "</think>" in value:
        value = value.split("</think>", maxsplit=1)[1].strip()
    if "### TRPG Narrative:" in value:
        value = value.split("### TRPG Narrative:", maxsplit=1)[1]
    if "### JSON:" in value:
        value = value.split("### JSON:", maxsplit=1)[0]
    value = re.sub(r"^#+\s*", "", value.strip())
    return value.strip() or None


def _stream_piece(provider_type: ProviderType, line: str) -> tuple[str | None, bool]:
    if not line:
        return None, False
    if provider_type is ProviderType.OLLAMA:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise NarrationError("model returned malformed Ollama stream JSON") from error
        if not isinstance(payload, dict):
            raise NarrationError("model returned malformed Ollama stream event")
        if payload.get("error"):
            raise NarrationError("model returned stream error")
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if content is not None and not isinstance(content, str):
            raise NarrationError("model returned malformed Ollama stream content")
        return content, payload.get("done") is True

    if not line.startswith("data:"):
        raise NarrationError("model returned malformed SSE stream event")
    data = line.removeprefix("data:").strip()
    if data == "[DONE]":
        return None, True
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as error:
        raise NarrationError("model returned malformed SSE JSON") from error
    if not isinstance(payload, dict):
        raise NarrationError("model returned malformed SSE event")
    if payload.get("error"):
        raise NarrationError("model returned stream error")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise NarrationError("model returned malformed SSE choices")
    delta = choices[0].get("delta")
    content = delta.get("content") if isinstance(delta, dict) else None
    if content is not None and not isinstance(content, str):
        raise NarrationError("model returned malformed SSE content")
    return content, False

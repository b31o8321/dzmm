from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .persistence import model_profiles


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
            async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
                response = await client.post(endpoint, json=body)
        except httpx.HTTPError as error:
            raise NarrationError(f"model connection failed: {error}") from error
        if response.status_code != 200:
            raise NarrationError(f"model returned HTTP {response.status_code}")
        try:
            content = _chat_content(profile.provider_type, response.json())
        except ValueError as error:
            raise NarrationError("model returned non-JSON response") from error
        narrative = _clean_narrative(content)
        if not narrative:
            raise NarrationError("model returned no valid narrative content")
        return narrative


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


def _narration_body(
    profile: ModelProfile,
    definition: dict[str, Any],
    state: dict[str, Any],
    player_input: str,
    outcomes: list[dict[str, Any]],
    lore_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是单人 TRPG 的叙事者。只用简洁中文描述已经由规则引擎确认的结果；"
                "不要编造物品、地点、数值或状态变化，不要解释规则，不要输出标签或 JSON。"
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
            "stream": False,
            "options": {"num_predict": 220},
        }
    body: dict[str, Any] = {
        "model": profile.model_name,
        "messages": messages,
        "stream": False,
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

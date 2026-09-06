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
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .model_protocol import chat_content as _chat_content
from .model_protocol import chat_endpoint, probe_body
from .model_request_feedback import model_connection_detail, model_timeout_detail
from .model_secrets import ModelSecretStore, default_model_secret_store
from .narrative import available_choices, narrative_variation
from .narrative_context import narrative_entity_names, narrative_world_material
from .narrative_output import (
    NARRATIVE_LM_STUDIO_MAX_TOKENS,
    NARRATIVE_OLLAMA_NUM_PREDICT,
    NARRATIVE_OPENAI_MAX_TOKENS,
    NARRATIVE_SYSTEM_PROMPT,
    clean_narrative_output,
    extract_gm_actions,
    model_response_was_truncated,
)
from .persistence import model_profiles, runs

NARRATION_TIMEOUT_SECONDS = 120.0
PROBE_TIMEOUT_SECONDS = 10.0
DRAFT_OPENAI_MAX_TOKENS = 6000

# LM Studio supports OpenAI-compatible structured output. Keeping this schema
# at the transport boundary prevents local instruct models from returning a
# single event/legacy world object when the caller requested CreativeSource.
CREATIVE_SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["world_name", "summary", "hero", "locations", "characters", "lore"],
    "additionalProperties": False,
    "properties": {
        "world_name": {"type": "string"},
        "summary": {"type": "string"},
        "hero": {
            "type": "object",
            "required": ["name", "origin"],
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "origin": {"type": "string"}},
        },
        "locations": {"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "string"}},
        "characters": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["name", "role", "description"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "lore": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["title", "body"],
                "additionalProperties": False,
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            },
        },
        "npcs": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["name", "role", "description"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                    "motivation": {"type": "string"},
                    "location": {"type": ["string", "null"]},
                    "contact_cooldown_turns": {"type": "integer"},
                    "faction": {"type": ["string", "null"]},
                    "reputation": {"type": "integer"},
                },
            },
        },
        "factions": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["name", "description"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "initial_tension": {"type": "integer"},
                    "passive_gain_per_turn": {"type": "integer"},
                    "threshold_conflict": {"type": "integer"},
                },
            },
        },
        "events": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["name", "summary"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "location": {"type": ["string", "null"]},
                    "importance": {"type": "integer"},
                    "trigger_turn": {"type": ["integer", "null"]},
                    "initial_active": {"type": "boolean"},
                    "trigger": {"type": "object"},
                    "completion": {"type": "object"},
                },
            },
        },
        "location_links": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["from_location", "to_location"],
                "additionalProperties": False,
                "properties": {
                    "from_location": {"type": "string"},
                    "to_location": {"type": "string"},
                    "direction": {"type": "string"},
                    "travel_turns": {"type": "integer"},
                },
            },
        },
        "campaign": {
            "type": ["object", "null"],
            "properties": {
                "name": {"type": "string"},
                "phases": {"type": "array"},
            },
        },
    },
}


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
    api_key: str | None = Field(default=None, max_length=4000, exclude=True)

    @field_validator("base_url")
    @classmethod
    def remove_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def normalize_optional_api_key(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class ModelProfile(ModelProfileInput):
    id: str
    is_default: bool = False
    api_key_ref: str | None = Field(default=None, exclude=True)
    has_api_key: bool = False


class ProbeResult(BaseModel):
    success: bool
    endpoint: str
    detail: str


class NarrationError(ValueError):
    pass


class NarrationRateLimitError(NarrationError):
    pass


class ModelProfileConflictError(ValueError):
    pass


class ModelProfileService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_store: ModelSecretStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secret_store = secret_store or default_model_secret_store()

    async def create(self, payload: ModelProfileInput) -> ModelProfile:
        _chat_endpoint(payload)
        async with self._session_factory() as session, session.begin():
            count = (
                await session.execute(select(func.count()).select_from(model_profiles))
            ).scalar_one()
            profile_id = str(uuid4())
            api_key_ref = f"profile:{profile_id}" if payload.api_key else None
            if api_key_ref and payload.api_key:
                self._secret_store.set(api_key_ref, payload.api_key)
            try:
                profile = ModelProfile(
                    id=profile_id,
                    is_default=count == 0,
                    api_key_ref=api_key_ref,
                    has_api_key=api_key_ref is not None,
                    **payload.model_dump(),
                )
                await session.execute(
                    insert(model_profiles).values(
                        id=profile.id,
                        name=profile.name,
                        provider_type=profile.provider_type,
                        base_url=profile.base_url,
                        model_name=profile.model_name,
                        api_key_ref=api_key_ref,
                        is_default=profile.is_default,
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                    )
                )
            except Exception:
                if api_key_ref:
                    self._secret_store.delete(api_key_ref)
                raise
        return profile

    async def get(self, profile_id: str) -> ModelProfile | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(model_profiles).where(model_profiles.c.id == profile_id)
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        return ModelProfile(
            id=row["id"],
            name=row["name"],
            provider_type=row["provider_type"],
            base_url=row["base_url"],
            model_name=row["model_name"],
            is_default=bool(row["is_default"]),
            api_key_ref=row["api_key_ref"],
            has_api_key=row["api_key_ref"] is not None,
        )

    async def list(self) -> list[ModelProfile]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(model_profiles).order_by(model_profiles.c.created_at)
            )
            rows = result.mappings().all()
        return [
            ModelProfile(
                id=row["id"],
                name=row["name"],
                provider_type=row["provider_type"],
                base_url=row["base_url"],
                model_name=row["model_name"],
                is_default=bool(row["is_default"]),
                api_key_ref=row["api_key_ref"],
                has_api_key=row["api_key_ref"] is not None,
            )
            for row in rows
        ]

    async def update(self, profile_id: str, payload: ModelProfileInput) -> ModelProfile:
        _chat_endpoint(payload)
        async with self._session_factory() as session, session.begin():
            existing = (
                await session.execute(
                    select(model_profiles.c.api_key_ref).where(model_profiles.c.id == profile_id)
                )
            ).mappings().one_or_none()
            if existing is None:
                raise ModelProfileConflictError("model profile not found")
            api_key_ref = existing["api_key_ref"]
            if payload.api_key:
                api_key_ref = api_key_ref or f"profile:{profile_id}"
                self._secret_store.set(api_key_ref, payload.api_key)
            changed = await session.execute(
                update(model_profiles)
                .where(model_profiles.c.id == profile_id)
                .values(**payload.model_dump(), api_key_ref=api_key_ref)
            )
            if changed.rowcount != 1:
                raise ModelProfileConflictError("model profile not found")
        profile = await self.get(profile_id)
        assert profile is not None
        return profile

    async def set_default(self, profile_id: str) -> ModelProfile:
        async with self._session_factory() as session, session.begin():
            exists = await session.execute(
                select(model_profiles.c.id).where(model_profiles.c.id == profile_id)
            )
            if exists.scalar_one_or_none() is None:
                raise ModelProfileConflictError("model profile not found")
            await session.execute(update(model_profiles).values(is_default=False))
            await session.execute(
                update(model_profiles)
                .where(model_profiles.c.id == profile_id)
                .values(is_default=True)
            )
        profile = await self.get(profile_id)
        assert profile is not None
        return profile

    async def delete(self, profile_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            profile = (
                await session.execute(
                    select(model_profiles.c.is_default, model_profiles.c.api_key_ref).where(
                        model_profiles.c.id == profile_id
                    )
                )
            ).mappings().one_or_none()
            if profile is None:
                raise ModelProfileConflictError("model profile not found")
            was_default = profile["is_default"]
            references = (
                await session.execute(
                    select(func.count())
                    .select_from(runs)
                    .where(runs.c.model_profile_id == profile_id)
                )
            ).scalar_one()
            if references:
                raise ModelProfileConflictError(
                    f"model profile is used by {references} run(s); choose another model before deleting"
                )
            await session.execute(delete(model_profiles).where(model_profiles.c.id == profile_id))
            if profile["api_key_ref"]:
                self._secret_store.delete(profile["api_key_ref"])
            if was_default:
                replacement = await session.execute(
                    select(model_profiles.c.id)
                    .order_by(model_profiles.c.created_at, model_profiles.c.id)
                    .limit(1)
                )
                replacement_id = replacement.scalar_one_or_none()
                if replacement_id:
                    await session.execute(
                        update(model_profiles)
                        .where(model_profiles.c.id == replacement_id)
                        .values(is_default=True)
                    )


class ModelProber:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        secret_store: ModelSecretStore | None = None,
    ) -> None:
        self._transport = transport
        self._secret_store = secret_store or default_model_secret_store()

    async def probe(self, profile: ModelProfile) -> ProbeResult:
        endpoint = _chat_endpoint(profile)
        body = _probe_body(profile)
        try:
            headers = _request_headers(profile, self._secret_store)
            async with httpx.AsyncClient(
                transport=self._transport, timeout=PROBE_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(endpoint, json=body, headers=headers)
        except NarrationError as error:
            return ProbeResult(success=False, endpoint=endpoint, detail=str(error))
        except httpx.TimeoutException:
            return ProbeResult(
                success=False,
                endpoint=endpoint,
                detail=model_timeout_detail(PROBE_TIMEOUT_SECONDS),
            )
        except httpx.HTTPError:
            return ProbeResult(
                success=False, endpoint=endpoint, detail=model_connection_detail()
            )
        if response.status_code != 200:
            return ProbeResult(
                success=False,
                endpoint=endpoint,
                detail=f"provider returned HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError:
            return ProbeResult(
                success=False, endpoint=endpoint, detail="provider returned non-JSON response"
            )
        content = _chat_content(profile.provider_type, payload)
        if isinstance(content, str) and content.strip():
            return ProbeResult(
                success=True, endpoint=endpoint, detail="protocol response contains content"
            )
        return ProbeResult(
            success=False,
            endpoint=endpoint,
            detail="provider returned HTTP 200 but not a valid non-empty chat response",
        )


class ModelNarrator:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        secret_store: ModelSecretStore | None = None,
    ) -> None:
        self._transport = transport
        self._secret_store = secret_store or default_model_secret_store()

    async def narrate(
        self,
        profile: ModelProfile,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
        lore_entries: list[dict[str, Any]],
        *,
        variation_seed: str = "",
    ) -> str:
        narrative, _actions = await self.narrate_with_actions(
            profile,
            definition,
            state,
            player_input,
            outcomes,
            lore_entries,
            variation_seed=variation_seed,
        )
        return narrative

    async def narrate_with_actions(
        self,
        profile: ModelProfile,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
        lore_entries: list[dict[str, Any]],
        *,
        variation_seed: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        endpoint = _chat_endpoint(profile)
        body = _narration_body(
            profile, definition, state, player_input, outcomes, lore_entries,
            variation_seed=variation_seed,
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=NARRATION_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    endpoint, json=body, headers=_request_headers(profile, self._secret_store)
                )
        except httpx.HTTPError as error:
            raise _request_narration_error(error) from error
        if response.status_code != 200:
            raise NarrationError(
                f"model returned HTTP {response.status_code}: {_response_detail(response)}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise NarrationError("model returned non-JSON response") from error
        if model_response_was_truncated(profile.provider_type, payload):
            raise NarrationError("model narrative was truncated; retry the turn")
        content = _chat_content(profile.provider_type, payload)
        visible, actions = extract_gm_actions(content)
        narrative = _clean_narrative(visible)
        if not narrative:
            raise NarrationError("model returned no valid narrative content")
        return narrative, actions

    async def stream(
        self,
        profile: ModelProfile,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
        lore_entries: list[dict[str, Any]],
        *,
        variation_seed: str = "",
    ) -> AsyncIterator[str]:
        endpoint = _chat_endpoint(profile)
        body = _narration_body(
            profile,
            definition,
            state,
            player_input,
            outcomes,
            lore_entries,
            stream=True,
            variation_seed=variation_seed,
        )
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport, timeout=NARRATION_TIMEOUT_SECONDS
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    json=body,
                    headers=_request_headers(profile, self._secret_store),
                ) as response,
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
            raise _request_narration_error(error) from error


class ModelDraftGenerator:
    """Calls a configured local provider for non-persistent creative source material."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        secret_store: ModelSecretStore | None = None,
    ) -> None:
        self._transport = transport
        self._secret_store = secret_store or default_model_secret_store()

    async def generate(
        self, profile: ModelProfile, prompt: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        endpoint = _chat_endpoint(profile)
        body = _draft_body(profile, prompt)
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=NARRATION_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    endpoint, json=body, headers=_request_headers(profile, self._secret_store)
                )
        except httpx.HTTPError as error:
            raise _request_narration_error(error) from error
        if response.status_code != 200:
            raise NarrationError(
                f"model returned HTTP {response.status_code}: {_response_detail(response)}"
            )
        try:
            content = _chat_content(profile.provider_type, response.json())
        except ValueError as error:
            raise NarrationError("model returned non-JSON response") from error
        if not isinstance(content, str) or not content.strip():
            raise NarrationError("model returned no draft content")
        return _draft_json(content)


def _chat_endpoint(profile: ModelProfileInput) -> str:
    return chat_endpoint(profile.provider_type, profile.base_url)


def _request_narration_error(error: httpx.HTTPError) -> NarrationError:
    if isinstance(error, httpx.TimeoutException):
        return NarrationError(model_timeout_detail(NARRATION_TIMEOUT_SECONDS))
    return NarrationError(model_connection_detail())


def _request_headers(
    profile: ModelProfile, secret_store: ModelSecretStore
) -> dict[str, str] | None:
    if not profile.api_key_ref:
        return None
    api_key = secret_store.get(profile.api_key_ref)
    if not api_key:
        raise NarrationError("model credential is missing from operating-system secure storage")
    return {"Authorization": f"Bearer {api_key}"}


def _probe_body(profile: ModelProfile) -> dict[str, Any]:
    return probe_body(profile.provider_type, profile.model_name)


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
    variation_seed: str = "",
) -> dict[str, Any]:
    variation = narrative_variation(definition, state, variation_seed or "default-run")
    entity_names = narrative_entity_names(definition)
    world_material = narrative_world_material(definition)
    current_location = next(
        (
            str(item.get("name") or "").strip()
            for item in definition.get("locations") or []
            if isinstance(item, dict) and str(item.get("id")) == str(state.get("location_id"))
        ),
        "",
    )
    choice_context: list[dict[str, str]] = []
    story = definition.get("story")
    if isinstance(story, dict) and isinstance(story.get("chapters"), list):
        try:
            choice_context = available_choices(state, definition)
        except KeyError:
            # The narrator also has a lightweight seam in unit tests and for
            # partially imported content; omit optional choice context there.
            choice_context = []
    selected_choice: dict[str, str] | None = None
    selected_choice_id = next(
        (
            item.get("choice_id")
            for item in outcomes
            if item.get("type") == "choose_story_choice" and isinstance(item.get("choice_id"), str)
        ),
        None,
    )
    if selected_choice_id:
        selected_choice = next(
            (choice for choice in choice_context if choice["id"] == selected_choice_id),
            {"id": selected_choice_id, "label": selected_choice_id},
        )
    messages = [
        {
            "role": "system",
            "content": NARRATIVE_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": "/no_think\n"
            + json.dumps(
                {
                    "world": definition["name"],
                    "hero": state["hero"]["name"],
                    "location_id": state["location_id"],
                    "current_location": current_location,
                    "ruleset": state.get("ruleset", {}).get("id"),
                    "chapter": state.get("chapter"),
                    "route": state.get("route"),
                    "relationships": state.get("relationships", {}),
                    "ending": state.get("ending"),
                    "player_input": player_input,
                    "validated_outcomes": outcomes,
                    "narrative_memory": state.get("narrative_context", {}).get("recent_turns", []),
                    "variation_directive": variation,
                    "npc_state": state.get("npc_state", {}),
                    "faction_state": state.get("faction_state", {}),
                    "campaign_state": state.get("campaign_state"),
                    "location_state": state.get("location_state", {}),
                    "active_events": state.get("active_events", []),
                    "plot_threads": state.get("plot_threads", []),
                    "pending_interactions": state.get("pending_interactions", []),
                    "available_choices": choice_context,
                    "selected_choice": selected_choice,
                    "world_entity_names": entity_names,
                    "world_material": world_material,
                    "narrative_guardrails": (
                        "叙事只能使用 world_entity_names 中的角色、NPC、地点、势力和事件名称；"
                        "world_material 只用于理解这些实体的动机和背景；"
                        "不要创造未列出的姓名，也不要把内部 ID、模板旧名或关系 ID 写进正文；"
                        "本回合必须围绕 current_location 对应地点展开，除非 validated_outcomes 明确移动，"
                        "不得凭空切换到未列出的地点或使用与当前地点冲突的空间描述。"
                    ),
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
            "options": {
                "temperature": 0.85,
                "top_p": 0.9,
                "num_predict": NARRATIVE_OLLAMA_NUM_PREDICT,
            },
        }
    body: dict[str, Any] = {
        "model": profile.model_name,
        "messages": messages,
        "stream": stream,
        "max_tokens": (
            NARRATIVE_LM_STUDIO_MAX_TOKENS
            if profile.provider_type is ProviderType.LM_STUDIO
            else NARRATIVE_OPENAI_MAX_TOKENS
        ),
        "temperature": 0.85,
        "top_p": 0.9,
    }
    if profile.provider_type is ProviderType.LM_STUDIO and "qwen" in profile.model_name.lower():
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def _draft_body(profile: ModelProfile, prompt: dict[str, Any]) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": prompt["system"]},
        {
            "role": "user",
            "content": "/no_think\n"
            + json.dumps(
                {"brief": prompt["brief"], "first_slice": prompt["first_slice"]}, ensure_ascii=False
            ),
        },
    ]
    if profile.provider_type is ProviderType.OLLAMA:
        return {
            "model": profile.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"num_predict": 1800},
        }
    body: dict[str, Any] = {
        "model": profile.model_name,
        "messages": messages,
        "stream": False,
        "max_tokens": DRAFT_OPENAI_MAX_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }
    if profile.provider_type is ProviderType.OPENAI_COMPAT:
        body["response_format"] = {"type": "json_object"}
    if profile.provider_type is ProviderType.LM_STUDIO:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "dzmm_creative_source",
                "strict": True,
                "schema": CREATIVE_SOURCE_SCHEMA,
            },
        }
        if "qwen" in profile.model_name.lower():
            body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def _draft_json(content: str) -> tuple[dict[str, Any], list[str]]:
    value = content.strip()
    repairs: list[str] = []
    if "</think>" in value:
        value = value.split("</think>", maxsplit=1)[1].strip()
        repairs.append("removed model thinking wrapper")
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()
        repairs.append("removed Markdown code fence")
    # Some local instruct models emit non-breaking/full-width spaces around
    # JSON punctuation. Normalize whitespace only; keys and values remain
    # untouched and are still validated by CreativeSource afterwards.
    normalized = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", value)
    if normalized != value:
        value = normalized
        repairs.append("normalized non-standard JSON whitespace")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        # Small local models often append an explanation after an otherwise
        # valid JSON object. Decode only the first complete object; do not
        # evaluate or repair arbitrary prose as JSON.
        decoder = json.JSONDecoder()
        candidates: list[tuple[dict[str, Any], int, int]] = []
        for start, char in enumerate(value):
            if char != "{":
                continue
            try:
                candidate, end = decoder.raw_decode(value[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                candidates.append((candidate, start, end))
        if not candidates:
            raise NarrationError(f"model draft is not a single JSON object: {error.msg}") from error
        # Prefer the object that looks like a complete creative source over a
        # leading hero/field fragment some models emit before their answer.
        preferred_keys = {
            "world_name",
            "summary",
            "locations",
            "characters",
            "lore",
            "npcs",
            "factions",
            "events",
            "world_definition",
        }
        payload, start, end = max(
            candidates,
            key=lambda item: (len(preferred_keys.intersection(item[0])), -item[1]),
        )
        if value[start + end :].strip():
            repairs.append("trimmed trailing model commentary")
    if not isinstance(payload, dict):
        raise NarrationError("model draft must be a JSON object")
    return payload, repairs


def _clean_narrative(content: str | None) -> str | None:
    return clean_narrative_output(content)


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
        if model_response_was_truncated(provider_type, payload):
            raise NarrationError("model narrative was truncated; retry the turn")
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
    if model_response_was_truncated(provider_type, payload):
        raise NarrationError("model narrative was truncated; retry the turn")
    delta = choices[0].get("delta")
    content = delta.get("content") if isinstance(delta, dict) else None
    if content is not None and not isinstance(content, str):
        raise NarrationError("model returned malformed SSE content")
    return content, False

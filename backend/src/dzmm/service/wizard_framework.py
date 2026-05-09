"""Open-world Wizard service — generates WorldFramework layer-by-layer.

Each function takes a ModelClient + context and returns parsed Python objects.
finalize_framework() commits everything to DB atomically.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.wizard_locations import build_locations_messages

log = logging.getLogger(__name__)

_PARAMS = GenerationParams(temperature=0.7, max_tokens=4096)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _extract_json(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    obj = text.find("{")
    arr = text.find("[")
    if arr != -1 and (obj == -1 or arr < obj):
        end = text.rfind("]")
        if end != -1:
            text = text[arr:end+1]
    elif obj != -1:
        end = text.rfind("}")
        if end != -1:
            text = text[obj:end+1]
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


async def generate_locations(
    genre: str, world_brief_md: str, client: ModelClient
) -> list[dict]:
    msgs = build_locations_messages(genre, world_brief_md)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))

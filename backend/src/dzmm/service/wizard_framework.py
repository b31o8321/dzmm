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
from dzmm.prompts.wizard_factions_fw import build_factions_messages
from dzmm.prompts.wizard_npc_templates import build_npc_templates_messages
from dzmm.prompts.wizard_events_fw import build_events_messages
from dzmm.prompts.wizard_campaign_fw import build_campaign_messages
from dzmm.db.models import (
    WorldFramework,
    WorldLocation,
    WorldFaction,
    WorldNPCTemplate,
    WorldEvent,
    Campaign,
)

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


async def generate_factions(
    genre: str, world_brief_md: str, locations: list[dict], client: ModelClient
) -> list[dict]:
    location_names = [l["name"] for l in locations]
    msgs = build_factions_messages(genre, world_brief_md, location_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_npc_templates(
    genre: str, world_brief_md: str, locations: list[dict],
    factions: list[dict], client: ModelClient,
) -> list[dict]:
    location_names = [l["name"] for l in locations]
    faction_names = [f["name"] for f in factions]
    msgs = build_npc_templates_messages(genre, world_brief_md, location_names, faction_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_events(
    genre: str, world_brief_md: str, locations: list[dict],
    factions: list[dict], npc_templates: list[dict], client: ModelClient,
) -> list[dict]:
    location_names = [l["name"] for l in locations]
    faction_names = [f["name"] for f in factions]
    npc_names = [n["name"] for n in npc_templates]
    msgs = build_events_messages(genre, world_brief_md, location_names, faction_names, npc_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_campaign(
    genre: str, world_brief_md: str, events: list[dict], client: ModelClient
) -> dict:
    event_summaries = [{"name": e["name"], "importance": e.get("importance", 2)} for e in events]
    msgs = build_campaign_messages(genre, world_brief_md, event_summaries)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def finalize_framework(s: AsyncSession, payload: dict) -> int:
    """Atomically create WorldFramework and all child records from wizard payload.

    Returns the new WorldFramework.id.
    Names in connections/scope/home_location/faction are resolved to IDs after insert.
    """
    fw = WorldFramework(
        name=payload["name"],
        genre=payload.get("genre", ""),
        style=payload.get("style", ""),
        description_md=payload.get("description_md", ""),
    )
    s.add(fw)
    await s.flush()  # assign fw.id

    # --- Locations (first pass, no connections yet) ---
    loc_name_to_id: dict[str, int] = {}
    loc_rows: list[WorldLocation] = []
    for loc_data in payload.get("locations", []):
        loc = WorldLocation(
            framework_id=fw.id,
            name=loc_data["name"],
            description_md=loc_data.get("description_md", ""),
            location_type=loc_data.get("location_type", "city"),
            connections_json="[]",
            initial_state=loc_data.get("initial_state", "normal"),
        )
        s.add(loc)
        loc_rows.append(loc)
    await s.flush()
    for loc, loc_data in zip(loc_rows, payload.get("locations", [])):
        loc_name_to_id[loc.name] = loc.id

    # Second pass: wire up connections_json with resolved IDs
    for loc, loc_data in zip(loc_rows, payload.get("locations", [])):
        resolved = []
        for conn in loc_data.get("connections", []):
            target_id = loc_name_to_id.get(conn.get("target_name", ""))
            if target_id:
                resolved.append({
                    "target_id": target_id,
                    "direction": conn.get("direction", ""),
                    "distance": conn.get("distance", 1),
                    "travel_turns": conn.get("travel_turns", 1),
                })
        loc.connections_json = json.dumps(resolved, ensure_ascii=False)

    # --- Factions ---
    faction_name_to_id: dict[str, int] = {}
    for f_data in payload.get("factions", []):
        faction = WorldFaction(
            framework_id=fw.id,
            name=f_data["name"],
            description_md=f_data.get("description_md", ""),
            rival_factions_json=json.dumps(f_data.get("rival_faction_names", []), ensure_ascii=False),
            ally_factions_json=json.dumps(f_data.get("ally_faction_names", []), ensure_ascii=False),
            tension_rules_json=json.dumps(f_data.get("tension_rules", {}), ensure_ascii=False),
        )
        s.add(faction)
        await s.flush()
        faction_name_to_id[faction.name] = faction.id

    # --- NPC Templates ---
    npc_name_to_id: dict[str, int] = {}
    for n_data in payload.get("npc_templates", []):
        home_id = loc_name_to_id.get(n_data.get("home_location_name", ""))
        faction_id = faction_name_to_id.get(n_data.get("faction_name", ""))
        npc = WorldNPCTemplate(
            framework_id=fw.id,
            name=n_data["name"],
            gender=n_data.get("gender", ""),
            role=n_data.get("role", ""),
            description_md=n_data.get("description_md", ""),
            motivation=n_data.get("motivation", ""),
            home_location_id=home_id,
            faction_id=faction_id,
            contact_favor_threshold=n_data.get("contact_favor_threshold", 70),
            contact_cooldown_turns=n_data.get("contact_cooldown_turns", 10),
        )
        s.add(npc)
        await s.flush()
        npc_name_to_id[npc.name] = npc.id

    # --- Events (resolve name refs to IDs in trigger_conditions) ---
    event_name_to_id: dict[str, int] = {}
    for e_data in payload.get("events", []):
        scope_ref = ""
        if e_data.get("scope_type") == "location":
            scope_ref = str(loc_name_to_id.get(e_data.get("scope_location_name", ""), ""))
        elif e_data.get("scope_type") == "faction":
            scope_ref = str(faction_name_to_id.get(e_data.get("scope_faction_name", ""), ""))

        # Resolve trigger_conditions name refs → IDs
        conds = []
        for cond in e_data.get("trigger_conditions", []):
            resolved_cond = dict(cond)
            if cond.get("type") == "location" and "location_name" in cond:
                resolved_cond["value"] = loc_name_to_id.get(cond["location_name"], 0)
                del resolved_cond["location_name"]
            elif cond.get("type") == "npc_met" and "npc_name" in cond:
                resolved_cond["value"] = npc_name_to_id.get(cond["npc_name"], 0)
                del resolved_cond["npc_name"]
            elif cond.get("type") == "faction_rep" and "faction_name" in cond:
                resolved_cond["faction_id"] = faction_name_to_id.get(cond["faction_name"], 0)
                del resolved_cond["faction_name"]
            conds.append(resolved_cond)

        event = WorldEvent(
            framework_id=fw.id,
            name=e_data["name"],
            summary_md=e_data.get("summary_md", ""),
            scope_type=e_data.get("scope_type", "global"),
            scope_ref=scope_ref,
            importance=e_data.get("importance", 2),
            trigger_conditions_json=json.dumps(conds, ensure_ascii=False),
            is_repeatable=e_data.get("is_repeatable", False),
            cooldown_turns=e_data.get("cooldown_turns", 0),
        )
        s.add(event)
        await s.flush()
        event_name_to_id[event.name] = event.id

    # --- Campaign (optional) ---
    campaign_data = payload.get("campaign")
    if campaign_data:
        phases = []
        for ph in campaign_data.get("phases", []):
            key_ids = [event_name_to_id[n] for n in ph.get("key_event_names", []) if n in event_name_to_id]
            phases.append({
                "phase_id": ph["phase_id"],
                "name": ph["name"],
                "description": ph.get("description", ""),
                "prerequisite_phase_ids": ph.get("prerequisite_phase_ids", []),
                "key_event_ids": key_ids,
                "required_count": ph.get("required_count", 1),
            })
        campaign = Campaign(
            framework_id=fw.id,
            name=campaign_data["name"],
            phases_json=json.dumps(phases, ensure_ascii=False),
        )
        s.add(campaign)

    await s.commit()
    return fw.id

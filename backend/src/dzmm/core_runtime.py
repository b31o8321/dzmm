"""Small transport-free Local Host runtime used by embedded hosts.

This module deliberately depends only on the Python standard library plus the
pure narrative/command modules. Desktop's SQLAlchemy/FastAPI adapter and
Android's Chaquopy bridge can both call the same state-jury operations.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from secrets import token_hex
from typing import Any
from uuid import uuid4

from .core.command_engine import apply_commands
from .core_runtime_errors import CoreRuntimeError
from .director import build_director_prompt, is_note_fresh, parse_director_note, should_run_director
from .embedded_model_profiles import EmbeddedModelProfileStore
from .embedded_model_requests import (
    clean_model_narrative,
    request_director_note,
    request_narrative,
    request_world_draft,
    strip_json_fence,
)
from .generated_world_repair import map_to_safe_story_skeleton, repair_generated_definition
from .model_protocol import chat_content
from .narrative import (
    NarrativeRuleError,
    advance_world_events,
    apply_gm_actions,
    available_choices,
    initial_state,
    narrative_variation,
    planned_choice_commands,
    record_narrative_context,
    schedule_npc_initiative,
    settle_pending_interactions,
    settle_world_events,
    validate_definition,
)
from .narrative_context import narrative_entity_names, narrative_world_material
from .narrative_output import extract_gm_actions, model_response_was_truncated
from .operation_control import OperationRegistry
from .run_presentation import build_run_presentation
from .story_beats import (
    build_deterministic_narrative,
    build_opening_story_beat,
    build_turn_story_beat,
)
from .world_templates import fog_harbor_template

logger = logging.getLogger(__name__)

_narrative_entity_names = narrative_entity_names
_narrative_world_material = narrative_world_material


def _narrative_memory_layers(
    definition: dict[str, Any], state: dict[str, Any], player_input: str
) -> dict[str, Any]:
    """Build bounded, player-safe memory layers for the next GM turn."""

    location_names = {
        str(item.get("id")): str(item.get("name") or "")
        for item in definition.get("locations") or []
        if isinstance(item, dict) and item.get("id")
    }
    current_location = location_names.get(str(state.get("location_id")), "")
    npc_names = [
        str(item.get("name") or "")
        for item in (definition.get("npcs") or []) + (definition.get("character_cards") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    active_threads = [
        str(item.get("description") or "")
        for item in state.get("plot_threads") or []
        if item.get("status") == "active" and str(item.get("description") or "").strip()
    ]
    active_events = [
        str(item.get("description") or item.get("name") or "")
        for item in state.get("active_events") or []
        if item.get("status") == "active" and str(item.get("description") or item.get("name") or "").strip()
    ]
    search_text = " ".join(
        [player_input, current_location, *npc_names, *active_threads, *active_events]
    ).lower()
    worldbook: list[dict[str, str]] = []
    for entry in (definition.get("lorebook") or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("id") or "").strip()
        body = str(entry.get("body") or entry.get("content") or "").strip()
        keys = entry.get("keys") or entry.get("key") or [title]
        if isinstance(keys, str):
            keys = [keys]
        if not title or not body:
            continue
        if str(entry.get("activation") or "").lower() == "always" or any(
            str(key).strip().lower() in search_text for key in keys if str(key).strip()
        ):
            worldbook.append({"title": title, "body": body})
        if len(worldbook) >= 4:
            break
    recent_turns = []
    for item in (state.get("narrative_context") or {}).get("recent_turns") or []:
        if not isinstance(item, dict):
            continue
        recent_turns.append(
            {
                "turn": item.get("turn"),
                "player_input": str(item.get("player_input") or "")[:240],
                "narrative": str(item.get("narrative") or "")[:600],
                "outcomes": _narrative_outcome_context(definition, item.get("outcomes") or [])[:6],
            }
        )
    recent_turns = recent_turns[-6:]
    summary = "；".join(
        f"第{item['turn']}回合：{item['player_input']}"
        for item in recent_turns[-4:]
        if item.get("player_input")
    )
    return {
        "summary": summary,
        "recent_turns": recent_turns,
        "open_threads": active_threads[:6],
        "active_events": active_events[:6],
        "worldbook": worldbook,
    }


def _narrative_chapter_context(
    definition: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    current = dict(state.get("chapter") or {})
    chapter_id = current.get("id")
    chapters = (definition.get("story") or {}).get("chapters") or []
    chapter = next(
        (item for item in chapters if isinstance(item, dict) and item.get("id") == chapter_id),
        None,
    )
    if not isinstance(chapter, dict):
        return current
    current["title"] = chapter.get("title")
    current["choices"] = [
        {"label": str(choice.get("label") or "")}
        for choice in chapter.get("choices") or []
        if isinstance(choice, dict) and str(choice.get("label") or "").strip()
    ]
    return current


def _narrative_outcome_context(
    definition: dict[str, Any], outcomes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    characters = {
        item.get("id"): item.get("name")
        for item in definition.get("character_cards") or []
        if isinstance(item, dict)
    }
    routes = {
        item.get("id"): item.get("name")
        for item in ((definition.get("story") or {}).get("routes") or [])
        if isinstance(item, dict)
    }
    chapters = {
        item.get("id"): item.get("title")
        for item in ((definition.get("story") or {}).get("chapters") or [])
        if isinstance(item, dict)
    }
    choices = {
        choice.get("id"): choice.get("label")
        for chapter in ((definition.get("story") or {}).get("chapters") or [])
        if isinstance(chapter, dict)
        for choice in chapter.get("choices") or []
        if isinstance(choice, dict)
    }
    resources = {
        item.get("id"): item.get("name")
        for item in definition.get("resources") or []
        if isinstance(item, dict)
    }
    result: list[dict[str, Any]] = []
    for outcome in outcomes:
        item = {"type": outcome.get("type")}
        for key, mapping in (
            ("choice_id", choices),
            ("relationship_id", characters),
            ("route_id", routes),
            ("chapter_id", chapters),
            ("next_chapter_id", chapters),
            ("resource_id", resources),
        ):
            value = outcome.get(key)
            if value in mapping:
                item[key.removesuffix("_id") + "_name"] = mapping[value]
        for key in ("npc_name", "deltas", "quantity", "kind", "status", "id"):
            if key in outcome and key != "id":
                item[key] = outcome[key]
        result.append(item)
    return result


class LocalCoreRuntime:
    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self._operations = OperationRegistry()
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._model_profiles = EmbeddedModelProfileStore(self._connect)

    def begin_operation(self, request_id: str) -> bool:
        return self._operations.begin(request_id)

    def cancel_operation(self, request_id: str) -> bool:
        return self._operations.cancel(request_id)

    def finish_operation(self, request_id: str) -> None:
        self._operations.finish(request_id)

    def ensure_operation_can_complete(self, request_id: str) -> None:
        if not self._operations.enter_applying(request_id):
            raise CoreRuntimeError("operation cancelled; draft was discarded")

    def _require_apply_permission(self, request_id: str) -> None:
        if not self._operations.enter_applying(request_id):
            raise CoreRuntimeError("operation cancelled; original Run state was not changed")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS local_worlds (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS local_world_versions (
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL REFERENCES local_worlds(id) ON DELETE CASCADE,
                    version_number INTEGER NOT NULL,
                    definition TEXT NOT NULL,
                    UNIQUE(world_id, version_number)
                );
                CREATE TABLE IF NOT EXISTS local_heroes (
                    id TEXT PRIMARY KEY,
                    world_version_id TEXT NOT NULL REFERENCES local_world_versions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    profile TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_runs (
                    id TEXT PRIMARY KEY,
                    world_version_id TEXT NOT NULL REFERENCES local_world_versions(id) ON DELETE RESTRICT,
                    hero_id TEXT NOT NULL REFERENCES local_heroes(id) ON DELETE RESTRICT,
                    model_profile_id TEXT,
                    state TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS local_story_beats (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES local_runs(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS director_notes (
                    run_id TEXT NOT NULL,
                    turn INTEGER NOT NULL,
                    tension TEXT NOT NULL,
                    hook TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (run_id, turn)
                );
                CREATE TABLE IF NOT EXISTS local_turns (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES local_runs(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'turn',
                    sequence INTEGER NOT NULL,
                    player_input TEXT NOT NULL,
                    narrative TEXT NOT NULL,
                    commands TEXT NOT NULL,
                    outcomes TEXT NOT NULL,
                    after_state TEXT NOT NULL,
                    UNIQUE(run_id, request_id),
                    UNIQUE(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS local_model_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider_type TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    has_api_key INTEGER NOT NULL DEFAULT 0,
                    is_default INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS local_run_create_requests (
                    request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    world_id TEXT NOT NULL REFERENCES local_worlds(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES local_runs(id) ON DELETE CASCADE
                );
                """
            )
            world_columns = {row[1] for row in connection.execute("PRAGMA table_info(local_worlds)")}
            if "status" not in world_columns:
                connection.execute(
                    "ALTER TABLE local_worlds ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
                )
            run_columns = {row[1] for row in connection.execute("PRAGMA table_info(local_runs)")}
            if "model_profile_id" not in run_columns:
                connection.execute("ALTER TABLE local_runs ADD COLUMN model_profile_id TEXT")
            if "status" not in run_columns:
                connection.execute(
                    "ALTER TABLE local_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
                )
            turn_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(local_turns)")
            }
            if "kind" not in turn_columns:
                connection.execute(
                    "ALTER TABLE local_turns ADD COLUMN kind TEXT NOT NULL DEFAULT 'turn'"
                )
                for turn in connection.execute("SELECT id, outcomes FROM local_turns"):
                    try:
                        outcomes = json.loads(turn["outcomes"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if any(
                        isinstance(outcome, dict) and outcome.get("type") == "rollback"
                        for outcome in outcomes
                    ):
                        connection.execute(
                            "UPDATE local_turns SET kind = 'rollback' WHERE id = ?",
                            (turn["id"],),
                        )
            profile_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(local_model_profiles)")
            }
            if "is_default" not in profile_columns:
                connection.execute(
                    "ALTER TABLE local_model_profiles ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0"
                )
            if "has_api_key" not in profile_columns:
                connection.execute(
                    "ALTER TABLE local_model_profiles ADD COLUMN has_api_key INTEGER NOT NULL DEFAULT 0"
                )
            has_default = connection.execute(
                "SELECT 1 FROM local_model_profiles WHERE is_default = 1 LIMIT 1"
            ).fetchone()
            if has_default is None:
                connection.execute(
                    "UPDATE local_model_profiles SET is_default = 1 WHERE id = "
                    "(SELECT id FROM local_model_profiles ORDER BY rowid LIMIT 1)"
                )

    def health(self) -> dict[str, Any]:
        self._ensure_schema()
        return {
            "runtime": "embedded_cpython",
            "storage": "app_private_sqlite",
            "database": self.database,
        }

    def list_worlds(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT worlds.id, worlds.name, worlds.status, COUNT(runs.id) AS run_count,
                       (
                           SELECT recent.id
                           FROM local_runs AS recent
                           JOIN local_world_versions AS recent_version
                             ON recent_version.id = recent.world_version_id
                           WHERE recent_version.world_id = worlds.id
                           ORDER BY recent.rowid DESC
                           LIMIT 1
                       ) AS latest_run_id
                FROM local_worlds AS worlds
                LEFT JOIN local_world_versions AS versions ON versions.world_id = worlds.id
                LEFT JOIN local_runs AS runs ON runs.world_version_id = versions.id
                GROUP BY worlds.id, worlds.name
                ORDER BY worlds.rowid DESC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "run_count": row["run_count"],
                "latest_run_id": row["latest_run_id"],
            }
            for row in rows
        ]

    def get_world(self, world_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            world = connection.execute(
                """
                SELECT worlds.id, worlds.name, worlds.status, versions.id AS world_version_id,
                       versions.version_number, versions.definition
                FROM local_worlds AS worlds
                JOIN local_world_versions AS versions ON versions.world_id = worlds.id
                WHERE worlds.id = ?
                ORDER BY versions.version_number DESC
                LIMIT 1
                """,
                (world_id,),
            ).fetchone()
            run_rows = connection.execute(
                """
                SELECT runs.id, runs.revision, runs.status, heroes.name AS hero_name,
                       runs.model_profile_id
                FROM local_runs AS runs
                JOIN local_world_versions AS versions ON versions.id = runs.world_version_id
                JOIN local_heroes AS heroes ON heroes.id = runs.hero_id
                WHERE versions.world_id = ?
                ORDER BY runs.rowid DESC
                """,
                (world_id,),
            ).fetchall()
        if world is None:
            raise CoreRuntimeError("world not found")
        return {
            "id": world["id"],
            "name": world["name"],
            "status": world["status"],
            "latest_world_version_id": world["world_version_id"],
            "latest_version_number": world["version_number"],
            "definition": json.loads(world["definition"]),
            "runs": [dict(row) for row in run_rows],
        }

    def list_model_profiles(self) -> list[dict[str, Any]]:
        return self._model_profiles.list()

    def create_model_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._model_profiles.create(payload)

    def update_model_profile(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._model_profiles.update(profile_id, payload)

    def set_default_model_profile(self, profile_id: str) -> dict[str, Any]:
        return self._model_profiles.set_default(profile_id)

    def delete_model_profile(self, profile_id: str) -> None:
        self._model_profiles.delete(profile_id)

    def probe_model_profile(
        self, profile_id: str, api_key: str | None = None
    ) -> dict[str, Any]:
        return self._model_profiles.probe(profile_id, api_key)

    def compose(self, payload: dict[str, Any]) -> dict[str, Any]:
        definition = payload.get("world_definition")
        hero = payload.get("hero")
        if not isinstance(definition, dict) or not isinstance(hero, dict):
            raise CoreRuntimeError("compose requires world_definition and hero objects")
        self.validate(definition, hero)
        world_id = str(uuid4())
        world_version_id = str(uuid4())
        with self._connect() as connection:
            profile_id = payload.get("model_profile_id")
            if (
                profile_id
                and connection.execute(
                    "SELECT id FROM local_model_profiles WHERE id = ?", (str(profile_id),)
                ).fetchone()
                is None
            ):
                raise CoreRuntimeError("model profile not found")
            connection.execute(
                "INSERT INTO local_worlds(id, name) VALUES (?, ?)",
                (world_id, definition["name"]),
            )
            connection.execute(
                "INSERT INTO local_world_versions(id, world_id, version_number, definition) VALUES (?, ?, ?, ?)",
                (world_version_id, world_id, 1, _dump(definition)),
            )
            hero_id, run_id, state, opening = self._insert_run(
                connection,
                world_version_id=world_version_id,
                definition=definition,
                hero=hero,
                model_profile_id=str(profile_id) if profile_id else None,
            )
        return {
            "world_id": world_id,
            "world_version_id": world_version_id,
            "hero_id": hero_id,
            "run_id": run_id,
            "state": state,
            "opening": opening,
        }

    def create_run(self, world_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        hero = payload.get("hero")
        if not isinstance(hero, dict) or not str(hero.get("name") or "").strip():
            raise CoreRuntimeError("create_run requires hero.name")
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise CoreRuntimeError("create_run requires request_id")
        fingerprint = _fingerprint({"world_id": world_id, **payload})
        with self._connect() as connection:
            request = connection.execute(
                "SELECT * FROM local_run_create_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if request is not None:
                if request["fingerprint"] != fingerprint:
                    raise CoreRuntimeError("request_id was already used for different run input")
                run = self.get_run(request["run_id"])
                return {**run, "created": False, "opening": run["story_beats"][0]}

            query = """
                SELECT versions.id, versions.definition, worlds.status
                FROM local_world_versions AS versions
                JOIN local_worlds AS worlds ON worlds.id = versions.world_id
                WHERE worlds.id = ?
            """
            arguments: list[Any] = [world_id]
            if payload.get("world_version_id"):
                query += " AND versions.id = ?"
                arguments.append(str(payload["world_version_id"]))
            query += " ORDER BY versions.version_number DESC LIMIT 1"
            version = connection.execute(query, arguments).fetchone()
            if version is None:
                raise CoreRuntimeError("world or world version not found")
            if version["status"] != "active":
                raise CoreRuntimeError("archived world cannot start a new run")
            profile_id = payload.get("model_profile_id")
            if (
                profile_id
                and connection.execute(
                    "SELECT id FROM local_model_profiles WHERE id = ?", (str(profile_id),)
                ).fetchone()
                is None
            ):
                raise CoreRuntimeError("model profile not found")
            hero_id, run_id, state, opening = self._insert_run(
                connection,
                world_version_id=version["id"],
                definition=json.loads(version["definition"]),
                hero=hero,
                model_profile_id=str(profile_id) if profile_id else None,
            )
            connection.execute(
                "INSERT INTO local_run_create_requests(request_id, fingerprint, world_id, run_id) VALUES (?, ?, ?, ?)",
                (request_id, fingerprint, world_id, run_id),
            )
        return {
            "world_id": world_id,
            "world_version_id": version["id"],
            "hero_id": hero_id,
            "run_id": run_id,
            "state": state,
            "opening": opening,
            "created": True,
        }

    def archive_world(self, world_id: str) -> dict[str, str]:
        return self._set_world_status(world_id, "archived")

    def restore_world(self, world_id: str) -> dict[str, str]:
        return self._set_world_status(world_id, "active")

    def delete_world(self, world_id: str) -> dict[str, Any]:
        """Permanently remove a world and every locally stored Run beneath it."""

        with self._connect() as connection:
            world = connection.execute(
                "SELECT name FROM local_worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise CoreRuntimeError("world not found")
            version_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM local_world_versions WHERE world_id = ?", (world_id,)
                ).fetchall()
            ]
            run_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM local_runs WHERE world_version_id IN "
                    "(SELECT id FROM local_world_versions WHERE world_id = ?)",
                    (world_id,),
                ).fetchall()
            ]
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                connection.execute(
                    f"DELETE FROM local_story_beats WHERE run_id IN ({placeholders})", run_ids
                )
                connection.execute(
                    f"DELETE FROM local_turns WHERE run_id IN ({placeholders})", run_ids
                )
                connection.execute(
                    f"DELETE FROM local_run_create_requests WHERE run_id IN ({placeholders})",
                    run_ids,
                )
                connection.execute(
                    f"DELETE FROM local_runs WHERE id IN ({placeholders})", run_ids
                )
            if version_ids:
                placeholders = ",".join("?" for _ in version_ids)
                connection.execute(
                    f"DELETE FROM local_heroes WHERE world_version_id IN ({placeholders})",
                    version_ids,
                )
                connection.execute(
                    f"DELETE FROM local_world_versions WHERE id IN ({placeholders})",
                    version_ids,
                )
            connection.execute("DELETE FROM local_worlds WHERE id = ?", (world_id,))
        return {
            "world_id": world_id,
            "world_name": world["name"],
            "deleted_runs": len(run_ids),
        }

    def _set_world_status(self, world_id: str, status: str) -> dict[str, str]:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE local_worlds SET status = ? WHERE id = ?", (status, world_id)
            ).rowcount
        if changed != 1:
            raise CoreRuntimeError("world not found")
        return {"world_id": world_id, "status": status}

    def _ensure_active_world_for_run(self, run_id: str, action: str) -> None:
        with self._connect() as connection:
            status = connection.execute(
                """
                SELECT worlds.status
                FROM local_runs AS runs
                JOIN local_world_versions AS versions ON versions.id = runs.world_version_id
                JOIN local_worlds AS worlds ON worlds.id = versions.world_id
                WHERE runs.id = ?
                """,
                (run_id,),
            ).fetchone()
        if status is None:
            raise CoreRuntimeError("run not found")
        if status["status"] != "active":
            raise CoreRuntimeError(f"archived world cannot {action}")

    def _insert_run(
        self,
        connection: sqlite3.Connection,
        *,
        world_version_id: str,
        definition: dict[str, Any],
        hero: dict[str, Any],
        model_profile_id: str | None,
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        hero_id, run_id = str(uuid4()), str(uuid4())
        hero_value = {
            "id": hero_id,
            "name": str(hero.get("name") or "旅行者"),
            "profile": hero.get("profile") or {},
        }
        state = initial_state(definition, hero_value)
        opening = build_opening_story_beat(definition, hero_value)
        connection.execute(
            "INSERT INTO local_heroes(id, world_version_id, name, profile) VALUES (?, ?, ?, ?)",
            (hero_id, world_version_id, hero_value["name"], _dump(hero_value["profile"])),
        )
        connection.execute(
            "INSERT INTO local_runs"
            "(id, world_version_id, hero_id, model_profile_id, state, revision, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, world_version_id, hero_id, model_profile_id, _dump(state), 0, "active"),
        )
        connection.execute(
            "INSERT INTO local_story_beats(id, run_id, kind, sequence, content) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), run_id, "opening", 0, _dump(opening)),
        )
        return hero_id, run_id, state, opening

    def generate_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = payload.get("model_profile_id")
        if not profile_id:
            template = fog_harbor_template()
            definition = dict(template["world_definition"])
            definition["name"] = str(payload.get("genre") or definition["name"])
            return {
                "valid": True,
                "summary": "本机模板是固定的雾港示例，仅用于离线验证游玩流程；它不会根据上面的题材生成新世界。",
                "world_definition": definition,
                "hero": template["hero"],
                "repairs": [],
                "issues": [],
            }
        with self._connect() as connection:
            profile = connection.execute(
                "SELECT * FROM local_model_profiles WHERE id = ?", (str(profile_id),)
            ).fetchone()
        if profile is None:
            raise CoreRuntimeError("model profile not found")
        is_compact_qwen = (
            str(profile["provider_type"]).lower() == "ollama"
            and "qwen" in str(profile["model_name"]).lower()
        )
        instruction = (
            "Return one compact JSON object with world_definition and hero only; no markdown or commentary. "
            "world_definition must contain name, story with at least one chapter, character_cards and locations. "
            "You may add short lorebook, npcs, factions and events arrays; keep at most 2 characters, 2 locations "
            "and 1 item each for npcs/factions/events. Use descriptive names and one-sentence descriptions. "
            "Do not invent rules, effects, predicates or commands: the Python host supplies the validated hybrid "
            "story mechanics after mapping these names and materials. hero must contain name and profile."
            if is_compact_qwen
            else (
                "Return one JSON object with world_definition and hero only; no markdown, no commentary. "
                "world_definition must be schema_version 3 and include name, lorebook, character_cards, "
                "locations, factions, npcs, events, resources, ruleset and story. "
                "For hybrid, ruleset.id must be hybrid and enabled_capabilities must include "
                "chapters, choices, relationships, routes, endings and resources. "
                "story must include arrays named flags, relationships, relationship_events, routes, "
                "chapters and endings. Use globally unique ids; chapter order starts at 1 and has exactly "
                "one terminal chapter. Every chapter object must contain id, title, order, next_chapter_id "
                "and choices; every choice must contain id, label and effects. Every flag must contain id, "
                "default and writers. Each relationship references a character_cards id and has dimensions "
                "with initial/min/max; each relationship event must contain id, relationship_id, deltas, "
                "reason_key, once_scope and cooldown_turns; each choice effect must use a predefined effect type. "
                "npcs and events should contain descriptive name/summary/role/motivation material when present; "
                "event trigger_conditions may only use location_reached, npc_state, npc_reputation, item_owned, faction_tension, "
                "flag, all or any and are only hints for the Python evaluator; "
                "do not put commands, scripts, predicates or arbitrary state writes in them. "
                "The Python host will validate the draft before anything is created."
            )
        )
        prompt = {
            "genre": payload.get("genre", ""),
            "tone": payload.get("tone", ""),
            "core_conflict": payload.get("core_conflict", ""),
            "ruleset": payload.get("ruleset", "hybrid"),
            "instruction": instruction,
        }
        body = request_world_draft(
            {**dict(profile), "api_key": payload.get("api_key")}, prompt
        )
        content = chat_content(profile["provider_type"], body)
        if not content:
            raise CoreRuntimeError("model returned no draft content")
        try:
            draft = json.loads(strip_json_fence(content))
        except json.JSONDecodeError as error:
            raise CoreRuntimeError(f"model draft is not valid JSON: {error.msg}") from error
        definition = draft.get("world_definition") if isinstance(draft, dict) else None
        hero = draft.get("hero") if isinstance(draft, dict) else None
        try:
            self.validate(definition or {}, hero)
        except CoreRuntimeError as error:
            repaired_definition, repairs = repair_generated_definition(definition)
            if repairs:
                try:
                    self.validate(repaired_definition, hero)
                except CoreRuntimeError:
                    pass
                else:
                    return {
                        "valid": True,
                        "summary": "模型草案已整理为可审阅的世界素材。",
                        "world_definition": repaired_definition,
                        "hero": hero if isinstance(hero, dict) else None,
                        "repairs": repairs,
                        "issues": [],
                    }
            mapped_definition, mapped_hero, mapping_repairs = map_to_safe_story_skeleton(
                definition, hero
            )
            if mapping_repairs:
                try:
                    self.validate(mapped_definition, mapped_hero)
                except CoreRuntimeError:
                    pass
                else:
                    return {
                        "valid": True,
                        "summary": "模型素材已整理为可游玩的世界草案，请先审阅地点、角色和事件。",
                        "world_definition": mapped_definition,
                        "hero": mapped_hero,
                        "repairs": mapping_repairs,
                        "issues": [],
                    }
            return {
                "valid": False,
                "summary": "这份草案缺少可安全游玩的必要内容，暂时不能创建。",
                "world_definition": definition if isinstance(definition, dict) else None,
                "hero": hero if isinstance(hero, dict) else None,
                "repairs": [],
                "issues": [{"path": "world_definition", "message": str(error)}],
            }
        return {
            "valid": True,
            "summary": "模型生成的待审阅草案",
            "world_definition": definition,
            "hero": hero,
            "repairs": [],
            "issues": [],
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT runs.*, versions.definition, versions.world_id, worlds.name AS world_name
                FROM local_runs AS runs
                JOIN local_world_versions AS versions ON versions.id = runs.world_version_id
                JOIN local_worlds AS worlds ON worlds.id = versions.world_id
                WHERE runs.id = ?
                """,
                (run_id,),
            ).fetchone()
            turns = connection.execute(
                "SELECT id, request_id, kind, sequence, player_input, narrative, outcomes, after_state FROM local_turns WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
            beats = connection.execute(
                "SELECT id, sequence, content FROM local_story_beats WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        if row is None:
            raise CoreRuntimeError("run not found")
        definition = json.loads(row["definition"])
        state = json.loads(row["state"])
        return {
            "run_id": run_id,
            "world_id": row["world_id"],
            "world_version_id": row["world_version_id"],
            "hero_id": row["hero_id"],
            "model_profile_id": row["model_profile_id"],
            "status": row["status"],
            "state": state,
            "presentation": build_run_presentation(definition),
            "available_choices": available_choices(state, definition),
            "story_beats": [
                {"id": beat["id"], "sequence": beat["sequence"], **json.loads(beat["content"])}
                for beat in beats
            ],
            "turns": [_turn_snapshot(turn) for turn in turns],
        }

    def export_world(self, world_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT worlds.id AS world_id, worlds.name, versions.id AS world_version_id,
                       versions.version_number, versions.definition
                FROM local_worlds AS worlds
                JOIN local_world_versions AS versions ON versions.world_id = worlds.id
                WHERE worlds.id = ?
                ORDER BY versions.version_number DESC
                LIMIT 1
                """,
                (world_id,),
            ).fetchone()
            heroes = (
                connection.execute(
                    "SELECT id, name, profile FROM local_heroes WHERE world_version_id = ?",
                    (row["world_version_id"],),
                ).fetchall()
                if row is not None
                else []
            )
        if row is None:
            raise CoreRuntimeError("world not found")
        return {
            "bundle_version": 1,
            "kind": "world",
            "source": {"world_id": world_id},
            "world_version": {
                "id": row["world_version_id"],
                "version_number": row["version_number"],
                "definition": json.loads(row["definition"]),
            },
            "heroes": [
                {"id": hero["id"], "name": hero["name"], "profile": json.loads(hero["profile"])}
                for hero in heroes
            ],
            "portable_policy": {"new_ids_on_import": True, "automatic_sync": False},
        }

    def import_world(self, payload: dict[str, Any]) -> dict[str, Any]:
        bundle = payload.get("bundle")
        if not isinstance(bundle, dict) or bundle.get("kind") != "world":
            raise CoreRuntimeError("expected portable world bundle")
        definition = (bundle.get("world_version") or {}).get("definition")
        heroes = bundle.get("heroes")
        if not isinstance(definition, dict) or not isinstance(heroes, list) or not heroes:
            raise CoreRuntimeError("portable world bundle is incomplete")
        return self.compose({"world_definition": definition, "hero": heroes[0]})

    def export_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT runs.*, versions.definition, versions.world_id,
                       worlds.name AS world_name, heroes.name AS hero_name, heroes.profile AS hero_profile
                FROM local_runs AS runs
                JOIN local_world_versions AS versions ON versions.id = runs.world_version_id
                JOIN local_worlds AS worlds ON worlds.id = versions.world_id
                JOIN local_heroes AS heroes ON heroes.id = runs.hero_id
                WHERE runs.id = ?
                """,
                (run_id,),
            ).fetchone()
            turns = connection.execute(
                "SELECT * FROM local_turns WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
            beats = connection.execute(
                "SELECT kind, sequence, content FROM local_story_beats WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        if row is None:
            raise CoreRuntimeError("run not found")
        return {
            "bundle_version": 1,
            "kind": "run",
            "source": {"run_id": run_id},
            "world_version": {"definition": json.loads(row["definition"])},
            "hero": {
                "id": row["hero_id"],
                "name": row["hero_name"],
                "profile": json.loads(row["hero_profile"]),
            },
            "run": {
                "state": json.loads(row["state"]),
                "story_beats": [
                    {
                        "kind": beat["kind"],
                        "sequence": beat["sequence"],
                        "content": json.loads(beat["content"]),
                    }
                    for beat in beats
                ],
                "turns": [dict(turn) for turn in turns],
            },
            "portable_policy": {"new_ids_on_clone": True, "automatic_sync": False},
        }

    def clone_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        bundle = payload.get("bundle")
        if not isinstance(bundle, dict) or bundle.get("kind") != "run":
            raise CoreRuntimeError("expected portable run bundle")
        definition = (bundle.get("world_version") or {}).get("definition")
        hero = bundle.get("hero")
        run_data = bundle.get("run")
        if (
            not isinstance(definition, dict)
            or not isinstance(hero, dict)
            or not isinstance(run_data, dict)
        ):
            raise CoreRuntimeError("portable run bundle is incomplete")
        state = run_data.get("state")
        turns_payload = run_data.get("turns") or []
        beats_payload = run_data.get("story_beats") or []
        if (
            not isinstance(state, dict)
            or state.get("schema_version") != 3
            or not isinstance(turns_payload, list)
        ):
            raise CoreRuntimeError("portable run bundle contains invalid state")
        request_ids: set[str] = set()
        sequences: set[int] = set()
        for turn in turns_payload:
            if not isinstance(turn, dict):
                raise CoreRuntimeError("portable run turn must be an object")
            request_id = str(turn.get("request_id") or "")
            sequence = turn.get("sequence")
            if (
                not request_id
                or request_id in request_ids
                or not isinstance(sequence, int)
                or sequence in sequences
            ):
                raise CoreRuntimeError("portable run turns contain duplicate or invalid identity")
            request_ids.add(request_id)
            sequences.add(sequence)
        cloned = self.compose({"world_definition": definition, "hero": hero})
        with self._connect() as connection:
            connection.execute(
                "UPDATE local_runs SET state = ?, revision = ?, status = ? WHERE id = ?",
                (
                    _dump(state),
                    int(state.get("revision", 0)),
                    "completed" if state.get("ending") else "active",
                    cloned["run_id"],
                ),
            )
            if beats_payload:
                connection.execute(
                    "DELETE FROM local_story_beats WHERE run_id = ?", (cloned["run_id"],)
                )
                for beat in beats_payload:
                    if not isinstance(beat, dict) or not isinstance(beat.get("content"), dict):
                        raise CoreRuntimeError("portable story beat must contain content")
                    connection.execute(
                        "INSERT INTO local_story_beats(id, run_id, kind, sequence, content) VALUES (?, ?, ?, ?, ?)",
                        (
                            str(uuid4()),
                            cloned["run_id"],
                            str(beat.get("kind") or "opening"),
                            int(beat.get("sequence", 0)),
                            _dump(beat["content"]),
                        ),
                    )
            for turn in turns_payload:
                connection.execute(
                    "INSERT INTO local_turns(id, run_id, request_id, kind, sequence, player_input, narrative, commands, outcomes, after_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        cloned["run_id"],
                        str(turn.get("request_id") or uuid4()),
                        str(turn.get("kind") or "turn"),
                        int(turn.get("sequence", 0)),
                        str(turn.get("player_input") or ""),
                        str(turn.get("narrative") or ""),
                        _dump(turn.get("commands") or []),
                        _dump(turn.get("outcomes") or []),
                        _dump(turn.get("after_state") or state),
                    ),
                )
        return self.get_run(cloned["run_id"])

    def choose(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM local_runs WHERE id = ?", (run_id,)).fetchone()
            request_id = str(payload.get("request_id") or token_hex(8))
            existing = connection.execute(
                "SELECT id FROM local_turns WHERE run_id = ? AND request_id = ?",
                (run_id, request_id),
            ).fetchone()
        if row is None:
            raise CoreRuntimeError("run not found")
        self._ensure_active_world_for_run(run_id, "choose")
        if existing is not None:
            return self.get_run(run_id)
        state = json.loads(row["state"])
        if state.get("ending"):
            raise CoreRuntimeError("run has ended; start a new Run or rollback")
        definition = self._definition_for_run(run_id)
        expected = payload.get("expected_revision")
        if expected != row["revision"]:
            raise CoreRuntimeError("state revision changed; reload before choosing")
        try:
            commands = planned_choice_commands(state, definition, payload.get("choice_id"))
            outcomes = apply_commands(
                state,
                definition,
                commands,
                validate_command=_validate_command,
                error_type=CoreRuntimeError,
            )
        except (NarrativeRuleError, CoreRuntimeError) as error:
            raise CoreRuntimeError(str(error)) from error
        before = int(row["revision"])
        state["revision"] = before + 1
        outcomes.extend(advance_world_events(state, definition))
        narrative, gm_actions = self._narrate_turn(
            row,
            definition,
            state,
            str(payload.get("player_input") or ""),
            outcomes,
            api_key=payload.get("api_key"),
        )
        outcomes.extend(apply_gm_actions(state, gm_actions))
        settle_world_events(state, definition, outcomes)
        settle_pending_interactions(state, outcomes)
        record_narrative_context(
            state, definition, run_id, str(payload.get("player_input") or ""), narrative, outcomes
        )
        initiative = schedule_npc_initiative(state, definition, run_id)
        if initiative:
            outcomes.append(initiative)
        beat = build_turn_story_beat(definition, state, narrative, outcomes)
        self._require_apply_permission(request_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE local_runs SET state = ?, revision = ?, status = ? "
                "WHERE id = ? AND revision = ?",
                (
                    _dump(state),
                    before + 1,
                    "completed" if state.get("ending") else "active",
                    run_id,
                    before,
                ),
            )
            connection.execute(
                "INSERT INTO local_turns(id, run_id, request_id, kind, sequence, player_input, narrative, commands, outcomes, after_state) VALUES (?, ?, ?, 'turn', ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    run_id,
                    request_id,
                    before + 1,
                    str(payload.get("player_input") or ""),
                    narrative,
                    _dump(commands),
                    _dump(outcomes),
                    _dump(state),
                ),
            )
            connection.execute(
                "INSERT INTO local_story_beats(id, run_id, kind, sequence, content) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), run_id, beat["kind"], before + 1, _dump(beat)),
            )
        self._schedule_director(run_id, before + 1, payload.get("api_key"))
        return self.get_run(run_id)

    def play(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM local_runs WHERE id = ?", (run_id,)).fetchone()
            request_id = str(payload.get("request_id") or token_hex(8))
            existing = connection.execute(
                "SELECT id FROM local_turns WHERE run_id = ? AND request_id = ?",
                (run_id, request_id),
            ).fetchone()
        if row is None:
            raise CoreRuntimeError("run not found")
        self._ensure_active_world_for_run(run_id, "play")
        if existing is not None:
            return self.get_run(run_id)
        state = json.loads(row["state"])
        if state.get("ending"):
            raise CoreRuntimeError("run has ended; start a new Run or rollback")
        definition = self._definition_for_run(run_id)
        if payload.get("expected_revision") != row["revision"]:
            raise CoreRuntimeError("state revision changed; reload before playing")
        commands = payload.get("commands")
        if not isinstance(commands, list) or not commands:
            raise CoreRuntimeError("play requires a non-empty command list")
        outcomes = apply_commands(
            state,
            definition,
            commands,
            validate_command=_validate_command,
            error_type=CoreRuntimeError,
        )
        before = int(row["revision"])
        state["revision"] = before + 1
        outcomes.extend(advance_world_events(state, definition))
        narrative, gm_actions = self._narrate_turn(
            row,
            definition,
            state,
            str(payload.get("player_input") or ""),
            outcomes,
            api_key=payload.get("api_key"),
        )
        outcomes.extend(apply_gm_actions(state, gm_actions))
        settle_world_events(state, definition, outcomes)
        settle_pending_interactions(state, outcomes)
        record_narrative_context(
            state, definition, run_id, str(payload.get("player_input") or ""), narrative, outcomes
        )
        initiative = schedule_npc_initiative(state, definition, run_id)
        if initiative:
            outcomes.append(initiative)
        beat = build_turn_story_beat(definition, state, narrative, outcomes)
        self._require_apply_permission(request_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE local_runs SET state = ?, revision = ?, status = ? "
                "WHERE id = ? AND revision = ?",
                (
                    _dump(state),
                    before + 1,
                    "completed" if state.get("ending") else "active",
                    run_id,
                    before,
                ),
            )
            connection.execute(
                "INSERT INTO local_turns(id, run_id, request_id, kind, sequence, player_input, narrative, commands, outcomes, after_state) VALUES (?, ?, ?, 'turn', ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    run_id,
                    request_id,
                    before + 1,
                    str(payload.get("player_input") or ""),
                    narrative,
                    _dump(commands),
                    _dump(outcomes),
                    _dump(state),
                ),
            )
            connection.execute(
                "INSERT INTO local_story_beats(id, run_id, kind, sequence, content) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), run_id, beat["kind"], before + 1, _dump(beat)),
            )
        self._schedule_director(run_id, before + 1, payload.get("api_key"))
        return self.get_run(run_id)

    def _schedule_director(self, run_id: str, revision: int, api_key: object) -> None:
        """Fire the background Director note after every Nth committed turn.

        The note never runs on the turn's critical path: a daemon thread owns the
        model call, and any failure is silently discarded (ADR-012).
        """

        if not should_run_director(revision):
            return
        threading.Thread(
            target=self._run_director_note,
            args=(run_id, revision, api_key),
            name=f"dzmm-director-{run_id[:8]}-{revision}",
            daemon=True,
        ).start()

    def _run_director_note(self, run_id: str, revision: int, api_key: object) -> None:
        try:
            with self._connect() as connection:
                run = connection.execute(
                    "SELECT model_profile_id FROM local_runs WHERE id = ?", (run_id,)
                ).fetchone()
                profile = (
                    connection.execute(
                        "SELECT * FROM local_model_profiles WHERE id = ?",
                        (run["model_profile_id"],),
                    ).fetchone()
                    if run is not None and run["model_profile_id"]
                    else None
                )
            if profile is None:
                return
            definition = self._definition_for_run(run_id)
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT state FROM local_runs WHERE id = ?", (run_id,)
                ).fetchone()
            if row is None:
                return
            state = json.loads(row["state"])
            prompt = build_director_prompt(state, definition)
            body = request_director_note({**dict(profile), "api_key": api_key}, prompt)
            note = parse_director_note(chat_content(profile["provider_type"], body))
            if not note:
                return
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO director_notes(run_id, turn, tension, hook) VALUES (?, ?, ?, ?)",
                    (run_id, revision, note["tension"], note["hook"]),
                )
        except Exception as error:  # noqa: BLE001 - Director failure must never surface
            logger.debug("director note skipped for %s@%s: %s", run_id, revision, error)

    def _fresh_director_note(
        self, run_id: str, current_turn: int
    ) -> dict[str, str] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT turn, tension, hook FROM director_notes WHERE run_id = ? ORDER BY turn DESC LIMIT 1",
                    (run_id,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or not is_note_fresh(int(row["turn"]), current_turn):
            return None
        return {"tension": row["tension"], "hook": row["hook"], "turn": int(row["turn"])}

    def _narrate_turn(
        self,
        run: sqlite3.Row,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
        *,
        api_key: object = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        profile_id = run["model_profile_id"]
        if not profile_id:
            return build_deterministic_narrative(definition, state, player_input), []
        with self._connect() as connection:
            profile = connection.execute(
                "SELECT * FROM local_model_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if profile is None:
            raise CoreRuntimeError("run model profile not found")
        current_location = next(
            (
                str(item.get("name") or "").strip()
                for item in definition.get("locations") or []
                if isinstance(item, dict) and str(item.get("id")) == str(state.get("location_id"))
            ),
            "",
        )
        body = request_narrative(
            {**dict(profile), "api_key": api_key},
            {
                "world": definition["name"],
                "hero": state["hero"]["name"],
                "location_id": state.get("location_id"),
                "current_location": current_location,
                "chapter": _narrative_chapter_context(definition, state),
                "ending": state.get("ending"),
                "player_input": player_input,
                "validated_outcomes": _narrative_outcome_context(definition, outcomes),
                "narrative_memory": state.get("narrative_context", {}).get("recent_turns", []),
                "memory_layers": _narrative_memory_layers(definition, state, player_input),
                "variation_directive": narrative_variation(definition, state, str(run["id"])),
                "director_note": self._fresh_director_note(
                    str(run["id"]), int(state.get("revision") or 0)
                ),
                "npc_state": state.get("npc_state", {}),
                "faction_state": state.get("faction_state", {}),
                "campaign_state": state.get("campaign_state"),
                "location_state": state.get("location_state", {}),
                "active_events": state.get("active_events", []),
                "plot_threads": state.get("plot_threads", []),
                "pending_interactions": state.get("pending_interactions", []),
                "world_entity_names": _narrative_entity_names(definition),
                "world_material": _narrative_world_material(definition),
                "narrative_guardrails": (
                    "叙事只能使用 world_entity_names 中的角色、NPC、地点、势力和事件名称；"
                    "world_material 只用于理解这些实体的动机和背景；"
                    "不要把内部 ID、模板旧名或关系 ID（例如 lan）写进正文；"
                    "本回合必须围绕 current_location 对应地点展开，除非 validated_outcomes 明确移动，"
                    "不得凭空切换到未列出的地点或使用与当前地点冲突的空间描述。"
                ),
            },
        )
        if model_response_was_truncated(str(profile["provider_type"]), body):
            raise CoreRuntimeError("model narrative was truncated; retry the turn")
        content = chat_content(profile["provider_type"], body)
        visible, actions = extract_gm_actions(content)
        narrative = clean_model_narrative(visible)
        if not narrative:
            raise CoreRuntimeError("model returned no valid narrative content")
        return narrative, actions

    def rollback(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM local_runs WHERE id = ?", (run_id,)).fetchone()
            request_id = str(payload.get("request_id") or token_hex(8))
            existing = connection.execute(
                "SELECT id FROM local_turns WHERE run_id = ? AND request_id = ?",
                (run_id, request_id),
            ).fetchone()
            target = connection.execute(
                "SELECT * FROM local_turns WHERE id = ? AND run_id = ?",
                (str(payload.get("target_turn_id") or ""), run_id),
            ).fetchone()
        if row is None:
            raise CoreRuntimeError("run not found")
        self._ensure_active_world_for_run(run_id, "rollback")
        if existing is not None:
            return self.get_run(run_id)
        if target is None:
            raise CoreRuntimeError("rollback target is not part of this run")
        if payload.get("expected_revision") != row["revision"]:
            raise CoreRuntimeError("state revision changed; reload before rollback")
        state = json.loads(target["after_state"])
        before = int(row["revision"])
        state["revision"] = before + 1
        outcomes = [{"type": "rollback", "target_turn_id": target["id"]}]
        with self._connect() as connection:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM local_turns WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE local_runs SET state = ?, revision = ?, status = ? "
                "WHERE id = ? AND revision = ?",
                (
                    _dump(state),
                    before + 1,
                    "completed" if state.get("ending") else "active",
                    run_id,
                    before,
                ),
            )
            connection.execute(
                "INSERT INTO local_turns(id, run_id, request_id, kind, sequence, player_input, narrative, commands, outcomes, after_state) VALUES (?, ?, ?, 'rollback', ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    run_id,
                    request_id,
                    sequence,
                    f"回滚到第 {target['sequence']} 回合之后",
                    f"已恢复到第 {target['sequence']} 回合之后的状态。",
                    "[]",
                    _dump(outcomes),
                    _dump(state),
                ),
            )
        return self.get_run(run_id)

    def _definition_for_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT versions.definition
                FROM local_runs AS runs
                JOIN local_world_versions AS versions ON versions.id = runs.world_version_id
                WHERE runs.id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise CoreRuntimeError("run not found")
        return json.loads(row["definition"])

    def validate(
        self, definition: dict[str, Any], hero: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if definition.get("schema_version") != 3:
            raise CoreRuntimeError("WorldDefinition schema_version must be 3")
        try:
            validate_definition(definition)
        except (KeyError, TypeError, NarrativeRuleError) as error:
            raise CoreRuntimeError(f"invalid WorldDefinition: {error}") from error
        if hero is not None and not str(hero.get("name") or "").strip():
            raise CoreRuntimeError("hero.name is required")
        return {
            "valid": True,
            "world_definition": definition,
            "hero": hero,
            "issues": [],
            "repairs": [],
        }


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _turn_snapshot(turn: sqlite3.Row) -> dict[str, Any]:
    snapshot = dict(turn)
    try:
        outcomes = json.loads(snapshot.pop("outcomes"))
    except (TypeError, json.JSONDecodeError):
        outcomes = []
    snapshot["rollback_target_id"] = next(
        (
            outcome.get("target_turn_id")
            for outcome in outcomes
            if isinstance(outcome, dict) and outcome.get("type") == "rollback"
        ),
        None,
    )
    return snapshot


def _validate_command(command: dict[str, Any]) -> None:
    if not isinstance(command, dict) or command.get("type") not in {
        "narrate",
        "offer_choices",
        "roll_dice",
        "attack",
        "move",
        "set_entity_state",
        "set_event_state",
        "inventory_change",
        "choose_story_choice",
        "advance_chapter",
        "evaluate_endings",
    }:
        raise CoreRuntimeError("unsupported TurnCommand")


def _fingerprint(payload: dict[str, Any]) -> str:
    import hashlib

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from .contracts import contract_validator
from .generated_world_repair import _unique_named_entities, extend_story_for_long_run
from .model_profiles import ModelDraftGenerator, ModelProfileService, NarrationError
from .narrative import NarrativeRuleError, validate_definition
from .operation_control import OperationRegistry
from .world_templates import fog_harbor_template
from .worlds import HeroInput


class AIWorldDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_id: str = Field(min_length=1, max_length=80)
    ruleset: Literal["story_adventure", "relationship_drama", "hybrid"]
    genre: str = Field(min_length=1, max_length=240)
    tone: str = Field(min_length=1, max_length=240)
    core_conflict: str = Field(min_length=1, max_length=600)
    hero_preference: str = Field(min_length=1, max_length=400)
    character_preferences: list[str] = Field(default_factory=list, max_length=4)
    request_id: str | None = Field(default=None, min_length=1, max_length=120)


class AIWorldDraftReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_definition: dict[str, Any]
    hero: dict[str, Any]


class DraftIssue(BaseModel):
    path: str
    message: str


class AIWorldDraftResult(BaseModel):
    valid: bool
    summary: str | None = None
    world_definition: dict[str, Any] | None = None
    hero: HeroInput | None = None
    repairs: list[str] = Field(default_factory=list)
    issues: list[DraftIssue] = Field(default_factory=list)


class CreativeCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)


class CreativeLore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class CreativeHero(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    origin: str = Field(min_length=1, max_length=400)


class CreativeNPC(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1200)
    motivation: str = Field(default="", max_length=600)
    location: str | None = Field(default=None, max_length=120)
    contact_cooldown_turns: int = Field(default=4, ge=1, le=40)
    faction: str | None = Field(default=None, max_length=120)
    reputation: int = Field(default=0, ge=-100, le=100)


class CreativeFaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1200)
    initial_tension: int = Field(default=0, ge=0, le=100)
    passive_gain_per_turn: int = Field(default=0, ge=0, le=10)
    threshold_conflict: int = Field(default=80, ge=1, le=100)


class CreativeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1200)
    location: str | None = Field(default=None, max_length=120)
    importance: int = Field(default=2, ge=1, le=5)
    trigger_turn: int | None = Field(default=None, ge=1, le=40)
    initial_active: bool = False
    trigger: dict[str, Any] = Field(default_factory=dict)
    completion: dict[str, Any] = Field(default_factory=dict)


class CreativeCampaignPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=600)
    key_event_names: list[str] = Field(default_factory=list, max_length=4)
    required_count: int = Field(default=1, ge=1, le=4)


class CreativeCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    phases: list[CreativeCampaignPhase] = Field(min_length=1, max_length=4)


class CreativeLocationLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_location: str = Field(min_length=1, max_length=120)
    to_location: str = Field(min_length=1, max_length=120)
    direction: str = Field(default="相邻", max_length=40)
    travel_turns: int = Field(default=1, ge=1, le=20)


class CreativeSource(BaseModel):
    """Safe creative material that Python maps into the canonical rule skeleton.

    It deliberately has no state, command, predicate, effect or script fields.
    The optional runtime material is descriptive only; Python assigns IDs and
    decides how it becomes initial world context.
    """

    model_config = ConfigDict(extra="forbid")

    world_name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    hero: CreativeHero
    locations: list[str] = Field(min_length=2, max_length=3)
    characters: list[CreativeCharacter] = Field(min_length=2, max_length=2)
    lore: list[CreativeLore] = Field(min_length=1, max_length=4)
    npcs: list[CreativeNPC] = Field(default_factory=list, max_length=4)
    factions: list[CreativeFaction] = Field(default_factory=list, max_length=3)
    events: list[CreativeEvent] = Field(default_factory=list, max_length=4)
    location_links: list[CreativeLocationLink] = Field(default_factory=list, max_length=4)
    campaign: CreativeCampaign | None = None


class AIWorldDraftService:
    def __init__(
        self, model_profiles: ModelProfileService, generator: ModelDraftGenerator | None = None
    ) -> None:
        self._model_profiles = model_profiles
        self._generator = generator or ModelDraftGenerator()
        self._operations = OperationRegistry()

    async def generate(self, payload: AIWorldDraftInput) -> AIWorldDraftResult:
        request_id = payload.request_id
        if request_id and not self._operations.begin(request_id):
            raise AIWorldDraftGenerationError("operation is already running")
        try:
            return await self._generate(payload)
        finally:
            if request_id:
                self._operations.finish(request_id)

    def cancel_operation(self, request_id: str) -> bool:
        return self._operations.cancel(request_id)

    async def _generate(self, payload: AIWorldDraftInput) -> AIWorldDraftResult:
        profile = await self._model_profiles.get(payload.model_profile_id)
        if profile is None:
            return AIWorldDraftResult(
                valid=False,
                issues=[
                    DraftIssue(
                        path="model_profile_id", message="configured model profile does not exist"
                    )
                ],
            )
        try:
            source_payload, repairs = await self._generator.generate(
                profile, _generation_prompt(payload)
            )
        except NarrationError as error:
            raise AIWorldDraftGenerationError(str(error)) from error
        if payload.request_id and not self._operations.enter_applying(payload.request_id):
            raise AIWorldDraftGenerationError("operation cancelled; draft was discarded")
        try:
            source_payload, source_repairs = _normalize_creative_source_payload(source_payload)
            repairs = [*repairs, *source_repairs]
            source = CreativeSource.model_validate(source_payload)
        except PydanticValidationError as error:
            return AIWorldDraftResult(
                valid=False,
                repairs=repairs,
                issues=_pydantic_issues(error),
            )
        definition, hero = _map_creative_source(source, payload.ruleset)
        result = validate_world_draft(definition, hero)
        reference_issues = _creative_source_reference_issues(source)
        if reference_issues:
            result = result.model_copy(
                update={
                    "valid": False,
                    "issues": [*result.issues, *reference_issues],
                }
            )
        return result.model_copy(update={"summary": source.summary, "repairs": repairs})


class AIWorldDraftGenerationError(ValueError):
    pass


def _normalize_creative_source_payload(payload: Any) -> tuple[Any, list[str]]:
    """Repair harmless weak-model shape drift without granting it rule authority."""

    if not isinstance(payload, dict):
        return payload, []
    normalized = deepcopy(payload)
    repairs: list[str] = []

    factions = normalized.get("factions")
    if isinstance(factions, list):
        for index, faction in enumerate(factions):
            if not isinstance(faction, dict):
                continue
            # Qwen-style Chinese completions occasionally replace the final
            # token in a known key (for example, ``passive_gain_per一点``).
            # Accept only this unambiguous alias, then apply the same bounds
            # as the canonical field; unknown mechanics remain forbidden by
            # CreativeFaction(extra="forbid").
            if "passive_gain_per_turn" not in faction:
                for key in list(faction):
                    normalized_key = "_".join(str(key).strip().split())
                    if normalized_key in {"passive_gain_per_turn", "passive_gain_per一点"}:
                        faction["passive_gain_per_turn"] = faction.pop(key)
                        repairs.append(f"factions[{index}].passive_gain_per_turn 已修正字段名称")
                        break
            for field, minimum, maximum, fallback in (
                ("initial_tension", 0, 100, 0),
                ("passive_gain_per_turn", 0, 10, 0),
                ("threshold_conflict", 1, 100, 80),
            ):
                value = faction.get(field)
                if isinstance(value, bool):
                    value = None
                if isinstance(value, (int, float)):
                    bounded = max(minimum, min(maximum, int(value)))
                else:
                    bounded = fallback
                if value != bounded:
                    faction[field] = bounded
                    repairs.append(f"factions[{index}].{field} 已按安全范围规范化")

    events = normalized.get("events")
    if isinstance(events, list):
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            importance = event.get("importance")
            bounded_importance = (
                max(1, min(5, int(importance)))
                if isinstance(importance, (int, float)) and not isinstance(importance, bool)
                else 2
            )
            if importance != bounded_importance:
                event["importance"] = bounded_importance
                repairs.append(f"events[{index}].importance 已按安全范围规范化")
            for field in ("trigger", "completion"):
                if not isinstance(event.get(field), dict):
                    event[field] = {}
                    repairs.append(f"events[{index}].{field} 非对象条件已忽略")

    npcs = normalized.get("npcs")
    if isinstance(npcs, list):
        for index, npc in enumerate(npcs):
            if not isinstance(npc, dict):
                continue
            for key in list(npc):
                normalized_key = "_".join(str(key).strip().split())
                if normalized_key == "contact_cooldown_turn个数" and "contact_cooldown_turns" not in npc:
                    npc["contact_cooldown_turns"] = npc.pop(key)
                    repairs.append(f"npcs[{index}].contact_cooldown_turns 已修正字段名称")
                    break
            for field, minimum, maximum, fallback in (
                ("contact_cooldown_turns", 1, 40, 4),
                ("reputation", -100, 100, 0),
            ):
                value = npc.get(field)
                if isinstance(value, bool):
                    value = None
                if isinstance(value, (int, float)):
                    bounded = max(minimum, min(maximum, int(value)))
                elif isinstance(value, str):
                    try:
                        bounded = max(minimum, min(maximum, int(value.strip())))
                    except ValueError:
                        bounded = fallback
                else:
                    bounded = fallback
                if value != bounded:
                    npc[field] = bounded
                    repairs.append(f"npcs[{index}].{field} 已按安全范围规范化")

    locations = normalized.get("locations")
    if isinstance(locations, list):
        known_locations = {
            value.strip()
            for value in locations
            if isinstance(value, str) and value.strip()
        }
        referenced_locations: list[tuple[str, str]] = []
        for group_name in ("npcs", "events"):
            entries = normalized.get(group_name)
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                if isinstance(entry, dict) and isinstance(entry.get("location"), str):
                    referenced_locations.append((f"{group_name}[{index}].location", entry["location"].strip()))
        links = normalized.get("location_links")
        if isinstance(links, list):
            for index, link in enumerate(links):
                if not isinstance(link, dict):
                    continue
                for field in ("from_location", "to_location"):
                    if isinstance(link.get(field), str):
                        referenced_locations.append((f"location_links[{index}].{field}", link[field].strip()))
        for path, location in referenced_locations:
            if not location or location in known_locations or len(locations) >= 3:
                continue
            locations.append(location)
            known_locations.add(location)
            repairs.append(f"{path} 已将引用地点加入地点列表")

    return normalized, repairs


def _creative_source_reference_issues(source: CreativeSource) -> list[DraftIssue]:
    """Reject references that cannot be represented in the playable location graph."""

    known_locations = set(source.locations)
    issues: list[DraftIssue] = []
    for group_name, entries in (("npcs", source.npcs), ("events", source.events)):
        for index, entry in enumerate(entries):
            location = getattr(entry, "location", None)
            if location and location not in known_locations:
                issues.append(
                    DraftIssue(
                        path=f"{group_name}[{index}].location",
                        message=f"引用地点“{location}”不在地点列表中；请补充地点或修改该引用。",
                    )
                )
    for index, link in enumerate(source.location_links):
        for field in ("from_location", "to_location"):
            location = getattr(link, field)
            if location not in known_locations:
                issues.append(
                    DraftIssue(
                        path=f"location_links[{index}].{field}",
                        message=f"引用地点“{location}”不在地点列表中；请补充地点或修改该连接。",
                    )
                )
    return issues


def validate_world_draft(definition: dict[str, Any], hero: dict[str, Any]) -> AIWorldDraftResult:
    issues: list[DraftIssue] = []
    for error in sorted(
        contract_validator("world_definition.schema.json").iter_errors(definition),
        key=lambda item: str(item.path),
    ):
        issues.append(DraftIssue(path=_json_path(error), message=error.message))
    try:
        validate_definition(definition)
    except (KeyError, NarrativeRuleError) as error:
        issues.append(DraftIssue(path="world_definition", message=str(error)))
    try:
        validated_hero = HeroInput.model_validate(hero)
    except PydanticValidationError as error:
        issues.extend(_pydantic_issues(error, prefix="hero"))
        validated_hero = None
    return AIWorldDraftResult(
        valid=not issues,
        world_definition=definition,
        hero=validated_hero,
        issues=issues,
    )


def _generation_prompt(payload: AIWorldDraftInput) -> dict[str, Any]:
    return {
        "system": (
            "你是 DZMM vNext 的世界创作草案员。只输出一个 JSON 对象，不要 Markdown、解释、"
            "代码、命令、规则、状态、正则、脚本或 Python。JSON 只能含 world_name、summary、hero、"
            "locations、characters、lore、npcs、factions、events、location_links、campaign。hero 只能含 name 和 origin；"
            "locations 是 2 到 3 个名称；"
            "characters 恰好是 2 项，每项只能含 name、role、description；lore 是 1 到 4 项，每项"
            "只能含 title、body。npcs 最多 4 项，每项只能含 name、role、description、motivation、"
            "location、contact_cooldown_turns、faction、reputation；factions 最多 3 项，每项只能含 name、description、"
            "initial_tension、passive_gain_per_turn、threshold_conflict；events 最多 4 项，每项只能含 "
            "name、summary、location、importance、trigger_turn、initial_active、trigger、completion；trigger 和 completion 只使用 "
            "location_reached、npc_state、item_owned、faction_tension、flag、all、any 这些谓词；"
            "campaign 只能含 name 和 phases；每个 phase 只能含 name、description、key_event_names、required_count。"
            "location_links 最多 4 项，每项只能含 from_location、to_location、direction、travel_turns。"
            "这些字段只能描述世界素材，不能写入状态、命令、规则、效果或脚本。所有文本用简洁中文。"
        ),
        "brief": payload.model_dump(exclude={"model_profile_id", "request_id"}),
        "first_slice": "给出三章节互动叙事素材，并补充 1 到 4 个有动机的 NPC、至少 1 个可追踪世界事件、"
        "可选势力和地点连接；Python 会独立生成所有 choice、Flag、关系事件和结局规则。",
    }


def _map_creative_source(
    source: CreativeSource, ruleset: Literal["story_adventure", "relationship_drama", "hybrid"]
) -> tuple[dict[str, Any], dict[str, Any]]:
    template = fog_harbor_template()
    definition = deepcopy(template["world_definition"])
    characters = source.characters
    locations = source.locations
    definition["name"] = source.world_name
    definition["ruleset"] = {
        "id": ruleset,
        "enabled_capabilities": [
            *(["trpg"] if ruleset == "hybrid" else []),
            "chapters",
            "choices",
            "relationships",
            "routes",
            "endings",
            "resources",
        ],
    }
    definition["locations"][0]["name"] = locations[0]
    definition["locations"][1]["name"] = locations[1]
    for index, location_name in enumerate(locations[2:], start=3):
        definition["locations"].append({"id": f"location-{index}", "name": location_name})
    location_ids = [location["id"] for location in definition["locations"]]
    location_names = {
        name: location_id for name, location_id in zip(locations, location_ids, strict=True)
    }
    for index, location in enumerate(definition["locations"]):
        location["connections"] = []
        if index + 1 < len(location_ids):
            location["connections"].append(
                {
                    "target_id": location_ids[index + 1],
                    "direction": "前往",
                    "travel_turns": 1,
                }
            )
        if index > 0:
            location["connections"].append(
                {
                    "target_id": location_ids[index - 1],
                    "direction": "返回",
                    "travel_turns": 1,
                }
            )
    definition["character_cards"] = [
        {
            "id": card_id,
            "name": character.name,
            "format": "native",
            "mapped": {
                "description": character.description,
                "personality": character.role,
                "scenario": source.summary,
                "first_mes": f"我是{character.name}。{character.role}",
            },
        }
        for card_id, character in zip(("lan", "shen_yan"), characters, strict=True)
    ]
    # Character cards are also runtime NPCs: cards hold voice/personality,
    # while this parallel entity carries location and contact behavior.
    definition["npcs"] = [
        {
            "id": card_id,
            "name": character.name,
            "role": character.role,
            "description": character.description,
            "motivation": character.description,
            "location_id": location_ids[index % len(location_ids)],
            "contact_cooldown_turns": 4,
        }
        for index, (card_id, character) in enumerate(
            zip(("lan", "shen_yan"), characters, strict=True)
        )
    ]
    for index, npc in enumerate(source.npcs, start=1):
        location_id = _resolve_location_id(npc.location, location_names, location_ids, index)
        definition["npcs"].append(
            {
                "id": f"npc-{index}",
                "name": npc.name,
                "role": npc.role,
                "description": npc.description,
                "motivation": npc.motivation,
                "location_id": location_id,
                "contact_cooldown_turns": npc.contact_cooldown_turns,
                "faction_name": npc.faction,
                "reputation": npc.reputation,
            }
        )
    # Character cards are mirrored as runtime NPCs for voice/contact behavior;
    # if a model repeats a card in its explicit NPC list, keep one canonical
    # entity so the player does not see duplicate people or receive duplicate
    # initiative events.
    definition["npcs"] = _unique_named_entities(definition["npcs"])
    definition["factions"] = [
        {
            "id": f"faction-{index}",
            "name": faction.name,
            "description": faction.description,
            "initial_tension": faction.initial_tension,
            "tension_rules": {
                "passive_gain_per_turn": faction.passive_gain_per_turn,
                "threshold_conflict": faction.threshold_conflict,
            },
        }
        for index, faction in enumerate(source.factions, start=1)
    ]
    faction_ids_by_name = {faction["name"]: faction["id"] for faction in definition["factions"]}
    for npc in definition["npcs"]:
        faction_name = npc.pop("faction_name", None)
        if faction_name in faction_ids_by_name:
            npc["faction_id"] = faction_ids_by_name[faction_name]
    definition["events"] = [
        {
            "id": f"event-{index}",
            "name": event.name,
            "summary": event.summary,
            "scope_ref": _resolve_location_id(event.location, location_names, location_ids, index),
            "importance": event.importance,
            "trigger_turn": event.trigger_turn,
            "initial_active": event.initial_active,
            "trigger_conditions": event.trigger,
            "completion_conditions": event.completion,
            "campaign_phase_id": None,
        }
        for index, event in enumerate(source.events, start=1)
    ]
    if not definition["events"]:
        definition["events"] = [
            {
                "id": "event-opening-pressure",
                "name": f"{source.world_name}的暗潮",
                "summary": source.summary,
                "scope_ref": location_ids[0],
                "importance": 2,
                "trigger_turn": None,
                "initial_active": True,
            }
        ]
    if source.campaign:
        event_ids_by_name = {event["name"]: event["id"] for event in definition["events"]}
        campaign_phases = [
            {
                "id": f"phase-{index}",
                "name": phase.name,
                "description": phase.description,
                "key_event_ids": [
                    event_ids_by_name[name]
                    for name in phase.key_event_names
                    if name in event_ids_by_name
                ],
                "required_count": phase.required_count,
            }
            for index, phase in enumerate(source.campaign.phases, start=1)
        ]
        for phase in campaign_phases:
            for event in definition["events"]:
                if event["id"] in phase["key_event_ids"]:
                    event["campaign_phase_id"] = phase["id"]
        definition["story"]["campaign"] = {
            "id": "campaign-main",
            "name": source.campaign.name,
            "phases": campaign_phases,
        }
    for link in source.location_links:
        source_id = _resolve_location_id(link.from_location, location_names, location_ids, 0)
        target_id = _resolve_location_id(link.to_location, location_names, location_ids, 1)
        if source_id == target_id:
            continue
        definition["locations"][location_ids.index(source_id)]["connections"].append(
            {
                "target_id": target_id,
                "direction": link.direction,
                "travel_turns": link.travel_turns,
            }
        )
    definition["lorebook"] = {
        "entries": [
            {
                "id": f"ai-lore-{index}",
                "title": lore.title,
                "body": lore.body,
                "activation": "always" if index == 1 else "keyword",
                "keywords": [source.world_name] if index != 1 else [],
                "priority": max(10, 100 - index * 10),
            }
            for index, lore in enumerate(source.lore, start=1)
        ]
    }
    definition["resources"][0]["name"] = "关键线索"
    _rename_story_surface(definition, source.world_name, locations, characters)
    hero = {
        "name": source.hero.name,
        "profile": {"origin": source.hero.origin, "preference": source.summary},
    }
    return definition, hero


def _resolve_location_id(
    value: str | None,
    location_names: dict[str, str],
    location_ids: list[str],
    fallback_index: int,
) -> str:
    if value and value in location_names:
        return location_names[value]
    return location_ids[fallback_index % len(location_ids)]


def _rename_story_surface(
    definition: dict[str, Any],
    world_name: str,
    locations: list[str],
    characters: list[CreativeCharacter],
) -> None:
    first, second = characters
    story = definition["story"]
    story["routes"][0]["name"] = f"{first.name}路线"
    story["routes"][1]["name"] = f"{second.name}路线"
    chapters = story["chapters"]
    chapters[0]["title"] = f"抵达{locations[0]}"
    chapters[0]["choices"][0]["label"] = f"援手{first.name}"
    chapters[0]["choices"][1]["label"] = f"替{second.name}保守秘密"
    chapters[1]["title"] = f"{world_name}的证词"
    chapters[1]["choices"][0]["label"] = f"把证词交给{first.name}"
    chapters[1]["choices"][1]["label"] = f"帮助{second.name}坦白"
    chapters[1]["choices"][2]["label"] = f"独自追查{locations[0]}的线索"
    chapters[1]["choices"][3]["label"] = f"让{first.name}与{second.name}共同作证"
    chapters[2]["title"] = f"{locations[1]}的决断"
    chapters[2]["choices"][0]["label"] = f"在{locations[1]}完成关键行动"
    chapters[2]["choices"][1]["label"] = "暂缓行动"
    extend_story_for_long_run(
        definition,
        world_name,
        locations,
        [character.name for character in characters],
    )


def _pydantic_issues(error: PydanticValidationError, prefix: str = "") -> list[DraftIssue]:
    return [
        DraftIssue(
            path=".".join([prefix, *map(str, item["loc"])]).strip("."),
            message=item["msg"],
        )
        for item in error.errors()
    ]


def _json_path(error: ValidationError) -> str:
    return ".".join(map(str, error.absolute_path)) or "world_definition"

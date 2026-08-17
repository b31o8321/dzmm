from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from .contracts import contract_validator
from .model_profiles import ModelDraftGenerator, ModelProfileService, NarrationError
from .narrative import NarrativeRuleError, validate_definition
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


class CreativeSource(BaseModel):
    """The only structure a model may author in the first draft slice.

    It deliberately has no state, command, predicate, effect or script fields. Python maps this
    creative material into the fixed, schema-v3 rule skeleton below.
    """

    model_config = ConfigDict(extra="forbid")

    world_name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    hero: CreativeHero
    locations: list[str] = Field(min_length=2, max_length=3)
    characters: list[CreativeCharacter] = Field(min_length=2, max_length=2)
    lore: list[CreativeLore] = Field(min_length=1, max_length=4)


class AIWorldDraftService:
    def __init__(
        self, model_profiles: ModelProfileService, generator: ModelDraftGenerator | None = None
    ) -> None:
        self._model_profiles = model_profiles
        self._generator = generator or ModelDraftGenerator()

    async def generate(self, payload: AIWorldDraftInput) -> AIWorldDraftResult:
        profile = await self._model_profiles.get(payload.model_profile_id)
        if profile is None:
            return AIWorldDraftResult(
                valid=False,
                issues=[DraftIssue(path="model_profile_id", message="configured model profile does not exist")],
            )
        try:
            source_payload, repairs = await self._generator.generate(profile, _generation_prompt(payload))
        except NarrationError as error:
            raise AIWorldDraftGenerationError(str(error)) from error
        try:
            source = CreativeSource.model_validate(source_payload)
        except PydanticValidationError as error:
            return AIWorldDraftResult(
                valid=False,
                repairs=repairs,
                issues=_pydantic_issues(error),
            )
        definition, hero = _map_creative_source(source, payload.ruleset)
        result = validate_world_draft(definition, hero)
        return result.model_copy(update={"summary": source.summary, "repairs": repairs})


class AIWorldDraftGenerationError(ValueError):
    pass


def validate_world_draft(definition: dict[str, Any], hero: dict[str, Any]) -> AIWorldDraftResult:
    issues: list[DraftIssue] = []
    for error in sorted(
        contract_validator("world_definition.schema.json").iter_errors(definition), key=lambda item: str(item.path)
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
            "locations、characters、lore。hero 只能含 name 和 origin；locations 是 2 到 3 个名称；"
            "characters 恰好是 2 项，每项只能含 name、role、description；lore 是 1 到 4 项，每项"
            "只能含 title、body。所有文本用简洁中文。"
        ),
        "brief": payload.model_dump(exclude={"model_profile_id"}),
        "first_slice": "给出雾港同等复杂度的三章节互动叙事素材；Python 会独立生成所有 choice、Flag、关系事件和结局规则。",
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
            *( ["trpg"] if ruleset == "hybrid" else [] ),
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


def _rename_story_surface(
    definition: dict[str, Any], world_name: str, locations: list[str], characters: list[CreativeCharacter]
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
    chapters[1]["choices"][3]["label"] = f"让{first.name}与{second.name}共同作证"
    chapters[2]["title"] = f"{locations[1]}的决断"


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

"""Asset distillation MVP (v1.7.0 P1) — turn a playthrough into writing assets.

The soul of the dzmm asset ecosystem: a run's narrative corpus is far denser
than any hand-written character card. This module distills it into three
player-facing assets: a character bible (角色小传), a dialogue fingerprint
(台词样本), and an event chronicle (事件年表). Pure functions here; the LLM
round-trip and persistence live in the transport layers.
"""

from __future__ import annotations

import json
from typing import Any

DISTILLATION_KINDS = ("character-bible", "dialogue-fingerprint", "chronicle")
CORPUS_TURN_CHARS = 600
CORPUS_TURNS_MAX = 60


def build_corpus(state: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    """Compact the run corpus: most recent turns, trimmed, oldest first."""

    pieces: list[str] = []
    hero = str((state.get("hero") or {}).get("name") or "主角")
    for turn in turns:
        if turn.get("kind") != "turn":
            continue
        pieces.append(
            f"回合{turn.get('sequence')}｜{hero}：{str(turn.get('player_input') or '')[:200]}\n"
            f"{str(turn.get('narrative') or '')[:CORPUS_TURN_CHARS]}"
        )
    return "\n\n".join(pieces[-CORPUS_TURNS_MAX:])


def build_distill_prompt(kind: str, hero: str, world: str, corpus: str) -> dict[str, Any]:
    systems = {
        "character-bible": (
            "你是叙事资产蒸馏器。只依据给定语料，为主角写一份角色小传（400-600 字）："
            "背景与动机、恐惧与矛盾点、已展现的成长弧线、与关键人物的关系。"
            "语料没有的不要编造。只输出小传正文。"
        ),
        "dialogue-fingerprint": (
            "你是叙事资产蒸馏器。只依据给定语料，输出主角的语言指纹 JSON："
            '{"口头禅": ["..."], "句式习惯": ["..."], "情绪语气样本": [{"情绪": "...", "示例": "..."}]}。'
            "每类至多 5 条，样本引用原文短语；语料没有的类别给空数组。只输出 JSON。"
        ),
        "chronicle": (
            "你是叙事资产蒸馏器。只依据给定语料，输出事件年表 JSON："
            '{"events": [{"回合": 1, "事件": "...", "影响": "..."}]}。'
            "按回合顺序，至多 30 条，只记语料中实际发生的事。只输出 JSON。"
        ),
    }
    if kind not in systems:
        raise ValueError(f"unknown distillation kind: {kind}")
    return {
        "system": systems[kind],
        "world": world,
        "hero": hero,
        "corpus": corpus[:24000],
    }


def parse_distill_content(kind: str, content: str) -> dict[str, Any]:
    """Parse model output; JSON kinds tolerate code fences, text kinds pass through."""

    cleaned = content.strip()
    if kind == "character-bible":
        return {"text": cleaned}
    stripped = cleaned
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json")
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return {"raw": cleaned}
    if not isinstance(parsed, dict):
        return {"raw": cleaned}
    return parsed

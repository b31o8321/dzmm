"""Canonical genre presets for the AI world-draft wizard.

Ported in spirit from the legacy wizard's five canonical genres: presets give
the model a proven genre frame instead of guessing from free text.  A preset
expands ``genre`` into a label plus concrete narrative guidance; unknown input
still passes through untouched so custom genres remain first-class.
"""

from __future__ import annotations

from typing import Any

GENRE_PRESETS: dict[str, dict[str, str]] = {
    "mystery": {
        "label": "悬疑探案",
        "tone": "阴郁克制，线索驱动，真相分层揭开",
        "core_conflict": "一桩看似意外的案件背后藏着人为的真相，知情者各有隐瞒",
        "guidance": "重调查、搜证与推理；关键 NPC 各自掌握不完整的信息碎片",
    },
    "hero_growth": {
        "label": "英雄成长",
        "tone": "热血昂扬，挑战逐步升级",
        "core_conflict": "初出茅庐的主角必须直面远超自身实力的威胁并蜕变为守护者",
        "guidance": "重试炼与成长弧线；强敌与导师交替出现，胜利需要代价",
    },
    "intrigue": {
        "label": "政治阴谋",
        "tone": "冷峻紧凑，话中有话",
        "core_conflict": "派系围绕权力真空互相倾轧，主角的每次站队都在改写棋局",
        "guidance": "重谈判、结盟与背叛；信息就是武器，暴力是最后手段",
    },
    "survival": {
        "label": "灾难求生",
        "tone": "压抑急迫，资源枯竭的窒息感",
        "core_conflict": "灾变切断了退路，幸存者必须在消耗殆尽前找到生机",
        "guidance": "重资源管理与艰难取舍；环境本身是主要敌人",
    },
    "romance": {
        "label": "恋爱攻略",
        "tone": "温暖细腻，情绪流动",
        "core_conflict": "靠近彼此心意的过程中，性格差异与外部阻力不断制造误解",
        "guidance": "重关系维度与日常事件；选择影响好感与结局走向",
    },
}

_PRESET_INDEX = {
    key: key
    for key in GENRE_PRESETS
} | {preset["label"]: key for key, preset in GENRE_PRESETS.items()}


def genre_preset_list() -> list[dict[str, Any]]:
    """Return presets in canonical order for client pickers."""

    return [
        {"id": key, **preset}
        for key, preset in GENRE_PRESETS.items()
    ]


def resolve_genre(genre: str) -> str:
    """Expand a preset id/label into guidance; pass unknown genres through."""

    key = _PRESET_INDEX.get(genre.strip())
    if key is None:
        return genre
    preset = GENRE_PRESETS[key]
    return f"{preset['label']}：{preset['guidance']}"

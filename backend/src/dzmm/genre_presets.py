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
        "skeleton": {
            "ch1_choices": ["协助{a}勘查现场", "替{b}隐瞒线索"],
            "ch2_title": "{world}的第一次勘查",
            "ch2_choices": [
                "把勘查记录交给{a}",
                "替{b}圆上供词",
                "独自梳理{location}的时间线",
                "让{a}与{b}当面对质",
            ],
            "longrun_title": "{world}·疑点追踪 {n}",
            "longrun_choices": ["在{location}复核疑点", "与{character}核对口供"],
            "terminal_title": "{location}的收网时刻",
            "terminal_choices": ["在{location}亮出全部证据", "让案子悬而未决"],
            "opening_narratives": [
                "{chapter_title}。{hero}走进{location}，雨还没有停。",
                "{chapter_title}。{world}的旧档案里，{hero}的名字被人用铅笔划去过一次。",
            ],
            "npc_first_lines": [
                "{hero}，你比我预想的来得早。",
                "别碰那件证物——先回答我一个问题，{hero}。",
            ],
        },
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
        "skeleton": {
            "ch1_choices": ["替{a}递上密件", "替{b}掩住口风"],
            "ch2_title": "{world}的供词",
            "ch2_choices": [
                "把密件呈给{a}",
                "替{b}掩护行踪",
                "暗中搜查{location}的书房",
                "让{a}与{b}在殿前对质",
            ],
            "longrun_title": "{world}·暗流涌动 {n}",
            "longrun_choices": ["在{location}查访线索", "向{character}递话试探"],
            "terminal_title": "{location}的摊牌之夜",
            "terminal_choices": ["在{location}摊开所有证据", "把证据留给下一任"],
            "opening_narratives": [
                "{chapter_title}。{hero}抱着密档走进{location}，殿内的火盆烧得很旺。",
                "{chapter_title}。{world}的更鼓敲过三巡，{hero}还没有等到传召。",
            ],
            "npc_first_lines": [
                "{hero}，聪敏人此刻应该低头记录。",
                "你来得正好，{hero}——有一份卷宗少了名字。",
            ],
        },
    },
    "survival": {
        "label": "灾难求生",
        "tone": "压抑急迫，资源枯竭的窒息感",
        "core_conflict": "灾变切断了退路，幸存者必须在消耗殆尽前找到生机",
        "guidance": "重资源管理与艰难取舍；环境本身是主要敌人",
        "skeleton": {
            "ch1_choices": ["抢修{a}负责的舱段", "把最后的面罩让给{b}"],
            "ch2_title": "{world}的资源清单",
            "ch2_choices": [
                "把物资调配权交给{a}",
                "替{b}隐瞒伤情",
                "清点{location}的剩余补给",
                "让{a}与{b}分头待命",
            ],
            "longrun_title": "{world}·资源消耗 {n}",
            "longrun_choices": ["在{location}搜寻可用补给", "和{character}清点余量"],
            "terminal_title": "{location}的最后窗口",
            "terminal_choices": ["在{location}执行突围方案", "原地保守待援"],
            "opening_narratives": [
                "{chapter_title}。{hero}在{location}清点完最后一瓶氧气。",
                "{chapter_title}。{location}的警报响了三声，被{hero}手动关掉了。",
            ],
            "npc_first_lines": [
                "{hero}，照这个消耗速度，我们撑不到救援。",
                "别关警报，{hero}——那是我们唯一的计时器。",
            ],
        },
    },
    "romance": {
        "label": "恋爱攻略",
        "tone": "温暖细腻，情绪流动",
        "core_conflict": "靠近彼此心意的过程中，性格差异与外部阻力不断制造误解",
        "guidance": "重关系维度与日常事件；选择影响好感与结局走向",
    },
}

GENRE_PRESETS["steampunk_western"] = {
    "label": "蒸汽朋克西部",
    "tone": "粗粝，黄沙与蒸汽",
    "core_conflict": "铁路公司要用蒸汽机车碾平最后一座不卖账的自由镇",
    "guidance": "重对抗与斡旋；公司代理人、镇民与小人物各有筹码",
    "skeleton": {
        "ch1_choices": ["替{a}守住工坊", "给{b}递一把六发左轮"],
        "ch2_title": "{world}的对峙",
        "ch2_choices": [
            "把账本交给{a}",
            "替{b}挡下传票",
            "暗查{location}的铁轨图",
            "让{a}与{b}公开结盟",
        ],
        "longrun_title": "{world}·对抗升级 {n}",
        "longrun_choices": ["在{location}组织抵抗", "与{character}谈判斡旋"],
        "terminal_title": "{location}的正午对决",
        "terminal_choices": ["在{location}正面迎战", "带镇民撤入荒野"],
        "opening_narratives": [
            "{chapter_title}。蒸汽机车碾过铁轨，{hero}在{location}擦完了最后一发子弹。",
            "{chapter_title}。{world}的风沙糊住了告示，{hero}把它撕了下来。",
        ],
        "npc_first_lines": [
            "{hero}，公司的火车不等人。",
            "镇上都在传，{hero}——说你不会退。",
        ],
    },
}

_PRESET_INDEX = {
    key: key
    for key in GENRE_PRESETS
} | {preset["label"]: key for key, preset in GENRE_PRESETS.items()}
_PRESET_INDEX["steampunk_western"] = "steampunk_western"
_PRESET_INDEX["蒸汽朋克西部"] = "steampunk_western"


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


# 未命中预设（自由文本 genre / 兜底）时使用的默认骨架：与历史标签逐字一致。
DEFAULT_SKELETON = {
    "ch1_choices": ["援手{a}", "替{b}保守秘密"],
    "ch2_title": "{world}的证词",
    "ch2_choices": [
        "把证词交给{a}",
        "帮助{b}坦白",
        "独自追查{location}的线索",
        "让{a}与{b}共同作证",
    ],
    "longrun_title": "{world}·线索推进 {n}",
    "longrun_choices": ["在{location}追查新线索", "向{character}询问进展"],
    "terminal_title": "{location}的最终决断",
    "terminal_choices": ["在{location}完成关键行动", "暂缓行动，等待更佳时机"],
    "opening_narratives": [
        "{chapter_title}。{hero}抵达{location}，{world}的故事从此刻开始。",
    ],
    "npc_first_lines": ["{hero}，别让这里替你作出第一个决定。"],
}


def skeleton_for_genre(genre: str) -> dict[str, Any]:
    """Return the label skeleton for a preset genre; unknown genres use the default."""

    key = _PRESET_INDEX.get(genre.strip())
    if key is None:
        return DEFAULT_SKELETON
    return GENRE_PRESETS[key].get("skeleton") or DEFAULT_SKELETON


def skeleton_for_labels(first_choice_label: str, second_choice_label: str) -> dict[str, Any]:
    """Identify the skeleton from a composed definition's first-chapter labels.

    The chosen skeleton drives opening-beat phrasing variants so a persisted
    world keeps its genre voice without carrying the genre string itself.
    """

    for preset in GENRE_PRESETS.values():
        skeleton = preset.get("skeleton") or {}
        patterns = skeleton.get("ch1_choices") or []
        if len(patterns) == 2:
            first_prefix = patterns[0].split("{")[0]
            second_prefix = patterns[1].split("{")[0]
            if (
                first_prefix
                and second_prefix
                and first_choice_label.startswith(first_prefix)
                and second_choice_label.startswith(second_prefix)
            ):
                return skeleton
    return DEFAULT_SKELETON

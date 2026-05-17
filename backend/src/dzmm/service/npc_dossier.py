# ============================================================
# npc_dossier.py — NPC 档案格式化（GM Prompt 注入用）
# ============================================================
# 【什么是 NPC 档案（dossier）？】
#   NPC = Non-Player Character，游戏里由 GM（AI）扮演的角色。
#   每个 NPC 在数据库里有一行记录，包含：姓名、性别、好感度、状态、
#   动机、原型（archetype）、外貌描述等字段。
#
#   档案（dossier）是把这些字段格式化成"给 GM 看的简报"，
#   注入到 GM Prompt 的 key_facts 区块里。
#   GM 根据这些信息决定 NPC 的行为、台词、态度。
#
# 【为什么要有"未揭示"机制？】
#   玩家视角：NPC 的真实动机/背景是谜，要通过游戏逐渐发现。
#   GM 视角：GM 知道 NPC 的所有秘密，但不应该直接告诉玩家。
#   revealed_json 记录玩家"已知道"的字段，GM 只能在叙述中提到已揭示的内容，
#   未揭示的字段用 [未揭示：...] 标注，提醒 GM 不要泄露。
#
# Extracted from service/game.py (v0.1.6 refactor)
# ============================================================

import json

from dzmm.db.models import NPC  # NPC 数据库模型


# ── 辅助：解码 revealed_json ──────────────────────────────────────────────────
def _npc_revealed(npc: NPC) -> dict[str, bool]:
    # 解析 npc.revealed_json（一个 JSON 字符串，记录哪些字段已被玩家了解）
    # 例如：{"name": true, "description": true, "favor": false}
    # 如果 JSON 损坏或为空，返回空字典（name 会在下面强制设为 True）
    try:
        revealed = json.loads(npc.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {}
    except (TypeError, ValueError):
        revealed = {}
    # name 始终揭示 —— GM 必须能称呼这个 NPC，即使其他信息都隐藏
    revealed["name"] = True
    return revealed


def _effective_reveals(npc: NPC) -> dict[str, bool]:
    # 返回"有效揭示状态"：存储的 revealed_json 叠加上 Python 端的自动揭示规则
    #
    # 【为什么有这个函数？】
    #   旧版本：自动揭示规则（如"见过的 NPC 自动揭示外貌"）只存在于前端序列化器，
    #   所以 GM Prompt 里还是显示 "[未揭示：description]"，
    #   哪怕玩家已经和这个 NPC 见过面了。这导致 GM 反复"提示"玩家去了解 NPC。
    #   新版本：两处代码（Prompt 注入 + 前端序列化）都经过这个函数，保持一致。
    #
    # 【setdefault 的语义】
    #   setdefault("key", True) 只在 key 不存在时设为 True，
    #   所以如果 revealed_json 里明确写了 "description": false，会保留 False。
    #   （GM 可以手动压制某个字段，即使玩家理论上已见过该 NPC）
    revealed = _npc_revealed(npc)

    # 已钉选（pinned）的 NPC = 剧本里预设的主要角色，玩家一开始就知道他们存在
    # 立即揭示好感数值，让玩家能跟踪关系走向
    # 但 description/state 可能含剧情秘密，等玩家真正遇到再揭示
    if npc.pinned:
        revealed.setdefault("favor", True)

    # NPC 在故事中首次出场后（last_seen_turn > 0），基础可观察字段自动揭示
    if npc.last_seen_turn > 0:
        revealed.setdefault("description", True)  # 外貌/描述
        revealed.setdefault("state", True)         # 当前状态
        revealed.setdefault("favor", True)         # 好感度

    # 有过有意义互动后（好感绝对值 ≥ 20），NPC 的性格原型（archetype）变得明显
    if abs(npc.favor) >= 20 or (
        npc.last_seen_turn > 0 and (npc.archetype or "").strip()
    ):
        revealed.setdefault("archetype", True)

    # 建立较深关系后（好感绝对值 ≥ 30），NPC 的真实目的才浮现
    if abs(npc.favor) >= 30:
        revealed.setdefault("purpose", True)

    # 再次强制 name = True，防止上面的 setdefault 覆盖掉它（保险措施）
    revealed["name"] = True
    return revealed


# ── 主格式化：完整档案（用于钉选 NPC 和被召回的 NPC）───────────────────────
def _format_npc_dossier(npc: NPC) -> str:
    # 生成 3~5 行的 NPC 详细档案块，注入 GM Prompt 的 key_facts 区块
    #
    # 【v0.11 揭示机制】
    #   未在 revealed_json 里标记的字段，不打印其实际值，
    #   而是告知 GM"该字段存在但未揭示"，让 GM 通过叙事自然地展示它
    #   （而不是直接说出来）
    revealed = _effective_reveals(npc)

    archetype = (npc.archetype or "").strip()                  # 性格原型（如：守护者、反派）
    state = (npc.state or "").strip() or "未知"                # 当前状态（如：受伤、焦虑）

    # 性别标记：♂/♀ 直接显示，不受 revealed 控制（属于基础身份信息）
    gender = (npc.gender or "").strip()
    gender_marker = {"male": "♂", "female": "♀"}.get(gender, "")
    # 构造第一行：姓名(性别)[原型] 状态：xxx
    head = f"- {npc.name}"
    if gender_marker:
        head += f"({gender_marker})"
    # 只有 archetype 已被揭示才显示（否则玩家不应知道 NPC 的性格原型）
    if archetype and revealed.get("archetype"):
        head += f" [{archetype}]"
    # 状态已揭示才显示
    if revealed.get("state"):
        head += f" 状态：{state}"

    lines: list[str] = [head]

    # 动机（purpose）：只有建立较深关系后才揭示
    purpose = (npc.purpose or "").strip()
    if purpose and revealed.get("purpose"):
        lines.append(f"  动机：{purpose}")

    # 好感度 + 多轴亲密度（affinity）数据
    affinity_parts: list[str] = []
    if revealed.get("favor"):
        # :+d 格式让正好感显示为 +10，负好感显示为 -5
        affinity_parts.append(f"好感{npc.favor:+d}")
    if revealed.get("affinity"):
        try:
            # affinity_json 存储多维度关系数据，如 {"信任": 30, "亲密": 10}
            affinity = json.loads(npc.affinity_json or "{}")
        except (TypeError, ValueError):
            affinity = {}
        if isinstance(affinity, dict):
            for axis, val in affinity.items():
                if isinstance(val, (int, float)):
                    affinity_parts.append(f"{axis}{int(val):+d}")
    if affinity_parts:
        lines.append("  " + "｜".join(affinity_parts))  # 用全角竖线分隔各项

    # 最近备注或描述
    try:
        notes = json.loads(npc.notes_json or "[]")
    except (TypeError, ValueError):
        notes = []
    if isinstance(notes, list) and notes:
        # notes 是 GM 写的连续性标注（如"分享了童年阴影"），记录玩家已经目睹的场景
        # 不受 revealed_json 控制，因为这些内容玩家本来就已经看到了
        last = notes[-1]
        text = ""
        if isinstance(last, dict):
            text = str(last.get("text", "")).strip()
        elif isinstance(last, str):
            text = last.strip()
        if text:
            lines.append(f"  最近：{text}")  # 显示最新的一条备注
    elif npc.description and revealed.get("description"):
        desc = npc.description.strip()
        if desc:
            lines.append(f"  备注：{desc[:60]}")  # 截取前 60 字符，避免档案过长

    # v0.53: speech_pattern — GM-only vocal tic hint (never counts as "revealed")
    speech_pattern = (getattr(npc, "speech_pattern", "") or "").strip()
    if speech_pattern:
        lines.append(f"  说话风格：{speech_pattern}")

    # 【未揭示字段列表】
    # 收集所有"有内容但玩家还不知道"的字段，提示 GM 可以有意识地通过叙事揭示它们
    hidden_fields: list[str] = []
    if (npc.description or "").strip() and not revealed.get("description"):
        hidden_fields.append("description")
    if (npc.purpose or "").strip() and not revealed.get("purpose"):
        hidden_fields.append("purpose")
    if (npc.archetype or "").strip() and not revealed.get("archetype"):
        hidden_fields.append("archetype")
    if (npc.state or "").strip() and not revealed.get("state"):
        hidden_fields.append("state")
    if not revealed.get("favor") and npc.favor != 0:
        hidden_fields.append("favor")
    # 检查 affinity（多维好感）是否有数据但未揭示
    if not revealed.get("affinity"):
        try:
            aff = json.loads(npc.affinity_json or "{}")
        except (TypeError, ValueError):
            aff = {}
        if isinstance(aff, dict) and aff:
            hidden_fields.append("affinity")
    # 检查 emotion（情绪状态）是否有数据但未揭示
    if not revealed.get("emotion"):
        try:
            emo = json.loads(npc.emotion_json or "{}")
        except (TypeError, ValueError):
            emo = {}
        if isinstance(emo, dict) and emo:
            hidden_fields.append("emotion")
    # 把未揭示字段名列出，明确告知 GM 不要在叙述中直接说出这些信息
    if hidden_fields:
        lines.append(
            "  [未揭示：" + "/".join(hidden_fields)
            + " — 玩家尚未通过对话或调查获悉，请勿在叙述中直接说出]"
        )

    return "\n".join(lines)  # 多行拼成一个字符串返回


# ── 简短格式：一行摘要（用于最近出现过的 NPC）──────────────────────────────
def _format_npc_short(npc: NPC) -> str:
    # 生成一行简短的 NPC 摘要，用于"最近见过但不在当前场景"的 NPC
    # 格式：- 姓名(♂/♀)（好感+10，状态：焦虑）外貌描述前40字
    #
    # 【v0.11 揭示机制】
    #   只打印玩家已知的字段；未知字段显示为 ??（GM 知道有这个维度，但看不到值）
    revealed = _effective_reveals(npc)
    # 好感度：已揭示显示数字，未揭示显示 ??
    favor_str = f"{npc.favor:+d}" if revealed.get("favor") else "??"
    # 状态：已揭示显示实际状态，未揭示显示 ??
    state_str = npc.state if revealed.get("state") else "??"
    # 描述：已揭示则显示（为空字符串则不显示），未揭示则强制为空
    desc = (npc.description or "").strip() if revealed.get("description") else ""
    gender_marker = {"male": "♂", "female": "♀"}.get((npc.gender or "").strip(), "")
    name_with_gender = f"{npc.name}({gender_marker})" if gender_marker else npc.name
    parts = f"- {name_with_gender}（好感{favor_str}，状态：{state_str}）"
    if desc:
        parts += desc[:40]  # 只取前 40 字，避免单行过长
    return parts

# ============================================================
# wizard.py — 多步骤建档向导服务
# ============================================================
# 【什么是 Wizard（向导）？】
#   新玩家创建一局游戏时，需要生成：世界观 → 角色 → NPC → 剧本。
#   Wizard 把这四步串联成一个对话式流程，每步调用不同的 LLM Prompt，
#   最后由 finalize_wizard() 一次性写入数据库。
#
# 【六个核心函数】
#   generate_world_brief:        生成世界名称、年代/地点、核心冲突（精简版）
#   generate_world_details:      把精简版扩展成完整世界观 Markdown
#   generate_character:          根据原型设定生成玩家角色
#   generate_npcs:               生成一批主要 NPC
#   generate_screenplay_from_wizard: 生成剧本大纲
#   finalize_wizard:             原子性地把所有数据写入数据库
#
# 【流式变体（stream_*）】
#   每个生成函数都有对应的流式版本，向前端实时推送 token。
#   协议：yield ("delta", {"text": "..."}) 表示 token；
#         yield ("result", {...parsed...}) 表示解析完成；
#         yield ("error", {"message": "..."}) 表示失败。
# ============================================================
import json
import logging
import re
from typing import TypeVar, Callable, Awaitable
_T = TypeVar("_T")

log = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    NPC,
    Screenplay,
    Session as GameSession,
    World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient

from dzmm.prompts.wizard_character import build_character_messages
from dzmm.prompts.wizard_world_brief import build_world_brief_messages

# 正则：匹配并剥除 LLM 可能输出的 ```json ... ``` 围栏
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(text: str) -> str:
    # 如果文本被 markdown 围栏包裹，去掉围栏
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


# 修复本地模型常见的 JSON 格式问题
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")       # 对象/数组末尾的多余逗号（如 {a:1,}）
_PY_BOOL_RE = re.compile(r"\bTrue\b|\bFalse\b|\bNone\b")  # Python 字面量（模型有时输出 True 而不是 true）
_PY_BOOL_MAP = {"True": "true", "False": "false", "None": "null"}
_DOUBLE_BRACE_RE = re.compile(r"\{\{|\}\}")           # 双花括号（模型复制了 Prompt 里的 {{模板}}）


def _extract_json(text: str) -> str:
    # 从 LLM 返回的任意文本里提取最外层的 JSON 对象（{...}）或数组（[...]）
    # 并修复常见的格式问题
    #
    # 【为什么需要这个函数？】
    #   本地模型经常在 JSON 前面加一句废话（"Here is your JSON:\n{...}"），
    #   或者有尾部逗号、Python 布尔字面量等非法 JSON 语法。
    #   这个函数先找到 JSON 的起点，再逐字符配对括号找到终点，
    #   然后清理格式问题。
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    # 把双花括号折叠成单花括号（LLM 有时把 Prompt 里的 {{...}} 当例子复制出来）
    text = _DOUBLE_BRACE_RE.sub(lambda m: m.group()[0], text)

    # 找到第一个 '{' 或 '[' 的位置，取更靠前的那个
    obj_start = text.find("{")
    arr_start = text.find("[")
    if obj_start == -1 and arr_start == -1:
        return text  # 找不到 JSON 结构，原样返回（让 json.loads 报错）
    if obj_start == -1:
        start = arr_start
    elif arr_start == -1:
        start = obj_start
    else:
        start = min(obj_start, arr_start)

    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    # 逐字符追踪括号深度，找到最外层括号的结束位置
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                # 找到了完整的 JSON，提取并清理
                extracted = text[start : i + 1]
                extracted = _TRAILING_COMMA_RE.sub(r"\1", extracted)  # 删除尾部逗号
                extracted = _PY_BOOL_RE.sub(lambda m: _PY_BOOL_MAP[m.group()], extracted)  # 修复布尔字面量
                return extracted
    # JSON 被截断了（token 超出限制）：尽力清理并返回残缺的部分
    tail = _TRAILING_COMMA_RE.sub(r"\1", text[start:])
    return _PY_BOOL_RE.sub(lambda m: _PY_BOOL_MAP[m.group()], tail)


# 合法的性别枚举值
_VALID_GENDERS = {"male", "female"}
# 性别别名映射：把用户可能输入的各种写法统一成 "male" 或 "female"
_GENDER_ALIASES = {
    "男": "male", "男性": "male", "m": "male", "boy": "male", "man": "male",
    "女": "female", "女性": "female", "f": "female", "girl": "female", "woman": "female",
}


def _normalize_gender(raw: object) -> str:
    # 把自由形式的性别输入规范化为 "male" 或 "female"（枚举值）
    # 无法识别的值返回 ""（GM Prompt 和档案系统把空值视为"未设定"）
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    if s in _VALID_GENDERS:
        return s
    return _GENDER_ALIASES.get(s, "")


def _unwrap_npc_list(data: object) -> list:
    # 兼容 LLM 返回 NPC 数据的三种常见格式：
    # 1. 裸列表：[{...}, {...}]（理想情况）
    # 2. 被包裹在对象里：{"npcs": [...]} 或 {"characters": [...]} 等
    # 3. 只返回单个 NPC（本地模型有时在只有 1 个 NPC 时省掉数组）
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 尝试常见的包装键名
        for key in ("npcs", "NPCs", "npc_list", "characters"):
            if isinstance(data.get(key), list):
                return data[key]
        # 如果是单个 NPC 对象（有 name 字段），包装成列表
        if "name" in data and isinstance(data.get("name"), str):
            log.warning(
                "wizard NPC generation returned a single object instead of an array; wrapping. keys=%s",
                sorted(data.keys()),
            )
            return [data]
    raise ValueError(f"Cannot extract NPC list from {type(data).__name__}: {str(data)[:200]}")


def _parse_section(md: str, header: str) -> str:
    # 从 Markdown 文本里提取 "## <header>" 区块的内容
    # 截止到下一个 ## 标题或文本末尾
    # 如果找不到该标题，返回空字符串
    pat = re.compile(
        rf"^##\s*{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(md)
    return m.group(1).strip() if m else ""


async def _stream_text(
    client: ModelClient, messages, max_tokens: int, json_mode: bool = False
) -> str:
    # 调用 LLM 流式接口，收集全部 token，返回完整字符串
    # 如果 LLM 返回空内容，抛出 ValueError（让 _with_retry 重试）
    #
    # 【为什么空内容要抛错？】
    #   空回复通常意味着：API 限额耗尽 / 不支持 json_mode / 鉴权失效 /
    #   推理模型（如 DeepSeek-R1）把全部输出放在隐藏的 reasoning tokens 里。
    #   直接让 json.loads 处理空字符串会报 "Expecting value: line 1 column 1"，
    #   错误信息对用户不友好。主动抛出有描述性的 ValueError 更好。
    chunks: list[str] = []
    chunk_count = 0
    async for ch in client.stream(
        messages, GenerationParams(max_tokens=max_tokens, temperature=0.85, json_mode=json_mode)
    ):
        chunk_count += 1
        if ch.delta:
            chunks.append(ch.delta)
    out = "".join(chunks).strip()
    log.debug(
        "wizard._stream_text: client=%s json_mode=%s max_tokens=%d "
        "chunks_received=%d output_chars=%d",
        getattr(client, "name", "?"), json_mode, max_tokens, chunk_count, len(out),
    )
    if not out:
        log.warning(
            "wizard._stream_text: empty output (client=%s json_mode=%s "
            "max_tokens=%d chunks=%d)",
            getattr(client, "name", "?"), json_mode, max_tokens, chunk_count,
        )
        raise ValueError(
            "LLM 返回空内容（可能：API 限额 / 模型不支持 JSON mode / "
            "鉴权失效 / 推理模型把全部输出当成隐藏 reasoning）"
        )
    return out


async def _with_retry(
    fn: Callable[[], Awaitable[_T]],
    max_attempts: int = 3,
    label: str = "wizard_call",
) -> _T:
    # 通用重试包装：对 ValueError 和 JSONDecodeError 最多重试 max_attempts 次
    # 用于处理 LLM 偶发的格式错误（本地模型有 5~10% 的概率返回格式不合法的 JSON）
    last_err: Exception = RuntimeError("no attempts made")
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            log.warning(
                "wizard[%s] attempt %d/%d failed: %s",
                label, attempt, max_attempts, str(e)[:300],
            )
    log.error(
        "wizard[%s] all %d attempts exhausted; raising last error: %s",
        label, max_attempts, str(last_err)[:300],
    )
    raise last_err  # 三次全部失败，把最后一个错误抛给调用方


def _render_brief_md(name: str, setting: str, conflict: str) -> str:
    # 把世界概要的三个字段（名称/年代地点/当下危机）渲染成 Markdown
    # 输出格式与 world_details Prompt 期望的输入格式匹配
    return (
        f"# {name.strip()}\n\n"
        f"## 时代背景\n{setting.strip()}\n\n"
        f"## ⚡ 当下危机\n{conflict.strip()}\n\n"
        "（这是世界开局时正在发生的具体冲突，PC 第 1 章会立即接触到它。）\n"
    )


def _parse_brief_json(raw: str) -> dict:
    # 解析世界概要 JSON，返回 {name, setting, conflict, raw_md}
    # raw_md 是由三个字段合成的 Markdown（给 world_details Prompt 和前端 brief_md 用）
    extracted = _extract_json(raw)
    data = json.loads(extracted)
    if not isinstance(data, dict):
        raise ValueError(f"world_brief expected JSON object, got {type(data).__name__}")
    name = str(data.get("name") or "").strip()
    setting = str(data.get("setting") or "").strip()
    conflict = str(data.get("conflict") or "").strip()
    # 三个字段都必须有内容
    if not (name and setting and conflict):
        raise ValueError(
            f"world_brief missing required fields (got: name={bool(name)}, "
            f"setting={bool(setting)}, conflict={bool(conflict)})"
        )
    return {
        "name": name,
        "setting": setting,
        "conflict": conflict,
        "raw_md": _render_brief_md(name, setting, conflict),
    }


async def generate_world_brief(genre: str, theme: str, client: ModelClient) -> dict:
    # 根据游戏类型和主题，生成世界概要（名称 + 年代/地点 + 核心冲突）
    # 带重试（json_mode=True 使用 JSON 模式，部分模型必须如此才能返回 JSON）
    log.info("wizard.world_brief: start (genre=%r theme=%r client=%s)",
             genre, theme, getattr(client, "name", "?"))
    async def _attempt():
        raw = await _stream_text(
            client, build_world_brief_messages(genre, theme), max_tokens=600,
            json_mode=True,
        )
        return _parse_brief_json(raw)
    result = await _with_retry(_attempt, label="world_brief")
    log.info("wizard.world_brief: success (name=%r)", result.get("name"))
    return result


def _parse_character_json(raw: str) -> dict:
    # 解析角色生成 JSON（{"name": "...", "profile_md": "...markdown..."}）
    # 两个 fallback 路径：
    # 1. 主路径：LLM 输出了合法 JSON
    # 2. 旧版 fallback：LLM 直接输出了 Markdown，用正则提取姓名
    try:
        data = json.loads(_extract_json(raw))
    except json.JSONDecodeError as e:
        # 如果文本看起来像被截断的 JSON（以 { 开头），抛错让 _with_retry 重试
        if raw.lstrip().startswith("{"):
            raise ValueError(
                f"character JSON appeared malformed (likely truncated): {e}; "
                f"head={raw[:120]!r}"
            ) from e

        # 旧版 fallback：模型直接返回 Markdown 而不是 JSON
        log.warning(
            "character generation returned non-JSON; falling back to markdown regex "
            "(raw_chars=%d head=%r)",
            len(raw), raw[:120],
        )
        info = _parse_section(raw, "基本信息")
        # 从 Markdown 里用正则提取姓名（排除反斜杠，防止 \n 字面量被粘连）
        m = (
            re.search(r"姓名[:：]\s*([^\s\n\\]+)", info)
            or re.search(r"姓名[:：]\s*([^\s\n\\]+)", raw)
        )
        name = m.group(1).strip("*` ") if m else "(未命名)"
        gm = (
            re.search(r"性别[:：]\s*([^\s\n*`\\]+)", info)
            or re.search(r"性别[:：]\s*([^\s\n*`\\]+)", raw)
        )
        gender = _normalize_gender(gm.group(1)) if gm else ""
        log.info(
            "character markdown-fallback: extracted name=%r gender=%r profile_md_chars=%d",
            name, gender, len(raw),
        )
        return {"name": name, "gender": gender, "profile_md": raw}

    if not isinstance(data, dict):
        raise ValueError(f"character JSON expected object, got {type(data).__name__}")
    name = str(data.get("name") or "").strip().strip("*` ")
    profile_md = str(data.get("profile_md") or "").strip()
    gender = _normalize_gender(data.get("gender"))
    # 如果 JSON 里没有 gender，尝试从 profile_md 的"性别：男/女"正则中提取
    if not gender:
        m = re.search(r"性别[:：]\s*([^\s\n*`]+)", profile_md)
        if m:
            gender = _normalize_gender(m.group(1))
    # 如果 JSON 里没有 name，从 profile_md 里提取
    if not name:
        m = re.search(r"姓名[:：]\s*([^\s\n]+)", profile_md)
        name = m.group(1).strip("*` ") if m else "(未命名)"
    if not profile_md:
        raise ValueError("character JSON missing profile_md")

    # v0.10.4: 提取基础属性（base_stats），前端 StatePanel 用于显示初始 HP/理智值等
    raw_stats = data.get("base_stats")
    base_stats: dict = {}
    if isinstance(raw_stats, dict):
        for k, v in raw_stats.items():
            if isinstance(v, (int, float)):
                base_stats[str(k)[:30]] = int(v)
    # 如果 LLM 没有生成 base_stats，或缺少 hp 字段，使用默认值
    # 确保 StatePanel 始终有东西可以显示
    if not base_stats or "hp" not in base_stats:
        base_stats = {"hp": 20, "sanity": 15, "体魄": 5, "反应": 5, "智力": 5, "意志": 5}

    return {
        "name": name, "gender": gender, "profile_md": profile_md,
        "base_stats_json": json.dumps(base_stats, ensure_ascii=False),
    }


async def generate_character(
    world_md: str, archetype: str, client: ModelClient, genre: str = ""
) -> dict:
    # 根据世界观和角色原型（archetype）生成玩家角色
    # archetype 为空时，让 LLM 自由发挥
    # genre 用于生成结构化属性（v0.15 Batch 4）
    effective_archetype = archetype.strip() or "（请根据世界观自由发挥，创造一个有深度的主角）"
    log.info(
        "wizard.character: start (archetype=%r genre=%r world_md_chars=%d client=%s)",
        archetype, genre, len(world_md), getattr(client, "name", "?"),
    )
    async def _attempt():
        # max_tokens=2500: profile_md 本身 600~1500 字符 + JSON 结构开销，
        # 1800 容易被截断导致 JSON 不合法，提高到 2500
        raw = await _stream_text(
            client, build_character_messages(world_md, effective_archetype),
            max_tokens=2500, json_mode=True,
        )
        result = _parse_character_json(raw)
        # v0.15 Batch 4: add structured stats from genre template
        from dzmm.engine.genre_templates import apply_genre_template
        tmpl = apply_genre_template(genre.strip())
        result["stat_block"] = tmpl["stat_block"]
        result["skills"] = tmpl["skills"]
        result["inventory"] = tmpl["inventory"]
        return result
    result = await _with_retry(_attempt, label="character")
    log.info(
        "wizard.character: success (name=%r profile_md_chars=%d)",
        result.get("name"), len(result.get("profile_md") or ""),
    )
    return result


async def generate_single_npc(
    world_md: str,
    character_md: str,
    hint: str,       # 玩家提供的 NPC 提示（原型/职业/名字等）
    client: ModelClient,
) -> dict:
    # 根据玩家提示生成单个 NPC
    # 使用 Message 实例而非普通 dict，确保所有模型客户端都能处理
    # （openai_compat.py 和 ollama.py 都调用 m.model_dump()，dict 会报 AttributeError）
    hint_text = hint.strip() or "（根据世界观自由发挥）"
    messages = [
        Message(
            role="system",
            content=(
                f"世界观：\n{world_md}\n\n主角：\n{character_md}\n\n"
                "你是世界观设计师。根据以下提示，生成**1个**主要 NPC，输出纯 JSON（无 markdown fence）。\n"
                "格式：{\"name\":\"...\",\"gender\":\"male 或 female（必填）\","
                "\"description\":\"...\",\"archetype\":\"...\",\"purpose\":\"...\"}"
            ),
        ),
        Message(role="user", content=f"NPC 提示：{hint_text}"),
    ]

    log.info(
        "wizard.single_npc: start (hint=%r client=%s)",
        hint_text, getattr(client, "name", "?"),
    )
    async def _attempt():
        raw = await _stream_text(client, messages, max_tokens=400, json_mode=True)
        try:
            npc = json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"single NPC JSON error: {e}; raw={raw[:200]!r}") from e
        if not isinstance(npc, dict) or not npc.get("name"):
            raise ValueError(f"invalid NPC shape: {npc!r}")
        npc["gender"] = _normalize_gender(npc.get("gender"))
        return npc

    result = await _with_retry(_attempt, label="single_npc")
    log.info("wizard.single_npc: success (name=%r)", result.get("name"))
    return result


async def finalize_wizard(
    session: AsyncSession,
    bundle: dict,  # 包含 world/character/screenplay/pinned_npcs 等所有向导收集的数据
) -> int:
    # 原子性地把向导收集的所有数据写入数据库
    # 调用方负责在成功后 commit()，失败时 rollback()
    # 本函数只 flush（让 ID 被赋值，供外键使用），不直接 commit
    #
    # 创建顺序（有外键依赖）：
    # 1. World（世界观）
    # 2. Character（玩家角色，需要 world_id）
    # 3. Session/GameSession（游戏存档，需要 world_id + character_id）
    # 3.5. CharState（角色状态，需要 session_id）
    # 4. 钉选 NPC（需要 session_id）
    # 5. Screenplay（剧本大纲，需要 session_id + world_id）
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be a dict")

    # 验证必填字段并提取
    try:
        world_data = bundle["world"]
        char_data = bundle["character"]
        sp_data = bundle["screenplay"]
        session_name = bundle["session_name"]
        gm_mid = int(bundle["gm_model_config_id"])           # GM 模型配置 ID
        sum_mid = int(bundle["summarizer_model_config_id"])  # 摘要器模型配置 ID
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"missing or invalid bundle field: {e}") from e

    if not isinstance(world_data, dict) or not isinstance(char_data, dict) \
            or not isinstance(sp_data, dict):
        raise ValueError("bundle.world / character / screenplay must be objects")

    # ── 1. 创建世界观 ───────────────────────────────────────────────────────
    world = World(
        name=str(world_data.get("name") or "(未命名世界)")[:120],
        content_md=str(world_data.get("content_md") or ""),  # 完整的世界书 Markdown
        style=str(world_data.get("style") or "realistic")[:40],
    )
    session.add(world)
    await session.flush()  # flush 后 world.id 才会被赋值

    # ── 2. 创建玩家角色（关联到世界）─────────────────────────────────────
    # v0.15 Batch 4: apply structured stat_block / skills / inventory if present
    stat_block: dict = char_data.get("stat_block") or {}
    skills_data: dict = char_data.get("skills") or {}
    inventory_data: list = char_data.get("inventory") or []

    # If not already in char_data, compute from genre template
    if not stat_block:
        from dzmm.engine.genre_templates import apply_genre_template
        tmpl = apply_genre_template(str(bundle.get("genre") or ""))
        stat_block = tmpl["stat_block"]
        skills_data = tmpl["skills"]
        inventory_data = tmpl["inventory"]

    char = Character(
        world_id=world.id,
        name=str(char_data.get("name") or "(未命名)")[:120],
        gender=_normalize_gender(char_data.get("gender")),
        profile_md=str(char_data.get("profile_md") or ""),
        base_stats_json=str(char_data.get("base_stats_json") or "{}"),
        # D&D attributes
        strength=int(stat_block.get("strength", 10)),
        dexterity=int(stat_block.get("dexterity", 10)),
        constitution=int(stat_block.get("constitution", 10)),
        intelligence=int(stat_block.get("intelligence", 10)),
        wisdom=int(stat_block.get("wisdom", 10)),
        charisma=int(stat_block.get("charisma", 10)),
        # Max vitals
        max_hp=int(stat_block.get("max_hp", 30)),
        max_sanity=int(stat_block.get("max_sanity", 50)),
        max_stamina=int(stat_block.get("max_stamina", 30)),
        # Skills + inventory
        skills_json=json.dumps(skills_data, ensure_ascii=False),
        inventory_json=json.dumps(inventory_data, ensure_ascii=False),
    )
    session.add(char)
    await session.flush()

    # ── 3. 创建游戏存档（关联到世界 + 角色 + 两个模型配置）────────────────
    sess = GameSession(
        name=str(session_name or "(未命名存档)")[:120],
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=gm_mid,        # GM 使用的模型
        summarizer_model_config_id=sum_mid,  # 摘要器使用的模型
    )
    session.add(sess)
    await session.flush()

    # ── 3.5. 创建角色状态（wizard 路径漏掉了这一步，v0.10.4 补上）──────
    # 之前 wizard 路径没有创建 CharState，导致前端"角色状态/背包"永远空白
    # 从 Character.base_stats_json 复制初始属性值
    from dzmm.db.models import CharState
    session.add(CharState(
        session_id=sess.id,
        stats_json=char.base_stats_json or "{}",
    ))

    # ── 4. 创建钉选 NPC（剧本预设的主要角色）──────────────────────────────
    # v0.2.2: 初始只揭示姓名，其他字段等玩家在游戏中遇到后再逐步揭示
    # 之前全部揭示导致开局"剧透感"过强
    revealed_name_only = json.dumps({"name": True})
    created_npcs: list[NPC] = []
    for npc_data in (bundle.get("pinned_npcs") or []):
        if not isinstance(npc_data, dict):
            continue
        name = str(npc_data.get("name") or "").strip()
        if not name:
            continue
        npc = NPC(
            session_id=sess.id,
            name=name[:120],
            gender=_normalize_gender(npc_data.get("gender")),
            description=str(npc_data.get("description") or "")[:1000],
            purpose=str(npc_data.get("motivation") or npc_data.get("purpose") or "")[:1000],
            archetype=str(npc_data.get("role") or npc_data.get("archetype") or "")[:120],
            pinned=True,                    # 标记为钉选（剧本主要角色）
            revealed_json=revealed_name_only,  # 只揭示姓名
        )
        session.add(npc)
        created_npcs.append(npc)

    # ── 5. 创建剧本大纲 ──────────────────────────────────────────────────
    # world_id: 删存档时剧本可以保留（关联到世界而不只是存档），
    # 下次新建存档可以复用同一个剧本
    sp = Screenplay(
        session_id=sess.id,
        world_id=world.id,
        version=1,
        genre=str(bundle.get("genre") or "")[:60],
        pc_name=char.name,           # 把 PC 信息也存在剧本里，方便续作复用
        pc_gender=char.gender,
        pc_profile_md=char.profile_md,
        pc_base_stats_json=char.base_stats_json,
        chapters_json=json.dumps(sp_data.get("chapters", []), ensure_ascii=False),
        main_characters_json=json.dumps(
            sp_data.get("main_characters", []), ensure_ascii=False
        ),
        ending_md=str(sp_data.get("ending_md") or sp_data.get("ending") or "")[:2000],
        opening_hook=str(sp_data.get("opening_hook") or "")[:2000],
        current_chapter=1,
        completed_events_json="[]",
        status="active",
    )
    session.add(sp)
    await session.flush()

    # 刷新 NPC 行，确保 npc.id 已被赋值
    for npc in created_npcs:
        await session.refresh(npc)

    # 返回新建记录的 ID，供调用方后续操作使用
    return {
        "session_id": sess.id,
        "world_id": world.id,
        "npc_ids": {npc.name: npc.id for npc in created_npcs},  # 名字 → ID 的映射
    }


# ============================================================
# 流式变体（Streaming Variants）
# ============================================================
# 每个生成函数都有对应的 stream_* 版本，通过 async generator 向前端推送进度。
# 协议（SSE 事件类型）：
#   "delta"  → {"text": "..."} : 每个 token 片段（实时显示给用户）
#   "result" → {...解析结果...} : 全部 token 收集完且 JSON 解析成功
#   "error"  → {"message": "..."} : 解析失败
# ============================================================

from collections.abc import AsyncGenerator  # noqa: E402

_StreamYield = AsyncGenerator[tuple[str, dict], None]


async def stream_world_brief(genre: str, theme: str, client: ModelClient) -> _StreamYield:
    # 流式生成世界概要，边生成边推 delta 给前端
    messages = build_world_brief_messages(genre, theme)
    chunks: list[str] = []
    async for ch in client.stream(
        messages, GenerationParams(max_tokens=800, temperature=0.85, json_mode=True),
    ):
        if ch.delta:
            chunks.append(ch.delta)
            yield "delta", {"text": ch.delta}  # 立即推送每个 token
    raw = "".join(chunks).strip()
    try:
        result = _parse_brief_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        log.warning("stream_world_brief JSON parse failed: %s; raw=%r", e, raw[:200])
        yield "error", {"message": f"基础设定 JSON 解析失败：{e}"}
        return
    yield "result", result  # 推送最终解析结果



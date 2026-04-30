"""Outliner LLM prompt — generates a structured screenplay (chapters + key events
+ main NPCs + ending + opening hook) from world+character+genre. Output is
strict JSON for the backend to parse and persist."""
from dzmm.models.client import Message

KNOWN_GENRES: dict[str, str] = {
    "悬疑探案": "PC 是侦探或调查者，剧情围绕解开一桩谜案，逐步揭开真相，最终对峙幕后黑手。",
    "英雄成长": "PC 从普通人或半吊子起步，遇到挫折后逐步成长，最终面对足以改变世界的关键挑战。",
    "政治阴谋": "PC 卷入派系斗争，要在多方势力间斡旋、收集情报、做出立场选择，最终决定一方胜负。",
    "灾难求生": "PC 处于灾难（瘟疫 / 末日 / 战争 / 自然灾害）中，资源稀缺，需要带领或保护一群人活下去。",
    "恋爱攻略": "PC 与 1-2 位主要 NPC 发展深度关系，关系是剧情核心驱动；外部冲突服务于关系试炼。",
}


_OUTLINER_SYSTEM = """你是一位经验丰富的 TRPG 编剧。你的任务是根据玩家提供的世界设定、PC 角色卡、故事类型，
生成一份结构化的「剧本大纲」（outline）给 GM 用。

# 输出格式（必须严格的 JSON，不要 markdown 代码块包裹）

{{
  "chapters": [
    {{
      "title": "第一章：副标题",
      "summary": "本章 50-80 字概要",
      "main_events": ["主线事件 1（必演）", "主线事件 2（必演）"],
      "optional_events": ["分支事件 1（PC 探索才触发）", "分支事件 2"],
      "main_npcs": ["本章重要 NPC 名"]
    }}
  ],
  "main_characters": [
    {{"name": "NPC 名", "role": "盟友/对手/导师/...", "description": "30-60 字", "intro_chapter": 1}}
  ],
  "ending": "60-100 字描述故事的最终高潮和闭幕条件",
  "opening_hook": "100-200 字开篇引子，给玩家看作为开局，**绝不剧透后续章节**——只交代起点环境、PC 处境、最初的契机"
}}

# 章节数量
3-5 章。少于 3 章故事单薄，多于 5 章节奏拖沓。

# 设计要求
1. 每章 main_events 2-4 个，optional_events 1-3 个
2. main_npcs 在 intro_chapter 章节首次登场
3. ending 是 PC 必须达成或破坏的最终目标，要具体不要抽象
4. opening_hook 写得像小说开篇——画面感、感官、悬念，但**不能告诉玩家后面会发生什么**
5. 整套大纲要紧扣故事类型（genre）的套路
6. PC 的能力 / 物品 / 弱点（profile_md 里有）应在 main_events 中找到至少一处可以用上 / 受挑战的场景

# 强约束
- 输出必须是合法 JSON，不要前后加任何文字
- 字段名严格按上面 schema
- 不输出 markdown 代码块标记 ```json
"""


def build_outliner_messages(
    world_name: str,
    world_md: str,
    character_name: str,
    character_md: str,
    genre: str,
    custom_prompt: str = "",
) -> list[Message]:
    user_lines = [
        f"# 世界：{world_name}",
        world_md.strip()[:1500],
        "",
        f"# PC：{character_name}",
        character_md.strip()[:1500],
        "",
        f"# 故事类型：{genre}",
    ]
    if genre in KNOWN_GENRES:
        user_lines.append(f"类型说明：{KNOWN_GENRES[genre]}")
    if custom_prompt.strip():
        user_lines.append("# 玩家自定义补充")
        user_lines.append(custom_prompt.strip()[:1000])
    user_lines.append("")
    user_lines.append("现在生成完整的剧本大纲 JSON。")

    return [
        Message(role="system", content=_OUTLINER_SYSTEM),
        Message(role="user", content="\n".join(user_lines)),
    ]

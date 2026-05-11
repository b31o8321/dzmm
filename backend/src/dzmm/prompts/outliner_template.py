"""Outliner LLM prompt — generates a structured screenplay (chapters + key events
+ main NPCs + ending + opening hook) from world+character+genre. Output is
strict JSON for the backend to parse and persist."""
# ============================================================
# 剧本大纲生成器（Outliner）提示词
# ============================================================
# 【Outliner 的职责】
#   玩家创建新游戏时，系统会调用 Outliner：
#   给它世界观、角色卡、故事类型，它输出一份结构化的「剧本大纲」（JSON）。
#   这个大纲包含：章节列表、每章的事件、主要 NPC、结局条件、开篇引子。
#   GM 在游戏过程中会读取这个大纲，按照章节顺序推进剧情。
#
# 【为什么输出 JSON 而不是自然语言？】
#   自然语言的大纲只有人能读，程序无法解析。
#   JSON 格式的大纲可以直接存入数据库，后端可以：
#   - 追踪哪些事件已完成（state: pending/done）
#   - 自动判断是否该触发 <event_complete>
#   - 根据 keywords 列表判断"这回合是否触发了某个事件"
#
# 【两个函数的区别】
#   build_outliner_messages()：首次生成大纲（游戏开始前）
#   build_rewrite_messages()：玩家做出重大决策后，重写未完成章节
#                            （已完成的章节不能改变，只改写未来）
# ============================================================
from dzmm.models.client import Message

# 已知故事类型及其说明：用于给 LLM 更清晰的类型指导
# 键：类型名（前端下拉选项）  值：对该类型的详细说明
KNOWN_GENRES: dict[str, str] = {
    "悬疑探案": "PC 是侦探或调查者，剧情围绕解开一桩谜案，逐步揭开真相，最终对峙幕后黑手。",
    "英雄成长": "PC 从普通人或半吊子起步，遇到挫折后逐步成长，最终面对足以改变世界的关键挑战。",
    "政治阴谋": "PC 卷入派系斗争，要在多方势力间斡旋、收集情报、做出立场选择，最终决定一方胜负。",
    "灾难求生": "PC 处于灾难（瘟疫 / 末日 / 战争 / 自然灾害）中，资源稀缺，需要带领或保护一群人活下去。",
    "恋爱攻略": "PC 与 1-2 位主要 NPC 发展深度关系，关系是剧情核心驱动；外部冲突服务于关系试炼。",
}


# Outliner 的系统提示词：定义 LLM 的角色和输出格式要求
# 输出必须是严格的 JSON，后端会用 json.loads() 解析它
_OUTLINER_SYSTEM = """你是一位经验丰富的 TRPG 编剧。你的任务是根据玩家提供的世界设定、PC 角色卡、故事类型，
生成一份结构化的「剧本大纲」（outline）给 GM 用。

# 输出格式（必须严格的 JSON，不要 markdown 代码块包裹）

{
  "chapters": [
    {
      "title": "第一章：副标题",
      "summary": "本章 50-80 字概要",
      "main_locations": ["本章主要场所1", "场所2", "场所3"],
      "main_events": [
        {
          "description": "主线事件描述（20-40字）",
          "keywords": ["触发关键词1", "关键词2", "关键词3"],
          "criteria": "完成标准：具体可判断的一句话（15-25字）"
        }
      ],
      "optional_events": [
        {
          "description": "支线事件描述",
          "keywords": ["关键词1", "关键词2"],
          "criteria": "完成标准"
        }
      ],
      "main_npcs": ["本章重要 NPC 名"]
    }
  ],
  "main_characters": [
    {"name": "NPC 名", "role": "盟友/对手/导师/...", "description": "30-60 字",
     "intro_chapter": 1, "primary_location": "该 NPC 常驻 / 主活动场所"}
  ],
  "ending": "60-100 字描述故事的最终高潮和闭幕条件",
  "opening_hook": "100-200 字开篇引子，给玩家看作为开局，**绝不剧透后续章节**——只交代起点环境、PC 处境、最初的契机"
}

# 章节数量
3-5 章。少于 3 章故事单薄，多于 5 章节奏拖沓。

# 设计要求
1. 每章 main_events 2-4 个，optional_events 1-3 个
2. main_npcs 在 intro_chapter 章节首次登场
3. ending 是 PC 必须达成或破坏的最终目标，要具体不要抽象
4. opening_hook 写得像小说开篇——画面感、感官、悬念，但**不能告诉玩家后面会发生什么**
5. 整套大纲要紧扣故事类型（genre）的套路
6. PC 的能力 / 物品 / 弱点（profile_md 里有）应在 main_events 中找到至少一处可以用上 / 受挑战的场景
7. 每个事件的 keywords 3-5 个（名词或动词短语，GM 在 narrative/PC行动中看到这些词时应推进该事件）
8. 每个事件的 criteria 是 15-25 字的具体条件，GM 确认满足后立即 emit <event_complete>
9. **场所约束（v0.10.5，防 NPC 凭空出场）**：
   - 每章 `main_locations` 列 2-4 个本章主要场所（具体地名，不要泛指）
   - 每个 `main_character` 的 `primary_location` 是他/她的常驻场所
     （家、工作地、活动据点等）；该值**必须出现在他/她 `intro_chapter`
     那章的 `main_locations` 列表里**，否则 PC 永远不可能在该章里"自然遇见"他/她
   - 把它当作 NPC 与场景的物理绑定——GM 引入新 NPC 时只能在 primary_location
     里直接相遇，否则得先铺垫

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
    # 构建给 Outliner LLM 的消息列表（首次生成大纲）。
    # 用户消息包含：世界观、角色卡、故事类型、玩家自定义补充。
    # [:1500] 截断：防止超长输入占用太多 token，
    #   如果玩家角色卡写得太详细（超过 1500 字），只取前 1500 字。
    user_lines = [
        f"# 世界：{world_name}",
        world_md.strip()[:1500],   # 最多取 1500 字
        "",
        f"# PC：{character_name}",
        character_md.strip()[:1500],
        "",
        f"# 故事类型：{genre}",
    ]
    # 如果是已知类型，追加详细说明；自定义类型则跳过（LLM 自行推断）
    if genre in KNOWN_GENRES:
        user_lines.append(f"类型说明：{KNOWN_GENRES[genre]}")
    # 玩家可以在 UI 里填写额外要求（比如"我希望有个书店"）
    if custom_prompt.strip():
        user_lines.append("# 玩家自定义补充")
        user_lines.append(custom_prompt.strip()[:1000])  # 补充内容最多 1000 字
    user_lines.append("")
    user_lines.append("现在生成完整的剧本大纲 JSON。")

    return [
        Message(role="system", content=_OUTLINER_SYSTEM),
        Message(role="user", content="\n".join(user_lines)),
    ]


# 剧本重写的系统提示词（重大决策后重写未完成章节）
_REWRITE_SYSTEM = """你是一位经验丰富的 TRPG 编剧，正在**改写现有剧本**。
玩家做了一个重大决定，会影响剧情走向；你的任务是基于这个决定**重写未完成的章节**。

# 输出格式（必须严格的 JSON，不要 markdown 代码块包裹）

{
  "chapters": [<整套新章节，结构与初版相同：title/summary/main_events/optional_events/main_npcs>],
  "main_characters": [<可选：新增或修改的 NPC>],
  "ending": "<可能修改的结局>",
  "diff_summary": "<60-120 字总结：相比原版改了什么、为什么>"
}

# 改写约束（重要）

1. **已完成的章节不可改**——保持 1..N（current_chapter-1）不动；只重写从 current_chapter 起到结尾
2. **已发生的事件是事实**——剧情方向可变，但不能让历史回滚
3. **PC 决定的影响要可见**——新章节里至少 1-2 处情节直接由这个决定衍生（NPC 反应 / 新势力出现 / 旧线断裂等）
4. **章节数量保持** 3-5 章，不要因重写大幅扩张或塌缩
5. **diff_summary** 用第三人称写，给玩家看的，例如「PC 选择投靠魔王后，第 3-5 章重心从拯救公主转为颠覆王权，新增暗影教团作为对手势力」

# 强约束
- 输出必须是合法 JSON
- chapters 字段是完整 chapters 数组（包括未改动的 1..current_chapter-1）
- 不要 markdown 代码块标记 ```json
"""


def build_rewrite_messages(
    world_name: str,
    world_md: str,
    character_name: str,
    character_md: str,
    genre: str,
    current_chapters_json: str,    # 当前大纲的 JSON 字符串（已完成和未完成的所有章节）
    current_chapter: int,          # 当前进行到第几章（从 1 开始）
    completed_events_summary: str, # 已完成事件的摘要（不可回滚的历史）
    decision_description: str,     # 玩家的重大决策描述（触发重写的原因）
    custom_prompt: str = "",
) -> list[Message]:
    """Messages for major-plot-turn rewrite. Reuses _REWRITE_SYSTEM and feeds
    current outline + history + decision so the model can produce a partial
    rewrite (preserving completed chapters)."""
    # 用户消息包含：世界观、角色卡、当前大纲 JSON、已完成事件、玩家决策
    # 截断长度比首次生成时更短（世界观用 1000 字，角色卡用 800 字），
    # 因为还需要放入当前大纲 JSON（最多 4000 字），总体控制在 token 预算内
    user_lines = [
        f"# 世界：{world_name}",
        world_md.strip()[:1000],
        "",
        f"# PC：{character_name}",
        character_md.strip()[:800],
        "",
        f"# 故事类型：{genre}",
    ]
    if genre in KNOWN_GENRES:
        user_lines.append(f"类型说明：{KNOWN_GENRES[genre]}")
    user_lines.extend([
        "",
        f"# 当前章节进度：第 {current_chapter} 章",
        "",
        "# 现有大纲（chapters JSON，作为上下文，重写时保留 1..current_chapter-1 章）",
        current_chapters_json[:4000],   # 大纲 JSON 最多 4000 字
    ])
    # 已完成事件：LLM 重写时必须把这些当作既成事实
    if completed_events_summary.strip():
        user_lines.extend(["", "# 已完成的关键事件（不可回滚）", completed_events_summary.strip()[:1000]])
    user_lines.extend([
        "",
        "# 玩家刚做出的重大决定（重写起点）",
        decision_description.strip()[:800],
    ])
    if custom_prompt.strip():
        user_lines.extend(["", "# 玩家自定义补充", custom_prompt.strip()[:500]])
    user_lines.extend([
        "",
        "现在输出改写后的完整 JSON。",
    ])
    return [
        Message(role="system", content=_REWRITE_SYSTEM),
        Message(role="user", content="\n".join(user_lines)),
    ]

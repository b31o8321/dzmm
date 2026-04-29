from dzmm.models.client import Message

_TEMPLATE = """你是一个 TRPG 剧情归档员。任务：把一段已发生的跑团对话压缩成简洁的剧情摘要，供 GM 在后续跑团中回顾。

# 已有摘要（截至上次归档）
{previous_summary}

# 待归档的新对话片段
{new_messages}

# 当前关键事实快照（不要重复这些信息，仅供你理解上下文）
{key_facts}

# 输出要求
1. 把已有摘要和新对话融合成**新的单一摘要**（不是续写，是融合）
2. 摘要长度控制在 800 字以内
3. 保留：关键剧情转折、与 NPC 的关键互动、已揭示的世界观信息、伏笔与悬念
4. 删除：例行对话、过场描写、已在关键事实中记录的信息
5. 用第三人称过去时叙述，保持风格中立
6. 重大转折用「【转折】」标记

直接输出新摘要正文，不要任何前后缀。
"""


def build_summarizer_messages(
    previous_summary: str,
    new_messages_text: str,
    key_facts: str,
) -> list[Message]:
    user = _TEMPLATE.format(
        previous_summary=previous_summary.strip() or "（首次归档）",
        new_messages=new_messages_text.strip() or "（无）",
        key_facts=key_facts.strip() or "（暂无）",
    )
    return [Message(role="user", content=user)]


_COMPRESSION_TEMPLATE = """你是一个 TRPG 长线归档员。下面这段剧情摘要太长了，需要：

1. 把它压缩到 600 字以内的精炼版（保留剧情骨架、关键 NPC、未解伏笔）
2. 同时把其中"独立成事件"的高亮（NPC 首次相遇、重大转折、伏笔回收）以下面格式输出：

<event importance="3">大转折/核心 NPC 首次登场，对剧情走向有持续影响</event>
<event importance="2">重要的支线进展或人物关系变化</event>
<event importance="1">细节，可以省略</event>

# 待压缩的摘要
{long_summary}

# 输出要求
- 第一行起到一个空行为止，是新的精炼摘要正文
- 之后以 <event> 标签罗列至少 2 条 importance≥2 的事件
- 不要任何额外说明文字、Markdown 标题
"""


def build_compression_messages(long_summary: str) -> list[Message]:
    return [Message(role="user", content=_COMPRESSION_TEMPLATE.format(long_summary=long_summary))]

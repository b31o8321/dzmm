from dzmm.models.client import Message

_TEMPLATE = """你是一个 TRPG 剧情归档员。任务：把一段已发生的跑团对话压缩成摘要，并提取关键事实清单，供 GM 在后续跑团中回顾。

# 已有摘要（截至上次归档）
{previous_summary}

# 待归档的新对话片段
{new_messages}

# 当前关键事实快照（仅供理解上下文，不要原样复制）
{key_facts}

# 输出格式（严格遵守）

## 剧情摘要
把已有摘要和新对话融合成新的单一摘要（不是续写）。长度 600-800 字。
保留：关键剧情转折、NPC 关键互动、已揭示的世界观信息、伏笔与悬念。
删除：例行对话、过场描写。第三人称过去时，重大转折用「【转折】」标记。

## 关键事实清单
以下各栏**逐条**罗列，空栏写"无"。保留所有已出现的信息（新旧合并，不覆盖）：

### 登场 NPC
格式：「名字」— 身份/特征一句话；与 PC 关系；已知动机（如有）
（每个曾登场的有名 NPC 一行，包括本次新出场的）

### 重要地点
格式：「地点名」— 位置/特征一句话

### NPC 承诺 / 协议
格式：「NPC」承诺了「内容」（第 N 回合）

### 已揭示秘密
格式：关于「X」：内容一句话

### 待解悬念
格式：- 悬念描述（和哪个 NPC/地点相关）

直接输出，不要任何额外前缀或说明。
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


_COMPRESSION_TEMPLATE = """你是一个 TRPG 长线归档员。下面的剧情摘要（含关键事实清单）太长了，需要精简。

# 待压缩的摘要
{long_summary}

# 输出要求

## 剧情摘要
把"剧情摘要"部分压缩到 400 字以内的精炼版（保留剧情骨架、关键 NPC、未解伏笔）。

## 关键事实清单
把原"关键事实清单"合并、去重后原样保留（允许合并相同 NPC 的多行信息）。
各栏目标题保持不变：「登场 NPC」「重要地点」「NPC 承诺 / 协议」「已揭示秘密」「待解悬念」。

<event importance="3">对剧情走向有持续影响的大转折或核心 NPC 首次登场</event>
<event importance="2">重要的支线进展或人物关系变化</event>

输出顺序：先 ## 剧情摘要，再 ## 关键事实清单，最后 <event> 标签（至少 2 条 importance≥2）。
不要任何额外说明文字。
"""


def build_compression_messages(long_summary: str) -> list[Message]:
    return [Message(role="user", content=_COMPRESSION_TEMPLATE.format(long_summary=long_summary))]

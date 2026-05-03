# LLM 工程化实现

> 这里讲的是"调 LLM API"之外的工程问题：如何让 LLM 稳定地按你想要的方式工作。

---

## 1. LLM 客户端抽象层

### 为什么要抽象？

本地用 Ollama，云端用 OpenAI 兼容接口。业务代码不应该知道底层是哪个，否则换模型要改很多地方。

### 抽象接口

[`models/client.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/client.py)：

```python
class ModelClient(ABC):
    name: str
    
    @abstractmethod
    def stream(self, messages: list[Message], params: GenerationParams) -> AsyncIterator[StreamChunk]:
        """子类必须实现的流式生成接口。"""
        ...
    
    async def complete(self, messages, params) -> tuple[str, TokenUsage]:
        """等待全部生成完再返回。默认实现：收集 stream() 的所有片段。"""
        parts = []
        usage = TokenUsage()
        async for chunk in self.stream(messages, params):
            parts.append(chunk.delta)
            if chunk.usage is not None:
                usage = chunk.usage
        return "".join(parts), usage
```

### Ollama 具体实现

[`models/ollama.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/ollama.py)：

```python
class OllamaClient(ModelClient):
    async def stream(self, messages, params) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],   # Pydantic → dict
            "stream": True,
            "options": {"temperature": params.temperature, "num_predict": params.max_tokens, "num_ctx": 8192},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                async for line in resp.aiter_lines():
                    obj = json.loads(line)
                    done = obj.get("done", False)
                    yield StreamChunk(
                        delta=(obj.get("message") or {}).get("content", ""),
                        finish_reason="stop" if done else None,
                        usage=TokenUsage(
                            input_tokens=obj.get("prompt_eval_count", 0),
                            output_tokens=obj.get("eval_count", 0),
                        ) if done else None,
                    )
```

**Ollama API 响应格式（每行一个 JSON）：**
```json
{"message": {"content": "你"}, "done": false}
{"message": {"content": "站"}, "done": false}
{"message": {"content": "在"}, "done": false}
{"done": true, "prompt_eval_count": 1200, "eval_count": 45}
```

---

## 2. Prompt 组装：动态注入 DB 状态

GM 的 System Prompt 分两部分：**静态模板**（铁律/角色定义）+ **动态 Key Facts**（当前 DB 状态）。

### 静态模板

[`prompts/gm_template.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/prompts/gm_template.py) 里有一个很长的 `_SYSTEM_TEMPLATE`，定义了：
- GM 的角色身份
- 必须用 XML 标签输出的格式规范
- 27 条铁律（不可违反的规则）
- Few-shot 示例（正确输出的例子）

### 动态 Key Facts

[`service/game.py` 的 `_build_key_facts()`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py) 每回合从数据库读取状态并拼成文本注入 Prompt：

```python
async def _build_key_facts(session, session_id, turn_count, char):
    parts = []

    # ① 当前地点 + 场景内物品
    current_loc = (await session.execute(
        select(Location).where(Location.session_id == session_id, Location.is_current == True)
    )).scalar_one_or_none()
    if current_loc:
        parts.append(f"## 当前地点\n{current_loc.name}：{current_loc.description}")

    # ② 活跃 NPC（只注入 is_current 地点的 NPC，减少 Token 占用）
    npcs = (await session.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()
    active_npcs = [n for n in npcs if n.state != "离开" and n.pinned or n.last_seen_turn > turn_count - 5]
    if active_npcs:
        npc_lines = [f"- {n.name}：好感 {n.favor}，状态 {n.state}" for n in active_npcs]
        parts.append("## 当前 NPC\n" + "\n".join(npc_lines))

    # ③ 剧本进度
    sp = (await session.execute(
        select(Screenplay).where(Screenplay.session_id == session_id, Screenplay.status == "active")
    )).scalar_one_or_none()
    if sp:
        chapters = json.loads(sp.chapters_json)
        current = chapters[sp.current_chapter - 1] if sp.current_chapter <= len(chapters) else None
        if current:
            events_status = ...
            parts.append(f"## 当前剧本进度（GM 严格遵守主线）\n当前章节：第 {sp.current_chapter} 章\n{events_status}")

    # ④ 场景滞留压力（超过阈值时注入强制推进指令）
    stc = sess.scene_turn_count or 0
    if stc >= SCENE_HARD_EXIT_TURNS:
        parts.append(f"🚨 场景强推（已在「{loc_name}」滞留 {stc} 回合）...")
    elif stc >= SCENE_SOFT_PRESSURE_TURNS:
        parts.append(f"⏰ 场景时间提醒（已在「{loc_name}」{stc} 回合）...")

    return "\n\n".join(parts)
```

### 最终组装成 LLM 消息

[`service/game.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)：

```python
msgs = build_gm_messages(
    world_md=world.content_md,        # 世界设定
    character_md=character_md,        # 角色卡
    live_state=live_state,            # 当前属性值
    rules_mode=rules_mode,            # light / standard / hardcore
    style=world.style,                # 世界风格
    story_summary=story_summary,      # 历史摘要（已压缩的早期消息）
    key_facts=key_facts,              # 动态注入的当前状态
    recent_messages=recent,           # 最近 N 条原始消息
    current_action=user_action,       # 玩家本回合输入
)
```

---

## 3. 流式 XML 解析：实时边解析边推送

### 问题

LLM 输出这样的内容：
```
<narrative>你走进酒馆，灯光昏黄。</narrative><npc_update name="老板">注意到你</npc_update>
```

但它是逐字符推送的，可能这次收到 `<narr`，下次才收到 `ative>`，不能等凑齐再解析。

### 状态机实现

[`parsing/stream_parser.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/parsing/stream_parser.py) 维护 4 种状态：

```
OUTSIDE       在任何标签外，等待开标签
IN_STREAMING  在 <narrative> 内，每收到字符立刻 yield NarrativeDelta
IN_BUFFERED   在其他已知标签内，缓冲到闭合再整体处理
IN_UNKNOWN    在未知标签内，静默丢弃
```

```python
class StreamingTagParser:
    def feed(self, chunk: str) -> list[ParseEvent]:
        self._buf += chunk
        events = []
        while True:
            if self._state == "OUTSIDE":
                m = _OPEN_TAG_RE.search(self._buf)    # 找下一个开标签
                if not m:
                    break
                tag = m.group(1).lower()
                self._buf = self._buf[m.end():]        # 消费掉开标签
                if tag == "narrative":
                    self._state = "IN_STREAMING"
                elif tag in KNOWN_TAGS:
                    self._state = "IN_BUFFERED"

            elif self._state == "IN_STREAMING":
                exact_idx = self._buf.find(f"</{self._current_tag}>")
                if exact_idx == -1:
                    # 还没找到闭合标签，安全推出前面的部分
                    safe_len = max(0, len(self._buf) - len(f"</{self._current_tag}>") - 2)
                    if safe_len > 0:
                        events.append(NarrativeDelta(self._buf[:safe_len]))   # 立刻推给前端！
                        self._buf = self._buf[safe_len:]
                    break
                else:
                    events.append(NarrativeDelta(self._buf[:exact_idx]))      # 最后一段
                    self._buf = self._buf[exact_idx + len(f"</{self._current_tag}>"):]
                    self._state = "OUTSIDE"
        return events
```

### 容错：拼写错误的闭合标签

LLM 有时输出 `</narriative>` 而不是 `</narrative>`。用编辑距离检测：

```python
def _is_typo_close(opened: str, found: str) -> bool:
    if abs(len(opened) - len(found)) > 2:
        return False
    ratio = SequenceMatcher(None, opened, found).ratio()
    if ratio < 0.7:
        return False
    return _edit_distance(opened, found) <= 2    # 最多允许 2 个字符的差异
```

---

## 4. 上下文窗口管理

### 问题

LLM 的 Context Window 有限。把所有历史消息塞进 Prompt：
1. 超长被截断（丢失关键信息）
2. 注意力分散，质量下降（实测 70 回合后 LLM 开始重复 few-shot 示例）

### 方案1：自适应窗口

[`service/game.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)：

```python
RECENT_WINDOW_DEFAULT = 12    # 0-30 回合：保留最近 12 条消息
RECENT_WINDOW_LONG_GAME = 8   # 30-60 回合：8 条
RECENT_WINDOW_VERY_LONG = 6   # 60+ 回合：6 条

def _recent_window_for(turn_count: int) -> int:
    if turn_count > 60: return RECENT_WINDOW_VERY_LONG
    if turn_count > 30: return RECENT_WINDOW_LONG_GAME
    return RECENT_WINDOW_DEFAULT
```

越往后，历史摘要质量越高，原文需要的越少。

### 方案2：摘要器

[`service/summarizer.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/summarizer.py)：

```python
SUMMARIZE_TRIGGER_TURNS = 10    # 每 10 回合触发一次摘要

async def maybe_summarize(session, session_id, client) -> bool:
    sess = await session.get(GameSession, session_id)
    if sess.turn_count < SUMMARIZE_TRIGGER_TURNS:
        return False
    
    # 只摘要 last_summarized_msg_id 之后的新消息
    new_msgs = (await session.execute(
        select(MessageRow)
        .where(MessageRow.session_id == session_id)
        .where(MessageRow.id > high_water)
        .order_by(MessageRow.id)
    )).scalars().all()
    
    if len(new_msgs) < SUMMARIZE_TRIGGER_TURNS * 2:
        return False                    # 新内容不够多，不触发
    
    new_text = "\n\n".join(f"[{m.role}] {m.content}" for m in new_msgs)
    
    # 用 LLM 把旧消息压缩成摘要
    summary_text, usage = await client.complete(
        build_summarizer_messages(previous_summary=prev, new_messages_text=new_text),
        GenerationParams(temperature=0.3, max_tokens=1500),
    )
    
    summary_row.summary_text = summary_text.strip()
    summary_row.last_summarized_msg_id = new_msgs[-1].id
    return True
```

**摘要后的 Prompt 结构：**
```
[早期历史 → 摘要文本（几百字）]
[最近 N 条 → 完整原文]
[当前回合输入]
```

---

## 5. 剧情推进机制

### 问题

LLM 默认行为是"在当前场景反复细化"，不会主动推进故事。实测：在第一个酒馆可以聊 30+ 回合不动。

### 方案1：场景回合预算

每进入新地点重置计数器，超过阈值注入压力指令：

```python
# service/game.py
SCENE_SOFT_PRESSURE_TURNS = 4
SCENE_HARD_EXIT_TURNS = 7

def _update_scene_turn_count(sess, completed_tags):
    """有 location_enter 标签 → 进入新地点 → 重置；否则递增。"""
    if any(t.name == "location_enter" for t in completed_tags):
        sess.scene_turn_count = 1
    else:
        sess.scene_turn_count += 1
```

注入的压力文本（在 `_build_key_facts` 里）：

```python
if stc >= SCENE_HARD_EXIT_TURNS:
    # 7 回合：强制推进，给 3 个具体方案
    directive = f"""🚨 场景强推（已在「{loc_name}」滞留 {stc} 回合）
    本回合必须让 PC 离开当前地点或触发重大事件。可选方案：
    a. 外部事件打断（有人冲进来、爆炸、命令）
    b. NPC 主动推动（提供新线索/任务/威胁）
    c. 环境变化（时间流逝、危险逼近）
    🚫 禁止：本回合不得让 PC 继续在此地停留做同类事情。"""
elif stc >= SCENE_SOFT_PRESSURE_TURNS:
    # 4 回合：温和提醒
    directive = f"⏰ 已在「{loc_name}」{stc} 回合，考虑推进场景。"
```

### 方案2：剧本大纲约束

开局 LLM 生成结构化剧本，每回合把进度注入 Prompt：

```
## 当前剧本进度（GM 严格遵守主线）
当前章节：第 1 章「序章：初入门派」（共 3 章）
本章主线（必须演完才能推进下章）：
- [done] 与师父初次见面
- [pending] 参加入门考核  ← GM 看到这个，知道需要触发考核场景
- [pending] 结识同门师兄
推进规则：主线 [pending] 事件完成后才能进入下一章。
```

**GM 完成事件时发出标签（[`service/state_apply/screenplay.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/state_apply/screenplay.py)）：**
```xml
<event_complete id="2" chapter="1"/>
```

---

## 6. 弱模型容错：JSON 解析三级降级

开局生成剧本大纲时，7B 模型常常输出格式错误的 JSON。

[`service/game.py` `_auto_generate_screenplay()`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)：

```python
raw = "".join(buf).strip()

# 第一级：去掉 markdown 代码块
if raw.startswith("```"):
    raw = raw.split("\n", 1)[-1]
if raw.endswith("```"):
    raw = raw.rsplit("\n", 1)[0]

data = None

# 第二级：直接 JSON 解析
try:
    data = json.loads(raw)
except (ValueError, TypeError):
    pass

# 第三级：正则提取 {...} 块（处理 LLM 在 JSON 前后加了解释文字的情况）
if data is None:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
        except (ValueError, TypeError):
            pass

# 最终降级：用最小骨架，保证游戏能开始
if data is None:
    log.warning("auto_screenplay: JSON parse failed — using fallback skeleton")
    data = {
        "chapters": [
            {
                "title": "第一章：开端",
                "summary": f"PC 踏入{world.name}，遭遇初始冲突。",
                "main_events": [{"description": "PC 接受主线任务", "keywords": ["任务"], "criteria": "PC 明确目标"}],
                "optional_events": [], "main_npcs": [],
            },
            {
                "title": "第二章：发展",
                "main_events": [{"description": "核心矛盾爆发", "keywords": ["冲突"], "criteria": "PC 解决冲突"}],
                "optional_events": [], "main_npcs": [],
            },
        ],
        "main_characters": [],
        "ending": "PC 完成使命。",
        "opening_hook": f"你站在{world.name}的某处，一段新的冒险即将开始……",
    }
```

---

## 7. Prompt 里的 Few-shot 示例

Few-shot 是让 LLM "看例子学行为" 的技术。比讲规则更有效，因为 LLM 本质上是模式匹配。

[`prompts/gm_few_shot.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/prompts/gm_few_shot.py) 里有正确输出的例子：

```python
FEW_SHOT_EXAMPLES = [
    {
        "role": "user",
        "content": "我走向吧台，向老板打听失踪案的消息。"
    },
    {
        "role": "assistant",
        "content": """<narrative>你走向吧台，老板正在擦拭玻璃杯...</narrative>
<dice skill="社交" target="12" success="获得关键线索" fail="老板警惕起来"/>
<npc_update name="老板张三" favor="+1" state="友好">对你有些好感，愿意透露一些消息</npc_update>
<choices>
- 继续追问失踪者的详情
- 装作随意地询问其他顾客  
- 直接表明调查者身份
</choices>"""
    }
]
```

这些例子在 `build_gm_messages()` 里被插入消息列表，紧跟在 System Prompt 之后，让 LLM 直接看到期望的输出格式。

---

## 8. Prompt Token 监控

长 Prompt 会让 7B 模型质量急剧下降。项目在每回合估算 Token 数并记录警告：

[`service/game.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)：

```python
def _rough_token_count(messages: list[Message]) -> int:
    """粗略估算 token 数（不调用 tiktoken，速度快）：
    CJK 字符约 1.5 字/token，ASCII 约 4 字/token。"""
    total = 0
    for m in messages:
        text = m.content or ""
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        ascii_count = len(text) - cjk
        total += int(cjk / 1.5) + int(ascii_count / 4)
    return total

# 每回合调用
prompt_tokens = _rough_token_count(msgs)
if prompt_tokens > 12000:
    log_event(session_id, "turn_prompt_warning",
              tokens=prompt_tokens,
              msg="prompt > 12k tokens, model may struggle")
```

超过 12k tokens 时记录警告事件，在前端 Debug 视图可见。

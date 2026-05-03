# 02 — LLM 工程化：在 TRPG 场景的实践

> 这是本项目最有价值的学习内容。
> LLM API 调用只是基础，真正的挑战是让 LLM 稳定地按照你想要的方式工作。

---

## 一、Prompt 工程：让 LLM "扮演 GM"

### 问题

LLM 是通用对话模型，你需要把它"塑造"成一个遵守 TRPG 规则、推进剧情的游戏主持人。

### 解决方案：结构化 System Prompt

**核心文件：** [`backend/src/dzmm/prompts/gm_template.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/prompts/gm_template.py)

GM Prompt 由多段拼接而成：

```
[System Prompt]
  1. 角色定义（你是谁、你的职责）
  2. 输出格式规范（必须用 XML 标签）
  3. 铁律（27 条不可违反的规则）
  4. 世界设定 Markdown
  5. 角色卡

[Key Facts 动态注入]
  - 当前场景/地点
  - 活跃 NPC 列表
  - 剧本进度（当前章节/主线事件状态）
  - 隐藏事件（GM 专用的"定时炸弹"）
  - 厄运值压力
  - 场景滞留警告（如果 PC 在同一地点待太久）

[故事摘要]（历史消息的压缩版）

[最近 N 条完整消息]（近期原文）

[当前行动]（用户本回合的输入）
```

### 为什么用 XML 标签？

LLM 输出既有给玩家看的叙事文本，也有给程序处理的结构化数据（属性变化、NPC 更新等）。
用 XML 标签区分二者，解析器可以实时识别：

```xml
<narrative>你走进了酒馆，灯光昏黄。</narrative>
<npc_update name="老酒保" favor="+2" state="友好">注意到你的眼神</npc_update>
<state_change>{"hp": -3}</state_change>
<dice skill="感知" target="12" success="发现可疑人物" fail="什么也没注意到">15</dice>
```

**相关代码：**
- 标签定义：[`parsing/stream_parser.py` KNOWN_TAGS](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/parsing/stream_parser.py#L6)
- 标签应用（DB 副作用）：[`service/state_apply/`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/state_apply/)

---

## 二、上下文窗口管理

### 问题

LLM 的 Context Window 是有限的（7B 模型通常 4k-32k tokens）。
把所有历史消息都放进 Prompt，会有两个问题：
1. 超出限制被强制截断（丢失重要信息）
2. LLM "迷失"在长文本中，注意力分散，输出质量下降

实测：70 回合后 LLM 开始重复 few-shot 示例（长上下文坍塌的典型症状）。

### 解决方案：摘要 + 自适应窗口

**两层策略：**

```
历史消息 = 摘要（压缩的早期历史）+ 最近 N 条完整消息
```

**层 1：摘要器**
- 每隔若干回合，用 LLM 把旧消息压缩成摘要
- 摘要是对话历史的"有损压缩"，保留关键事件，丢弃细节
- 相关文件：[`service/summarizer.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/summarizer.py)

**层 2：自适应窗口**
- 窗口大小随游戏进程缩小（摘要质量越高，需要的原文越少）

```python
# service/game.py
RECENT_WINDOW_DEFAULT = 12   # 0-30 回合
RECENT_WINDOW_LONG_GAME = 8  # 30-60 回合
RECENT_WINDOW_VERY_LONG = 6  # 60+ 回合
```

**相关代码：** [`service/game.py` `_recent_window_for()`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)

---

## 三、流式输出：打字机效果

### 问题

LLM 生成一段文字需要几秒到几十秒。如果等全部生成完才显示，体验极差。

### 解决方案：流式 API + SSE 推送

```
LLM 逐 token 输出
    ↓ client.stream() (async generator)
StreamingTagParser.feed() 实时解析 XML 标签
    ↓ yield NarrativeDelta（叙事片段）/ TagComplete（完整标签）
API 层打包成 SSE 事件（每 20 字符或 50ms 推一次）
    ↓ HTTP EventSource
前端 turn.narrative += text → Vue 响应式更新 → 字符实时显示
```

**三层缓冲：**

1. **解析器缓冲**：`StreamingTagParser` 内部缓冲，防止标签被切断
2. **叙事合并缓冲**：API 层每 20 字符/50ms 批量推送，减少 HTTP 发包次数
3. **前端 reactive 缓冲**：`turn.narrative` 是 Vue `reactive` 对象，字符串累积触发重渲染

**相关代码：**
- 解析器：[`parsing/stream_parser.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/parsing/stream_parser.py)
- 批量推送：[`api/routes_sessions/turn.py` `FLUSH_CHARS/FLUSH_INTERVAL`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/api/routes_sessions/turn.py#L109)
- 前端消费：[`composables/useGameTurn.ts` `onNarrative`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useGameTurn.ts)

---

## 四、LLM 输出格式容错

### 问题

LLM 不是编译器，它会犯错：
- 写 `</narriative>` 而不是 `</narrative>`（拼写错误）
- 忘记写 `</narrative>` 就停了（达到 max_tokens 被截断）
- 把 `<choices>` 标签夹在 `<narrative>` 里
- 在 JSON 前后加 markdown 代码块（````json ... ````）

### 解决方案：多层容错

**容错 1：拼写错误的闭合标签**
- `_is_typo_close()` 用编辑距离检测 typo
- `</narriative>` → 识别为 `</narrative>` 的 typo → 正常关闭标签

**容错 2：未关闭的标签（被截断）**
- `parser.finish()` 在流结束时处理残留
- 宁可给出不完整数据，也不丢弃已收集的内容

**容错 3：choices 混入 narrative**
- 前端 `extractChoices()` 从叙事文本中补救出选项列表

**容错 4：剧本 JSON 解析失败**
- 三级降级：直接解析 → 正则提取 `{...}` → 最小 Fallback 骨架
- 相关代码：[`service/game.py` `_auto_generate_screenplay()`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)

---

## 五、弱模型适配（qwen2.5:7b 等本地小模型）

### 问题

7B 参数的本地模型能力有限，主要挑战：
1. **复杂 JSON 生成失败**：剧本大纲要求嵌套 JSON，7B 模型经常产出格式错误
2. **铁律遵守不稳定**：27 条规则太多，小模型会忘记遵守部分规则
3. **长上下文质量下降**：7B 模型对长提示词更敏感

### 解决方案

**针对 JSON 生成失败：三级 Fallback（详见容错 4）**

**针对规则遵守：**
- Few-shot 示例（在 Prompt 里提供正确输出的例子）
- 相关文件：[`prompts/gm_few_shot.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/prompts/gm_few_shot.py)

**模型推荐策略：**
- GM 叙事引擎推荐专门为 RP 优化的模型（如 roleplay fine-tune 版本）
- 7B 通用模型做基本游戏可以，但 RP 质量和规则遵守明显弱于专用模型

---

## 六、剧情推进机制

### 问题（TRPG 特有）

LLM 倾向于"在当前场景反复细化"，而不是"推动故事往前走"。
实测：玩家在第一个酒馆能和同一个 NPC 聊 30+ 回合，故事毫无进展。

### 解决方案

**1. 剧本大纲（Screenplay）**
- 开局时 LLM 生成结构化剧本（章节/主线事件/关键词/完成标准）
- 每回合把当前进度注入 Key Facts，让 GM 知道"还有哪些事件没发生"

**2. 场景回合压力（Scene Turn Budget）**
- 追踪 `scene_turn_count`（在同一地点已待的回合数）
- 4 回合：Prompt 注入温和提醒（⏰）
- 7 回合：Prompt 注入强制推进指令（🚨，给出 3 个具体方案 + 禁令）

```python
# service/game.py
SCENE_SOFT_PRESSURE_TURNS = 4
SCENE_HARD_EXIT_TURNS = 7
```

**相关代码：** [`service/game.py` `_build_key_facts()`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)

**3. event_complete 作为进度标记**
- GM 完成一个主线事件后必须 emit `<event_complete id="...">`
- 系统记录哪些事件已完成，确保每章主线推完才进入下一章

---

## 七、Key Facts 注入模式

这是整个 Prompt 工程的核心设计：**把数据库状态动态注入 Prompt**。

每回合调用 `_build_key_facts()` 从 DB 读取并格式化：

| 注入内容 | 来源 | 作用 |
|---------|------|------|
| 当前地点 + 场景内物品 | `Location` 表 | GM 知道 PC 在哪里 |
| 活跃 NPC 列表（属性/情绪/好感度） | `NPC` 表 | GM 知道谁在场 |
| 剧本进度（章节/主线事件状态） | `Screenplay` 表 | GM 知道剧情推进到哪里 |
| 隐藏事件（GM 专用） | `HiddenEvent` 表 | "定时炸弹"提醒 |
| 厄运值 | `Session.doom_score` | 坏结局概率 |
| 场景滞留计数 | `Session.scene_turn_count` | 强制推进触发 |
| PC 活跃目标 | `PCGoal` 表 | GM 知道玩家在追求什么 |

**相关代码：** [`service/game.py` `_build_key_facts()`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)

---

## 延伸阅读

- OpenAI Cookbook：Prompt Engineering 最佳实践
- LangChain 文档：Chain of Thought、Few-shot 等技术
- [Anthropic: Claude Prompt Engineering Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)

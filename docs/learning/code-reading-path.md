# 代码阅读路径

> 针对「只懂 Python 语法，不懂 FastAPI / SQLAlchemy / 系统架构」的学习者。
> 每个文件现在都有详细的中文注释，按下面的顺序读，每个阶段都能形成完整的理解闭环。

---

## 整体地图

```
配置层         → 数据库层      → API 层         → 服务层         → AI 层
config.py         db/models.py    schemas.py       game.py          prompts/
secrets.py        db/base.py      routes_*.py      service/         models/
main.py                                            state_apply/     parsing/
```

---

## 第一阶段：程序怎么启动（30 分钟）

弄清楚「一个 FastAPI 服务器是怎么跑起来的」。

| 文件 | 重点看什么 |
|------|-----------|
| `config.py` | 数据库文件存哪里、常量怎么定义 |
| `logging_config.py` | 日志系统的初始化，`_INITIALIZED` 防重复技巧 |
| `secrets.py` | 系统密钥链是什么，API Key 为什么不存数据库 |
| `main.py` | `@asynccontextmanager lifespan`、CORS、路由注册、依赖注入 `Depends` |
| `main_entry.py` | 为什么打包后要用同步入口包裹异步函数 |

**你看完之后能回答**：服务启动时做了哪几件事？为什么用 `async def` 而不是普通 `def`？

---

## 第二阶段：数据库长什么样（1 小时）

弄清楚「数据存在哪、表和表之间怎么关联」。不需要懂 SQL，只要会读类定义。

| 文件 | 重点看什么 |
|------|-----------|
| `db/models.py` | 每个 `class` = 一张表；`ForeignKey` = 外键；`Mapped[int\|None]` = 可空列 |
| `db/base.py` | `_V0XX_MIGRATIONS` 字典是什么、`init_db` 怎么自动升级旧数据库 |

**关键表的关系**（从上往下是外键方向）：
```
World
 └─ Character
 └─ Session ────────── ModelConfig（GM 模型）
      │                ModelConfig（摘要模型）
      ├─ NPC
      ├─ Message
      ├─ Location
      ├─ PlotThread
      ├─ CharState（运行时属性，如当前 HP）
      └─ WorldFramework（开放世界框架）
           ├─ WorldLocation
           ├─ WorldFaction
           ├─ WorldNPCTemplate
           └─ WorldEvent
```

**你看完之后能回答**：为什么 `CharState` 和 `Character` 是两张表？`JSON 字段` 是什么存储模式？

---

## 第三阶段：API 接口怎么写（1 小时）

弄清楚「客户端发一个 HTTP 请求，服务器是怎么处理的」。

**先读这个文件，建立模板认知**：

| 文件 | 重点看什么 |
|------|-----------|
| `api/schemas.py` | `*In` 和 `*Out` 类的区别，Pydantic 自动校验的原理 |
| `api/routes_worlds.py` | 最简单的 CRUD：`@router.get`、`@router.post`、`Depends`、`HTTPException` |
| `api/routes_models.py` | `api_key_ref` 安全设计，`is_default` 互斥逻辑 |

**然后读这个，看复杂一点的**：

| 文件 | 重点看什么 |
|------|-----------|
| `api/routes_sessions/base.py` | 两种创建存档的模式（剧本模式 vs 自由模式），`s.flush()` vs `s.commit()` |
| `api/routes_sessions/_common.py` | 依赖注入占位符的设计，`delete_session_cascade` 为什么要手动级联 |
| `api/routes_sessions/messages.py` | SQLAlchemy 查询链：`select().where().order_by().scalars().all()` |

**FastAPI 三件套**（你会反复见到）：
```python
@router.post("/path", response_model=SomeOut)   # 定义路由 + 返回类型
async def handler(body: SomeIn,                  # Pydantic 自动解析请求体
                  s: AsyncSession = Depends(...)):# 依赖注入数据库会话
```

**你看完之后能回答**：`Depends` 是什么魔法？`async def` 里怎么写数据库查询？

---

## 第四阶段：一回合游戏是怎么跑的（2 小时，核心）

这是整个项目最重要的流程。

**Step 1：入口（API 层）**

| 文件 | 重点看什么 |
|------|-----------|
| `api/routes_sessions/turn.py` | SSE 流式响应是什么，`StreamingResponse` + `yield`，为什么不能用普通 return |

**Step 2：主引擎（Service 层）**

| 文件 | 重点看什么 |
|------|-----------|
| `service/game.py` | `run_turn()` 的 ①～⑩ 步流程注释，`_build_key_facts()` 的 19 步上下文构建 |

**Step 3：GM 提示词（AI 层）**

| 文件 | 重点看什么 |
|------|-----------|
| `prompts/gm_template.py` | System Prompt 长什么样，为什么有 XML 标签规范 |
| `prompts/gm_few_shot.py` | Few-shot 是什么，示例对话为什么能改变 LLM 行为 |

**Step 4：解析输出（Parsing 层）**

| 文件 | 重点看什么 |
|------|-----------|
| `parsing/stream_parser.py` | 流式解析的挑战：标签可能被切成两段，怎么用缓冲区拼回来 |
| `parsing/events.py` | `ParseEvent` 是什么数据结构 |

**Step 5：把标签写进数据库（State Apply 层）**

| 文件 | 重点看什么 |
|------|-----------|
| `service/state_apply/__init__.py` | 整个子系统的设计思路 |
| `service/state_apply/_impl.py` | 调度器：哪个标签交给哪个子模块处理 |
| `service/state_apply/npc.py` | 最复杂的一个：渐进揭露、模糊名字匹配 |

**一回合完整数据流**：
```
玩家点"发送"
  → POST /sessions/{id}/turn
  → take_turn() 路由函数（turn.py）
  → run_turn() 业务引擎（game.py）
      → _build_key_facts() 构建上下文
      → build_gm_messages() 组装 System/User/Assistant
      → client.stream() 调用 LLM，逐 token 流回
      → StreamingTagParser.feed() 解析标签
      → yield ParseEvent → SSE 推送给前端
  → apply_tags() 把标签写进数据库（state_apply/）
```

**你看完之后能回答**：为什么要用 SSE 而不是普通 HTTP 响应？XML 标签为什么比 JSON 更适合流式解析？

---

## 第五阶段：多 Agent 架构（1 小时）

弄清楚 v0.10 引入的多 Agent 系统：GM 不是唯一在工作的 AI。

| 文件 | 重点看什么 |
|------|-----------|
| `service/agents/orchestrator.py` | 编排器怎么决定派谁上场，`framework_id` 的分支逻辑 |
| `service/agents/triggers.py` | Director 不是每回合都跑，7 个触发条件 |
| `service/agents/director_open_world.py` | 评分算法：`importance × distance_factor + 旅伴加成` |
| `service/world_graph.py` | BFS 是什么，为什么用它算地点距离 |
| `service/agents/npc_actor.py` | NPC actor 和 GM 的区别（第一人称决策 vs 全知旁白） |
| `service/agents/streams.py` | 共用的历史加载和摘要逻辑 |

**多 Agent 关系图**：
```
Orchestrator（编排器）
 ├─ GM（主叙事）      ← 每回合必跑，game.py::run_turn
 ├─ Director（导演）  ← 触发时跑，生成 plot_directive 注入下一回合
 └─ NPC Actor         ← NPC 主动行动时跑（npc_tick 接口触发）
```

---

## 第六阶段：开放世界框架（30 分钟）

理解 v0.11 开放世界框架与旧剧本模式的区别。

| 文件 | 重点看什么 |
|------|-----------|
| `service/wizard_framework.py` | `finalize_framework()` 的名字→ID 两遍解析法 |
| `api/routes_wizard.py` | `/wizard/fw/*` 8 步接口，每步生成什么 |
| `prompts/wizard_locations.py` 等 | 向导各步的提示词长什么样 |

---

## 第七阶段：辅助系统（按需阅读）

不影响主流程，可以按感兴趣的顺序读。

| 文件 | 学什么 |
|------|--------|
| `service/summarizer.py` | 为什么要压缩上下文，high-water mark 设计 |
| `service/world_rag.py` | RAG 是什么，ChromaDB 向量搜索怎么工作 |
| `service/npc_dossier.py` | NPC 档案注入，渐进揭露机制 |
| `service/npc_memory.py` | NPC 长期记忆，fire-and-forget 模式 |
| `service/npc_initiative.py` | NPC 主动联络的 eagerness 评分 |
| `service/encounter_check.py` | 巧合遭遇的"软验证" |
| `service/turn_snapshot.py` | 读档（回滚）的三步策略 |
| `models/openai_compat.py` | OpenAI 兼容接口，并发信号量（Semaphore） |
| `tts/cosyvoice_sidecar.py` | 为什么 TTS 要单独开进程（sidecar 模式） |
| `eval/runner.py` | 自动评测是什么，LLM-as-Judge |

---

## 阶段检查点

读完每个阶段，你应该能做到：

- **第一阶段后**：自己写一个最简单的 FastAPI 服务，有 `/health` 接口，能返回 JSON
- **第二阶段后**：自己用 SQLAlchemy 定义一张表，写一个查询
- **第三阶段后**：自己给上面的表加 GET / POST 接口，带 Pydantic 校验
- **第四阶段后**：看懂 `run_turn()` 的主体逻辑，解释每一步在干什么
- **第五阶段后**：解释「为什么 Director 不是每回合都运行」「BFS 距离如何影响事件优先级」
- **第六阶段后**：解释「开放世界框架和剧本驱动的根本区别」
- **第七阶段后**：根据功能需求，快速定位到应该改哪个文件

---

## 遇到不懂的语法时

代码里常见的 Python 高级用法，遇到时查这里：

| 语法 | 含义 |
|------|------|
| `async def f(): yield x` | 异步生成器，用于 SSE 流式响应 |
| `await s.execute(select(T).where(...))` | 异步数据库查询 |
| `json.loads(field or "{}")` | 字段为 None 时用空 JSON 兜底 |
| `**body.model_dump()` | Pydantic 对象解包成 dict，传给构造函数 |
| `asyncio.create_task(f())` | 后台任务，fire-and-forget（不等结果） |
| `scalar_one_or_none()` | 查单行，查不到返回 None，不报错 |
| `@contextmanager` / `yield` | 把函数变成上下文管理器（相当于 try/finally） |
| `typing.TYPE_CHECKING` | 只在类型检查时 import，避免循环依赖 |

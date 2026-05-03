# Python 后端实现

---

## 1. 项目用了哪些 Python 技术

| 技术 | 用途 | 文件 |
|------|------|------|
| FastAPI | HTTP 路由框架 | `api/routes_sessions/turn.py` |
| SQLAlchemy 2.0 async | ORM + 异步数据库 | `db/models.py`, `db/base.py` |
| Pydantic v2 | 数据校验 + 序列化 | `models/client.py` |
| httpx | 异步 HTTP 客户端（调用 Ollama）| `models/ollama.py` |
| asyncio | Python 原生异步运行时 | 贯穿全部后端代码 |

---

## 2. async/await：异步编程基础

### 问题

调用 LLM API、操作数据库都是 IO 等待。如果用同步代码，等待期间线程被占用，不能处理其他请求。

### 项目里怎么用的

**数据库异步查询**（[`api/routes_sessions/turn.py:44-48`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/api/routes_sessions/turn.py#L44)）：

```python
# await 等待 DB 查询完成，但不阻塞事件循环（可以同时处理其他请求）
sess = await s.get(GameSession, session_id)
cfg  = await s.get(ModelConfig, sess.gm_model_config_id)
```

**异步 HTTP 请求调用 Ollama**（[`models/ollama.py:46-51`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/ollama.py#L46)）：

```python
async with httpx.AsyncClient(timeout=self.timeout) as client:
    async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():   # 逐行读 Ollama 的流式响应
            obj = json.loads(line)
            yield StreamChunk(delta=obj["message"]["content"])
```

**关键点：** `async with` 等同于 Java 的 try-with-resources，保证连接自动关闭。`async for` 是异步版本的 for 循环。

---

## 3. async generator：流式输出的核心

这是整个项目最重要的 Python 特性。**函数里有 `yield`，返回值是迭代器**——不是一次性返回结果，而是边执行边产出数据。

### Ollama 客户端实现流式输出

[`models/ollama.py:28-73`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/ollama.py)：

```python
async def stream(self, messages, params) -> AsyncIterator[StreamChunk]:
    payload = {
        "model": self.model,
        "messages": [m.model_dump() for m in messages],  # Pydantic 对象 → dict
        "stream": True,
        "options": {"temperature": params.temperature, "num_predict": params.max_tokens},
    }
    async with httpx.AsyncClient(timeout=self.timeout) as client:
        async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
            async for line in resp.aiter_lines():
                obj = json.loads(line)
                delta = (obj.get("message") or {}).get("content", "")
                done  = obj.get("done", False)
                usage = TokenUsage(
                    input_tokens=obj.get("prompt_eval_count", 0),
                    output_tokens=obj.get("eval_count", 0),
                ) if done else None
                yield StreamChunk(delta=delta, finish_reason="stop" if done else None, usage=usage)
                #     ↑ 每收到一行 Ollama 响应，立刻 yield 出去
```

### 游戏引擎 run_turn：消费 + 再次 yield

[`service/game.py`（run_turn 主循环）](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)：

```python
async def run_turn(...) -> AsyncIterator[ParseEvent]:
    # ... 组装 Prompt ...

    parser = StreamingTagParser()

    async for chunk in client.stream(msgs, params):      # ① 消费 LLM 流
        if chunk.delta:
            for ev in parser.feed(chunk.delta):          # ② 实时解析 XML 标签
                if isinstance(ev, TagComplete):
                    completed_tags.append(ev)
                yield ev                                  # ③ 把解析事件再次 yield 出去
    
    for ev in parser.finish():   # ④ 流结束，处理残留
        yield ev

    # ... 解析完毕后，写数据库 ...
    await apply_tags(session, session_id, next_turn, completed_tags)
```

**流向：** Ollama → `yield StreamChunk` → `run_turn` 消费 → 解析 → `yield ParseEvent` → API 路由消费 → SSE 推给前端

### 工厂模式：根据配置选择客户端

[`models/factory.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/factory.py)：

```python
def build_client(cfg: ModelConfig) -> ModelClient:
    if cfg.type == "ollama":
        return OllamaClient(name=cfg.name, base_url=cfg.base_url, model=cfg.model_name)
    if cfg.type == "openai_compat":
        api_key = get_api_key(cfg.api_key_ref) if cfg.api_key_ref else ""
        return OpenAICompatClient(name=cfg.name, base_url=cfg.base_url, api_key=api_key, model=cfg.model_name)
    if cfg.type == "lm_studio":
        return OpenAICompatClient(name=cfg.name, base_url=cfg.base_url, api_key="", model=cfg.model_name)
    raise ValueError(f"unknown model type: {cfg.type}")
```

业务代码只依赖 `ModelClient` 抽象，不知道底层是 Ollama 还是 OpenAI，这就是策略模式（Strategy Pattern）。

---

## 4. Pydantic：数据类 + 自动校验

[`models/client.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/client.py) 里的数据类：

```python
from pydantic import BaseModel

class GenerationParams(BaseModel):
    temperature: float = 0.8    # 有默认值，创建时可以不传
    max_tokens: int = 1500
    top_p: float = 0.95
    stop: list[str] | None = None

class StreamChunk(BaseModel):
    delta: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None
```

**好处：**
- 不需要写 `__init__`，Pydantic 自动生成
- 传错类型会立刻报错（不是运行到一半才崩）
- `model_dump()` 直接转 dict，`model_dump_json()` 转 JSON
- `str | None` 是 Python 3.10+ 的联合类型（旧写法 `Optional[str]`）

---

## 5. SQLAlchemy async ORM

### 定义模型

[`db/models.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/db/models.py) 的关键语法：

```python
from sqlalchemy.orm import Mapped, mapped_column, relationship

class Character(Base):
    __tablename__ = "characters"
    
    id: Mapped[int] = mapped_column(primary_key=True)        # 自增主键
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))  # 外键
    name: Mapped[str] = mapped_column(String(120))
    base_stats_json: Mapped[str] = mapped_column(Text)       # JSON 存为 TEXT
    
    # created_at 用 lambda 保证每次 INSERT 都调用一次 datetime.now()
    # 如果写 default=datetime.now(UTC) 则只求值一次（模块加载时），所有行时间相同
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    
    world: Mapped[World] = relationship()   # 访问 char.world 自动查 worlds 表
```

**`Mapped[str | None]` 表示可空列：**

```python
api_key_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
```

### 查询

[`service/game.py` 里的查询写法](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py)：

```python
# 方式1：按主键查（最常用）
sess = await session.get(GameSession, session_id)

# 方式2：带条件查询，返回单行（不存在返回 None）
summary_row = (
    await session.execute(
        select(StorySummary).where(StorySummary.session_id == session_id)
    )
).scalar_one_or_none()

# 方式3：查多行
rows = (
    await session.execute(
        select(MessageRow)
        .where(MessageRow.session_id == session_id)
        .order_by(MessageRow.id.desc())
        .limit(2)
    )
).scalars().all()
```

### 写入

```python
# 新增
session.add(Screenplay(session_id=sess.id, genre="悬疑探案", chapters_json="[]"))
await session.flush()   # 让 DB 生成 id，但还没提交

# 修改（直接赋值，SQLAlchemy 追踪变更）
sess.turn_count = next_turn
sess.last_played = datetime.now(UTC).replace(tzinfo=None)

# 删除
await session.delete(row)

# 提交（由调用方负责，service 层不 commit）
await session.commit()
```

---

## 6. 数据库迁移：不用 Alembic 的轻量方案

SQLite 不支持 `ALTER COLUMN`，只支持 `ALTER TABLE ADD COLUMN`。项目用了一套简单的幂等迁移：

[`db/base.py:149-156`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/db/base.py#L149)：

```python
def _add_missing_columns_sync(conn, table: str, columns: list[tuple[str, str]]) -> None:
    """幂等迁移：只添加不存在的列，已存在的列跳过。"""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    existing = {r[1] for r in rows}          # r[1] 是列名，构成集合
    for name, ddl in columns:
        if name not in existing:             # 只有列不存在时才 ALTER
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

每个版本的新列定义在独立的字典里，启动时依次执行：

```python
_V030_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("scene_turn_count", "scene_turn_count INTEGER NOT NULL DEFAULT 0"),
    ],
}

async def init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)   # 建新表
        for table, cols in _V030_MIGRATIONS.items():    # 迁移旧表
            await conn.run_sync(_add_missing_columns_sync, table, cols)
```

**优点：** 不需要迁移文件，服务启动时自动执行，幂等（多次运行不出错）。
**缺点：** 只能加列，不能改列类型或删列。

---

## 7. FastAPI 路由

[`api/routes_sessions/turn.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/api/routes_sessions/turn.py)：

```python
router = APIRouter(prefix="/sessions", tags=["sessions"])

# @router.post → 注册 POST /sessions/{session_id}/turn
# session_id: int → FastAPI 自动从 URL 路径提取并转换类型
# body: TurnRequest → 自动从请求体 JSON 解析（Pydantic 校验）
# Depends(get_session_maker_dep) → 依赖注入（自动提供 DB 连接工厂）
@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,
    session_maker = Depends(get_session_maker_dep),
):
    async def event_stream():
        async with session_maker() as s:    # 获取 DB 会话
            ...
            async for ev in run_turn(s, session_id, body.action, client):
                yield {"event": "narrative", "data": json.dumps({"text": ev.text})}
        yield {"event": "done", "data": "{}"}
    
    return EventSourceResponse(event_stream())   # 把 async generator 包成 SSE 响应
```

**依赖注入链：**
```
Depends(get_session_maker_dep) → async_session(engine) → AsyncSession
```

每个请求都得到一个独立的数据库会话，用完自动关闭，不需要手动管理。

---

## 8. dataclass：轻量数据类

[`parsing/events.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/parsing/events.py)：

```python
from dataclasses import dataclass, field

@dataclass
class NarrativeDelta:
    text: str                                    # 叙事文本片段

@dataclass  
class TagComplete:
    name: str
    attrs: dict[str, str] = field(default_factory=dict)  # 可变默认值必须用 field()
    content: str = ""

@dataclass
class ParseError:
    message: str
    raw: str

# 联合类型别名：ParseEvent 可以是这三种之一
ParseEvent = NarrativeDelta | TagComplete | ParseError
```

**`dataclass` vs `Pydantic BaseModel`：**
- `dataclass`：标准库，轻量，无运行时类型校验，适合内部数据结构
- `Pydantic`：有运行时类型校验和 JSON 序列化，适合 API 入参/出参

---

## 9. isinstance 判断类型

Python 没有 Java 的 `switch (obj instanceof Type)` 语法（Java 16+ 才有 Pattern Matching）。
项目里用 `isinstance` 做运行时类型判断：

```python
# service/game.py
async for chunk in client.stream(msgs, params):
    for ev in parser.feed(chunk.delta):
        if isinstance(ev, TagComplete):       # 等价于 Java: ev instanceof TagComplete
            completed_tags.append(ev)
        if isinstance(ev, NarrativeDelta):
            narrative_parts.append(ev.text)
        yield ev
```

```python
# api/turn.py
async for ev in run_turn(s, session_id, body.action, client):
    if isinstance(ev, NarrativeDelta):
        narrative_buf.append(ev.text)
    elif isinstance(ev, TagComplete):
        yield {"event": "tag", "data": json.dumps({"name": ev.name, ...})}
    elif isinstance(ev, ParseError):
        yield {"event": "parse_error", ...}
```

---

## 10. state_apply：标签副作用分发器

GM 的 LLM 输出里有各种标签（`<state_change>`、`<npc_update>` 等），每个都要修改数据库。

[`service/state_apply/_impl.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/state_apply/_impl.py) 是分发器：

```python
async def apply_tags(session, session_id, current_turn, tags):
    for tag in tags:
        if tag.name == "state_change":
            await _apply_state_change(session, session_id, tag.content)
        elif tag.name == "npc_update":
            await _apply_npc_update(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "plot_event":
            await _apply_plot_event(session, session_id, current_turn, tag.attrs, tag.content)
        # ... 其他标签 ...
```

以 `state_change` 为例，[`service/state_apply/state_change.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/state_apply/state_change.py)：

```python
async def _apply_state_change(session, session_id, raw):
    payload = parse_loose_json(raw)     # 容错 JSON 解析（LLM 可能输出不标准的 JSON）
    if not payload:
        return
    
    cs = (await session.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    
    stats = json.loads(cs.stats_json or "{}")
    
    for key, val in payload.items():
        if key == "inventory_add" and isinstance(val, list):
            inventory.extend(str(x) for x in val)
        elif key == "inventory_remove" and isinstance(val, list):
            for item in val:
                if item in inventory: inventory.remove(item)
        elif isinstance(val, (int, float)):
            stats[key] = stats.get(key, 0) + val   # 累加（delta 而非绝对值）
    
    cs.stats_json = json.dumps(stats, ensure_ascii=False)
```

**设计要点：** 每个标签一个独立文件，职责单一，便于单独测试和修改。

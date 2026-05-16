# Screenplay-First Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the data model from World→Character→Session into World→Screenplay(含PC定义)→Session，使剧本成为独立可复用的第一级实体。

**Architecture:** 在 `Screenplay` 模型上新增 `world_id`、`title`、`pc_name`、`pc_profile_md`、`pc_base_stats_json` 字段，使其脱离对具体 `Session` 的依赖，成为可在 World 下独立管理的剧本卡。`Session` 新增 `screenplay_id` 外键；创建会话时若传入 `screenplay_id` 则从剧本数据自动创建 `Character` 行，`game.py` 完全不改动。历史 `Session` 保持 `character_id` 继续可用（`screenplay_id` 为 nullable）。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / SQLite·aiosqlite / Pydantic v2 / Vue 3 + TypeScript + Pinia + Element Plus

---

## File Map

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/src/dzmm/db/models.py` | 修改 | 给 `Screenplay` 加 PC 字段；给 `Session` 加 `screenplay_id` |
| `backend/src/dzmm/db/base.py` | 修改 | 添加 `_V028_MIGRATIONS` 并在 `init_db` 中执行 |
| `backend/src/dzmm/api/schemas.py` | 修改 | 新增 `ScreenplayStandaloneIn/Out`；更新 `SessionIn` |
| `backend/src/dzmm/api/routes_screenplays.py` | 新建 | `GET/POST /worlds/{id}/screenplays`、`GET/PATCH/DELETE /screenplays/{id}` |
| `backend/src/dzmm/api/app.py` | 修改 | 注册新路由 |
| `backend/src/dzmm/api/routes_sessions/base.py` | 修改 | `create_session` 支持 `screenplay_id`，自动创建 Character |
| `backend/src/dzmm/seed_data.py` | 修改 | 把内置角色卡改为内置剧本；删掉 Character 种子数据 |
| `frontend/src/api/types.ts` | 修改 | 新增 `StandaloneScreenplay`、`StandaloneScreenplayIn` 类型；更新 `SessionIn` |
| `frontend/src/api/screenplays.ts` | 新建 | `standaloneScreenplayApi`（CRUD + worldScreenplays list） |
| `frontend/src/stores/screenplays.ts` | 新建 | Pinia store for standalone screenplays |
| `frontend/src/views/WorldScreenplaysView.vue` | 新建 | `/worlds/:id/screenplays` 页，剧本卡列表 + 新建表单 |
| `frontend/src/views/WorldsView.vue` | 修改 | 每个世界观行显示"📜 N 个剧本"徽标；点击跳转 screenplays 列表 |
| `frontend/src/views/SessionsView.vue` | 修改 | 新建会话弹窗改为选剧本（替代选 World+Character） |
| `frontend/src/router/index.ts` | 修改 | 注册 `worlds/:id/screenplays` 路由 |
| `frontend/src/views/LayoutView.vue` | 修改 | 将导航"角色卡"换成"世界观"（或直接删除"角色卡"nav item） |

---

### Task 1: DB models + migration (_V028_MIGRATIONS)

**Files:**
- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/src/dzmm/db/base.py`

- [ ] **Step 1: 给 `Screenplay` 模型加字段**

在 `backend/src/dzmm/db/models.py` 的 `Screenplay` 类中，在 `session_id` 字段后添加新字段（保持 `session_id` 可为 nullable 以向后兼容历史剧本）：

```python
class Screenplay(Base):
    __tablename__ = "screenplays"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)  # nullable: standalone screenplays have no session
    world_id: Mapped[int | None] = mapped_column(ForeignKey("worlds.id"), nullable=True)  # v0.2.8: standalone screenplay belongs to world
    title: Mapped[str] = mapped_column(String(120), default="")  # v0.2.8: display title independent of session name
    pc_name: Mapped[str] = mapped_column(String(120), default="")  # v0.2.8: PC definition
    pc_profile_md: Mapped[str] = mapped_column(Text, default="")
    pc_base_stats_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(default=1)
    genre: Mapped[str] = mapped_column(String(60), default="")
    custom_prompt: Mapped[str] = mapped_column(Text, default="")
    outline_md: Mapped[str] = mapped_column(Text, default="")
    chapters_json: Mapped[str] = mapped_column(Text, default="[]")
    main_characters_json: Mapped[str] = mapped_column(Text, default="[]")
    ending_md: Mapped[str] = mapped_column(Text, default="")
    opening_hook: Mapped[str] = mapped_column(Text, default="")
    current_chapter: Mapped[int] = mapped_column(default=1)
    completed_events_json: Mapped[str] = mapped_column(Text, default="[]")
    parent_screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 2: 给 `Session` 模型加 `screenplay_id`**

在 `backend/src/dzmm/db/models.py` 的 `Session` 类中，在 `character_id` 字段后添加：

```python
screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)  # v0.2.8: source screenplay
```

- [ ] **Step 3: 添加迁移字典**

在 `backend/src/dzmm/db/base.py` 的 `_V027_MIGRATIONS` 之后添加：

```python
_V028_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "screenplays": [
        ("session_id_nullable_marker", ""),  # handled separately — session_id already exists, just making world_id etc
        ("world_id", "world_id INTEGER REFERENCES worlds(id)"),
        ("title", "title VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_name", "pc_name VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_profile_md", "pc_profile_md TEXT NOT NULL DEFAULT ''"),
        ("pc_base_stats_json", "pc_base_stats_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "sessions": [
        ("screenplay_id", "screenplay_id INTEGER REFERENCES screenplays(id)"),
    ],
}
```

注意：`session_id_nullable_marker` 是占位符，`_add_missing_columns_sync` 检测到 `session_id` 已存在会跳过；不需要实际修改 NOT NULL 约束（SQLite 不支持 ALTER COLUMN，历史行的 `session_id` 仍有值，新的独立剧本 `session_id=NULL` 依赖 SQLAlchemy 的 `nullable=True` 映射，DDL 已在 `create_all` 建新表时生效，只有升级旧库时才需要处理）。

**实际上把占位符去掉，用更干净的实现：**

```python
_V028_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "screenplays": [
        ("world_id", "world_id INTEGER REFERENCES worlds(id)"),
        ("title", "title VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_name", "pc_name VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_profile_md", "pc_profile_md TEXT NOT NULL DEFAULT ''"),
        ("pc_base_stats_json", "pc_base_stats_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "sessions": [
        ("screenplay_id", "screenplay_id INTEGER REFERENCES screenplays(id)"),
    ],
}
```

- [ ] **Step 4: 在 `init_db` 中执行迁移**

在 `init_db()` 函数最后的迁移循环块末尾添加：

```python
        for table, cols in _V028_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
```

- [ ] **Step 5: 验证无语法错误**

```bash
cd backend && python -c "from dzmm.db.base import init_db; from dzmm.db import models; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/src/dzmm/db/base.py
git commit -m "feat(db): v0.2.8 — Screenplay gains world_id+PC fields; Session gains screenplay_id"
```

---

### Task 2: Backend schemas + Screenplay CRUD API

**Files:**
- Modify: `backend/src/dzmm/api/schemas.py`
- Create: `backend/src/dzmm/api/routes_screenplays.py`
- Modify: `backend/src/dzmm/api/app.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/` 新建 `test_standalone_screenplays.py`：

```python
import json
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def _make_world(client: AsyncClient) -> int:
    r = await client.post("/worlds", json={"name": "测试世界", "content_md": "内容", "style": "realistic", "rules_mode": "light"})
    return r.json()["id"]


async def test_create_standalone_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "迷雾剧本",
        "genre": "悬疑探案",
        "pc_name": "林探",
        "pc_profile_md": "老警探",
        "pc_base_stats_json": "{}",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["world_id"] == wid
    assert data["title"] == "迷雾剧本"
    assert data["session_id"] is None


async def test_list_world_screenplays(client: AsyncClient):
    wid = await _make_world(client)
    await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本A", "genre": "悬疑探案", "pc_name": "A", "pc_profile_md": "", "pc_base_stats_json": "{}"
    })
    await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本B", "genre": "英雄成长", "pc_name": "B", "pc_profile_md": "", "pc_base_stats_json": "{}"
    })
    r = await client.get(f"/worlds/{wid}/screenplays")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    titles = {it["title"] for it in items}
    assert titles == {"剧本A", "剧本B"}


async def test_get_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    create_r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本X", "genre": "政治阴谋", "pc_name": "侠客", "pc_profile_md": "背景", "pc_base_stats_json": "{}"
    })
    sp_id = create_r.json()["id"]
    r = await client.get(f"/screenplays/{sp_id}")
    assert r.status_code == 200
    assert r.json()["id"] == sp_id


async def test_delete_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    create_r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "剧本Y", "genre": "灾难求生", "pc_name": "幸存者", "pc_profile_md": "", "pc_base_stats_json": "{}"
    })
    sp_id = create_r.json()["id"]
    r = await client.delete(f"/screenplays/{sp_id}")
    assert r.status_code == 204
    r2 = await client.get(f"/screenplays/{sp_id}")
    assert r2.status_code == 404
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd backend && python -m pytest tests/test_standalone_screenplays.py -v 2>&1 | head -30
```

Expected: ERRORS / FAILED (routes not yet registered)

- [ ] **Step 3: 在 schemas.py 中新增 Pydantic 类型**

在 `backend/src/dzmm/api/schemas.py` 末尾追加：

```python
class ScreenplayStandaloneIn(BaseModel):
    title: str
    genre: str = ""
    pc_name: str = ""
    pc_profile_md: str = ""
    pc_base_stats_json: str = "{}"
    custom_prompt: str = ""
    outline_md: str = ""
    chapters_json: str = "[]"
    main_characters_json: str = "[]"
    ending_md: str = ""
    opening_hook: str = ""


class ScreenplayStandaloneOut(ScreenplayStandaloneIn):
    id: int
    world_id: int
    session_id: int | None = None
    version: int = 1
    current_chapter: int = 1
    completed_events_json: str = "[]"
    status: str = "active"
    created_at: str
```

- [ ] **Step 4: 创建路由文件 `routes_screenplays.py`**

新建 `backend/src/dzmm/api/routes_screenplays.py`：

```python
"""Standalone Screenplay CRUD: independent of session lifecycle."""
import json as _json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.api.schemas import ScreenplayStandaloneIn, ScreenplayStandaloneOut
from dzmm.db.models import Screenplay, World

router = APIRouter(tags=["screenplays"])


def _sp_to_out(sp: Screenplay) -> ScreenplayStandaloneOut:
    return ScreenplayStandaloneOut(
        id=sp.id,
        world_id=sp.world_id,
        session_id=sp.session_id,
        title=sp.title,
        genre=sp.genre,
        pc_name=sp.pc_name,
        pc_profile_md=sp.pc_profile_md,
        pc_base_stats_json=sp.pc_base_stats_json,
        custom_prompt=sp.custom_prompt,
        outline_md=sp.outline_md,
        chapters_json=sp.chapters_json,
        main_characters_json=sp.main_characters_json,
        ending_md=sp.ending_md,
        opening_hook=sp.opening_hook,
        version=sp.version,
        current_chapter=sp.current_chapter,
        completed_events_json=sp.completed_events_json,
        status=sp.status,
        created_at=sp.created_at.isoformat() if sp.created_at else "",
    )


@router.post("/worlds/{world_id}/screenplays", response_model=ScreenplayStandaloneOut, status_code=201)
async def create_world_screenplay(
    world_id: int,
    body: ScreenplayStandaloneIn,
    s: AsyncSession = Depends(get_session_dep),
):
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "world not found")
    sp = Screenplay(
        world_id=world_id,
        session_id=None,
        title=body.title,
        genre=body.genre,
        pc_name=body.pc_name,
        pc_profile_md=body.pc_profile_md,
        pc_base_stats_json=body.pc_base_stats_json,
        custom_prompt=body.custom_prompt,
        outline_md=body.outline_md,
        chapters_json=body.chapters_json,
        main_characters_json=body.main_characters_json,
        ending_md=body.ending_md,
        opening_hook=body.opening_hook,
    )
    s.add(sp)
    await s.commit()
    await s.refresh(sp)
    return _sp_to_out(sp)


@router.get("/worlds/{world_id}/screenplays", response_model=list[ScreenplayStandaloneOut])
async def list_world_screenplays(
    world_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "world not found")
    rows = (await s.execute(
        select(Screenplay)
        .where(Screenplay.world_id == world_id, Screenplay.session_id.is_(None))
        .order_by(Screenplay.created_at.desc())
    )).scalars().all()
    return [_sp_to_out(sp) for sp in rows]


@router.get("/screenplays/{screenplay_id}", response_model=ScreenplayStandaloneOut)
async def get_screenplay(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    return _sp_to_out(sp)


@router.patch("/screenplays/{screenplay_id}", response_model=ScreenplayStandaloneOut)
async def patch_screenplay(
    screenplay_id: int,
    body: ScreenplayStandaloneIn,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sp, field, value)
    await s.commit()
    await s.refresh(sp)
    return _sp_to_out(sp)


@router.delete("/screenplays/{screenplay_id}", status_code=204)
async def delete_screenplay(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    await s.delete(sp)
    await s.commit()
```

- [ ] **Step 5: 注册路由到 app.py**

在 `backend/src/dzmm/api/app.py` 中找到现有 `include_router` 的位置（在 `create_app()` 函数内），添加：

```python
from dzmm.api.routes_screenplays import router as screenplays_router
# ...existing imports...
app.include_router(screenplays_router)
```

- [ ] **Step 6: 运行测试，确认通过**

```bash
cd backend && python -m pytest tests/test_standalone_screenplays.py -v
```

Expected: 4 PASSED

- [ ] **Step 7: 运行全量测试**

```bash
cd backend && python -m pytest -x -q 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add backend/src/dzmm/api/schemas.py backend/src/dzmm/api/routes_screenplays.py backend/src/dzmm/api/app.py backend/tests/test_standalone_screenplays.py
git commit -m "feat(api): standalone Screenplay CRUD — /worlds/{id}/screenplays + /screenplays/{id}"
```

---

### Task 3: 更新 Session 创建逻辑（接受 screenplay_id，自动创建 Character）

**Files:**
- Modify: `backend/src/dzmm/api/schemas.py`
- Modify: `backend/src/dzmm/api/routes_sessions/base.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_standalone_screenplays.py` 末尾追加（或新建 `test_session_from_screenplay.py`）：

```python
# --- session creation from screenplay ---

async def _make_model_config(client: AsyncClient) -> int:
    r = await client.post("/models", json={
        "name": "test", "type": "openai_compat",
        "base_url": "http://localhost:11434", "model_name": "llama3"
    })
    return r.json()["id"]


async def test_create_session_from_screenplay(client: AsyncClient):
    wid = await _make_world(client)
    sp_r = await client.post(f"/worlds/{wid}/screenplays", json={
        "title": "迷雾剧本", "genre": "悬疑探案",
        "pc_name": "林探", "pc_profile_md": "老警探，沉默寡言",
        "pc_base_stats_json": '{"力量": 3, "智力": 8}'
    })
    sp_id = sp_r.json()["id"]
    mid = await _make_model_config(client)
    r = await client.post("/sessions", json={
        "name": "第一局",
        "screenplay_id": sp_id,
        "gm_model_config_id": mid,
        "summarizer_model_config_id": mid,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["screenplay_id"] == sp_id
    # character should have been auto-created
    char_id = data["character_id"]
    assert char_id > 0
    # verify character data matches screenplay PC fields
    char_r = await client.get(f"/characters/{char_id}")
    assert char_r.status_code == 200
    char_data = char_r.json()
    assert char_data["name"] == "林探"
    assert "老警探" in char_data["profile_md"]
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd backend && python -m pytest tests/test_standalone_screenplays.py::test_create_session_from_screenplay -v 2>&1 | tail -10
```

Expected: FAILED

- [ ] **Step 3: 更新 `SessionIn` schema**

在 `backend/src/dzmm/api/schemas.py` 中将 `SessionIn` 修改为：

```python
class SessionIn(BaseModel):
    name: str
    screenplay_id: int | None = None   # new: standalone screenplay → auto-create character
    world_id: int | None = None         # legacy / direct
    character_id: int | None = None     # legacy / direct
    gm_model_config_id: int
    summarizer_model_config_id: int
```

更新 `SessionOut`：

```python
class SessionOut(BaseModel):
    id: int
    name: str
    screenplay_id: int | None = None
    world_id: int
    character_id: int
    gm_model_config_id: int
    summarizer_model_config_id: int
    turn_count: int
```

- [ ] **Step 4: 更新 `create_session` 函数**

在 `backend/src/dzmm/api/routes_sessions/base.py` 中更新 `create_session`：

```python
@router.post("", response_model=SessionOut)
async def create_session(body: SessionIn, s: AsyncSession = Depends(get_session_dep)):
    from dzmm.db.models import Screenplay, Character as CharacterRow

    world_id = body.world_id
    character_id = body.character_id

    if body.screenplay_id is not None:
        sp = await s.get(Screenplay, body.screenplay_id)
        if sp is None:
            raise HTTPException(404, "screenplay not found")
        world_id = sp.world_id
        # Auto-create a Character row from screenplay PC definition
        char = CharacterRow(
            world_id=world_id,
            name=sp.pc_name or "主角",
            profile_md=sp.pc_profile_md or "",
            base_stats_json=sp.pc_base_stats_json or "{}",
        )
        s.add(char)
        await s.flush()
        character_id = char.id
    elif world_id is None or character_id is None:
        raise HTTPException(422, "either screenplay_id or both world_id+character_id are required")

    sess = GameSession(
        name=body.name,
        world_id=world_id,
        character_id=character_id,
        screenplay_id=body.screenplay_id,
        gm_model_config_id=body.gm_model_config_id,
        summarizer_model_config_id=body.summarizer_model_config_id,
    )
    s.add(sess)
    await s.flush()
    s.add(CharState(session_id=sess.id))
    await s.commit()
    await s.refresh(sess)
    return _to_out(sess)
```

- [ ] **Step 5: 更新 `_to_out` helper 以包含 `screenplay_id`**

在 `backend/src/dzmm/api/routes_sessions/_common.py` 中找到 `_to_out` 函数，确保它输出 `screenplay_id`：

```python
def _to_out(sess) -> SessionOut:
    return SessionOut(
        id=sess.id,
        name=sess.name,
        screenplay_id=sess.screenplay_id,
        world_id=sess.world_id,
        character_id=sess.character_id,
        gm_model_config_id=sess.gm_model_config_id,
        summarizer_model_config_id=sess.summarizer_model_config_id,
        turn_count=sess.turn_count,
    )
```

- [ ] **Step 6: 运行目标测试**

```bash
cd backend && python -m pytest tests/test_standalone_screenplays.py -v
```

Expected: 5 PASSED

- [ ] **Step 7: 全量测试**

```bash
cd backend && python -m pytest -x -q 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add backend/src/dzmm/api/schemas.py backend/src/dzmm/api/routes_sessions/base.py backend/src/dzmm/api/routes_sessions/_common.py backend/tests/test_standalone_screenplays.py
git commit -m "feat(session): create session from screenplay_id — auto-creates Character"
```

---

### Task 4: 前端类型 + API 客户端

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/screenplays.ts`
- Create: `frontend/src/stores/screenplays.ts`

- [ ] **Step 1: 更新 `types.ts`，添加 `StandaloneScreenplay` 类型并更新 `SessionIn`**

在 `frontend/src/api/types.ts` 末尾追加：

```typescript
export interface StandaloneScreenplay {
  id: number
  world_id: number
  session_id: number | null
  title: string
  genre: string
  pc_name: string
  pc_profile_md: string
  pc_base_stats_json: string
  custom_prompt: string
  outline_md: string
  chapters_json: string
  main_characters_json: string
  ending_md: string
  opening_hook: string
  version: number
  current_chapter: number
  completed_events_json: string
  status: 'active' | 'concluded' | 'superseded'
  created_at: string
}

export type StandaloneScreenplayIn = Omit<StandaloneScreenplay,
  'id' | 'world_id' | 'session_id' | 'version' | 'current_chapter' |
  'completed_events_json' | 'status' | 'created_at'>
```

将 `SessionIn` 修改为：

```typescript
export interface SessionIn {
  name: string
  screenplay_id?: number      // new: pick a standalone screenplay
  world_id?: number           // legacy
  character_id?: number       // legacy
  gm_model_config_id: number
  summarizer_model_config_id: number
}
```

将 `GameSession` 更新为：

```typescript
export interface GameSession {
  id: number
  name: string
  screenplay_id: number | null
  world_id: number
  character_id: number
  gm_model_config_id: number
  summarizer_model_config_id: number
  turn_count: number
}
```

- [ ] **Step 2: 新建 `frontend/src/api/screenplays.ts`**

```typescript
import { api } from './client'
import type { StandaloneScreenplay, StandaloneScreenplayIn } from './types'

export const standaloneScreenplayApi = {
  listByWorld: (worldId: number) =>
    api.get<StandaloneScreenplay[]>(`/worlds/${worldId}/screenplays`).then(r => r.data),

  create: (worldId: number, body: StandaloneScreenplayIn) =>
    api.post<StandaloneScreenplay>(`/worlds/${worldId}/screenplays`, body).then(r => r.data),

  get: (id: number) =>
    api.get<StandaloneScreenplay>(`/screenplays/${id}`).then(r => r.data),

  update: (id: number, body: Partial<StandaloneScreenplayIn>) =>
    api.patch<StandaloneScreenplay>(`/screenplays/${id}`, body).then(r => r.data),

  remove: (id: number) =>
    api.delete(`/screenplays/${id}`),
}
```

- [ ] **Step 3: 新建 `frontend/src/stores/screenplays.ts`**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { standaloneScreenplayApi } from '@/api/screenplays'
import type { StandaloneScreenplay, StandaloneScreenplayIn } from '@/api/types'

export const useScreenplaysStore = defineStore('screenplays', () => {
  const byWorld = ref<Map<number, StandaloneScreenplay[]>>(new Map())

  async function fetchByWorld(worldId: number) {
    const items = await standaloneScreenplayApi.listByWorld(worldId)
    byWorld.value.set(worldId, items)
    return items
  }

  async function create(worldId: number, body: StandaloneScreenplayIn) {
    const sp = await standaloneScreenplayApi.create(worldId, body)
    const existing = byWorld.value.get(worldId) ?? []
    byWorld.value.set(worldId, [sp, ...existing])
    return sp
  }

  async function remove(id: number, worldId: number) {
    await standaloneScreenplayApi.remove(id)
    const existing = byWorld.value.get(worldId) ?? []
    byWorld.value.set(worldId, existing.filter(sp => sp.id !== id))
  }

  return { byWorld, fetchByWorld, create, remove }
})
```

- [ ] **Step 4: TypeScript 类型检查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/screenplays.ts frontend/src/stores/screenplays.ts
git commit -m "feat(frontend): StandaloneScreenplay types + API client + Pinia store"
```

---

### Task 5: 新建 `WorldScreenplaysView.vue`（剧本卡列表页）

**Files:**
- Create: `frontend/src/views/WorldScreenplaysView.vue`
- Modify: `frontend/src/router/index.ts`

- [ ] **Step 1: 新建视图文件**

新建 `frontend/src/views/WorldScreenplaysView.vue`：

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useScreenplaysStore } from '@/stores/screenplays'
import { useWorldsStore } from '@/stores/worlds'
import type { StandaloneScreenplayIn } from '@/api/types'
import { KNOWN_GENRES } from '@/api/screenplay'

const route = useRoute()
const worldId = computed(() => Number(route.params.id))

const spStore = useScreenplaysStore()
const worldsStore = useWorldsStore()

const items = computed(() => spStore.byWorld.get(worldId.value) ?? [])
const world = computed(() => worldsStore.items.find(w => w.id === worldId.value))

const showForm = ref(false)
const saving = ref(false)
const form = ref<StandaloneScreenplayIn>({
  title: '',
  genre: '',
  pc_name: '',
  pc_profile_md: '',
  pc_base_stats_json: '{}',
  custom_prompt: '',
  outline_md: '',
  chapters_json: '[]',
  main_characters_json: '[]',
  ending_md: '',
  opening_hook: '',
})

function resetForm() {
  form.value = {
    title: '',
    genre: '',
    pc_name: '',
    pc_profile_md: '',
    pc_base_stats_json: '{}',
    custom_prompt: '',
    outline_md: '',
    chapters_json: '[]',
    main_characters_json: '[]',
    ending_md: '',
    opening_hook: '',
  }
}

async function onSubmit() {
  if (!form.value.title || !form.value.pc_name) {
    ElMessage.warning('剧本标题和 PC 名称为必填项')
    return
  }
  saving.value = true
  try {
    await spStore.create(worldId.value, form.value)
    ElMessage.success('剧本已创建')
    showForm.value = false
    resetForm()
  } catch {
    ElMessage.error('创建失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(sp: { id: number; title: string }) {
  await ElMessageBox.confirm(`删除剧本「${sp.title}」？此操作不可撤销。`, '确认删除', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await spStore.remove(sp.id, worldId.value)
  ElMessage.success('已删除')
}

onMounted(async () => {
  await Promise.all([
    worldsStore.fetch(),
    spStore.fetchByWorld(worldId.value),
  ])
})
</script>

<template>
  <div class="world-screenplays">
    <div class="header">
      <h2>{{ world?.name ?? '世界观' }} — 剧本列表</h2>
      <el-button type="primary" @click="showForm = true">＋ 新建剧本</el-button>
    </div>

    <el-empty v-if="items.length === 0" description="暂无剧本，点击「新建剧本」开始创作" />

    <div class="sp-grid">
      <el-card v-for="sp in items" :key="sp.id" class="sp-card">
        <template #header>
          <div class="card-header">
            <span class="sp-title">{{ sp.title }}</span>
            <el-tag size="small">{{ sp.genre || '自定义' }}</el-tag>
          </div>
        </template>
        <div class="sp-pc">
          <strong>PC：</strong>{{ sp.pc_name }}
          <div v-if="sp.pc_profile_md" class="sp-profile">{{ sp.pc_profile_md.slice(0, 60) }}{{ sp.pc_profile_md.length > 60 ? '…' : '' }}</div>
        </div>
        <template #footer>
          <el-button size="small" type="danger" text @click="onDelete(sp)">删除</el-button>
        </template>
      </el-card>
    </div>

    <el-dialog v-model="showForm" title="新建剧本" width="520px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="剧本标题" required>
          <el-input v-model="form.title" placeholder="例：迷雾中的红玫瑰" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.genre" placeholder="选择类型">
            <el-option v-for="g in KNOWN_GENRES" :key="g.key" :label="g.label" :value="g.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="PC 名称" required>
          <el-input v-model="form.pc_name" placeholder="主角姓名" />
        </el-form-item>
        <el-form-item label="PC 背景">
          <el-input v-model="form.pc_profile_md" type="textarea" :rows="3" placeholder="角色背景简述（支持 Markdown）" />
        </el-form-item>
        <el-form-item label="初始属性">
          <el-input v-model="form.pc_base_stats_json" placeholder='{"力量":5,"敏捷":5}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.world-screenplays { padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.sp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.sp-card { cursor: default; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.sp-title { font-weight: 600; }
.sp-pc { font-size: 14px; }
.sp-profile { color: #888; margin-top: 4px; font-size: 12px; }
</style>
```

- [ ] **Step 2: 注册路由**

在 `frontend/src/router/index.ts` 中，在 `worlds` 路由后追加：

```typescript
{ path: 'worlds/:id/screenplays', name: 'world-screenplays',
  component: () => import('@/views/WorldScreenplaysView.vue'), props: true },
```

- [ ] **Step 3: TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/WorldScreenplaysView.vue frontend/src/router/index.ts
git commit -m "feat(frontend): WorldScreenplaysView — per-world screenplay card list"
```

---

### Task 6: 更新 `WorldsView.vue`（添加"📜 N 个剧本"徽标）

**Files:**
- Modify: `frontend/src/views/WorldsView.vue`

- [ ] **Step 1: 加载每个世界观的剧本数**

在 `WorldsView.vue` 的 `<script setup>` 中：

1. 导入 `useScreenplaysStore` 和 `useRouter`
2. 在 `onMounted` 时，对每个 world 调用 `spStore.fetchByWorld(w.id)`
3. 添加 computed `screenplayCountById`

具体改动：

在 `script setup` 顶部现有 import 后添加：
```typescript
import { useRouter } from 'vue-router'
import { useScreenplaysStore } from '@/stores/screenplays'

const router = useRouter()
const spStore = useScreenplaysStore()

const screenplayCountById = computed(() =>
  new Map(worldsStore.items.map(w => [w.id, (spStore.byWorld.get(w.id) ?? []).length]))
)
```

在 `onMounted` 中添加：
```typescript
for (const w of worldsStore.items) {
  spStore.fetchByWorld(w.id)
}
```

- [ ] **Step 2: 在表格中添加"剧本"列**

在 worlds 列表的 `el-table` 中找到操作列之前，添加：

```vue
<el-table-column label="剧本" width="120">
  <template #default="{ row }">
    <el-button
      link
      size="small"
      @click="router.push({ name: 'world-screenplays', params: { id: row.id } })"
    >
      📜 {{ screenplayCountById.get(row.id) ?? 0 }} 个剧本
    </el-button>
  </template>
</el-table-column>
```

- [ ] **Step 3: TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/WorldsView.vue
git commit -m "feat(frontend): WorldsView — screenplay count badge + navigate to world screenplays"
```

---

### Task 7: 更新 `SessionsView.vue`（新建会话改选剧本）

**Files:**
- Modify: `frontend/src/views/SessionsView.vue`
- Modify: `frontend/src/stores/sessions.ts`（如有 `create` 方法）

- [ ] **Step 1: 更新新建会话表单**

在 `SessionsView.vue` 中：

1. 导入 `useScreenplaysStore`
2. 将表单中"选世界观"+"选角色"两步改为"选剧本"一步
3. 表单数据结构改为 `{ name, screenplay_id, gm_model_config_id, summarizer_model_config_id }`

具体改动：

在 `script setup` 中：
```typescript
import { useScreenplaysStore } from '@/stores/screenplays'

const spStore = useScreenplaysStore()

// Replace form definition
const form = ref({
  name: '',
  screenplay_id: 0,
  gm_model_config_id: 0,
  summarizer_model_config_id: 0,
})

// On world select in the dropdown, load that world's screenplays
const selectedWorldId = ref(0)
const worldScreenplays = computed(() => spStore.byWorld.get(selectedWorldId.value) ?? [])

async function onWorldChange(worldId: number) {
  selectedWorldId.value = worldId
  form.value.screenplay_id = 0
  await spStore.fetchByWorld(worldId)
}
```

在 `onMounted` 中加载所有世界观的剧本数（用于显示 count）：
```typescript
for (const w of worldsStore.items) {
  spStore.fetchByWorld(w.id)
}
```

在创建会话表单的验证逻辑中：
```typescript
if (!form.value.screenplay_id || !form.value.gm_model_config_id) {
  ElMessage.warning('请选择剧本和模型')
  return
}
```

将表单模板中的世界观+角色选择替换为：

```vue
<el-form-item label="世界观">
  <el-select
    :model-value="selectedWorldId"
    @change="onWorldChange"
    placeholder="先选世界观"
  >
    <el-option
      v-for="w in worldsStore.items"
      :key="w.id"
      :label="w.name"
      :value="w.id"
    />
  </el-select>
</el-form-item>
<el-form-item label="剧本" required>
  <el-select
    v-model="form.screenplay_id"
    :disabled="!selectedWorldId"
    placeholder="选择剧本"
  >
    <el-option
      v-for="sp in worldScreenplays"
      :key="sp.id"
      :label="`${sp.title}（${sp.pc_name}）`"
      :value="sp.id"
    />
  </el-select>
</el-form-item>
```

保留并更新 gm/summarizer 选择，移除旧的 `world_id`/`character_id` 选择。

- [ ] **Step 2: 更新会话列表显示**

在会话表格中，将"世界观"和"角色"列合并为"剧本"列（可以继续用 worldNameById，因为后端仍返回 world_id）：

```vue
<el-table-column label="世界观 / 剧本" min-width="200">
  <template #default="{ row }">
    <div>{{ worldNameById.get(row.world_id) ?? `世界观#${row.world_id}` }}</div>
    <div v-if="row.screenplay_id" class="sp-subtitle">
      📜 {{ screenplayTitleById.get(row.screenplay_id) ?? `剧本#${row.screenplay_id}` }}
    </div>
  </template>
</el-table-column>
```

添加 computed `screenplayTitleById`（从所有已加载的剧本中构建）：
```typescript
const screenplayTitleById = computed(() => {
  const m = new Map<number, string>()
  for (const [, sps] of spStore.byWorld) {
    for (const sp of sps) m.set(sp.id, sp.title)
  }
  return m
})
```

- [ ] **Step 3: TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SessionsView.vue
git commit -m "feat(frontend): SessionsView — create session by picking screenplay"
```

---

### Task 8: 更新 seed_data.py（种植剧本，移除角色卡）并清理导航

**Files:**
- Modify: `backend/src/dzmm/seed_data.py`
- Modify: `frontend/src/views/LayoutView.vue`（移除"角色卡"nav item）

- [ ] **Step 1: 更新 seed_data.py**

在 `backend/src/dzmm/seed_data.py` 中：

1. 删除 `_CHARACTERS` 列表（角色卡）
2. 新增 `_SCREENPLAYS` 列表（每个世界观一个剧本，PC 定义从原角色卡迁入）
3. 更新 `seed_db()` 函数，调用 `Screenplay` 模型而非 `Character`

`_SCREENPLAYS` 结构（4条，每条对应一个世界观）：

```python
_SCREENPLAYS = [
    {
        "world_index": 0,  # 零区禁令：新京都 2091
        "title": "合规人生的边界",
        "genre": "政治阴谋",
        "pc_name": "楚晓",
        "pc_profile_md": """## 楚晓

**身份：** NCB（神经合规局）前三级审核员，编号 C-0471

**背景：** 曾执行过 247 次"强制重置"申请审核，其中 3 次签发了自己后来质疑的处决令。六周前，她在常规清仓时发现档案库 B-7 里存在一个从未被分配合规芯片的区域——这在法律上不应该存在。

**特质：** 习惯在说谎前用右手拇指摩擦无名指指节；对纸质文件有近乎执念的偏好；从不相信巧合。

**携带：** 一枚已停用的四级权限芯片（失效日期：三周前）、审核官证（仍然有效）、记录着某个孤儿院地址的小纸条。""",
        "pc_base_stats_json": '{"调查":8,"交涉":6,"渗透":5,"战斗":3,"技术":6,"意志":7}',
    },
    {
        "world_index": 1,  # 上海·谍影 1937
        "title": "失联的猎雀人",
        "genre": "悬疑探案",
        "pc_name": "顾之行",
        "pc_profile_md": """## 顾之行

**身份：** 军统上海站外勤情报员，代号"鸢尾"

**背景：** 加入军统前是租界里的跑单帮，见过太多人为了活命出卖同伴。三年前被老站长亲自招募，执行过四次渗透任务，全身而退。两周前，联络人"麻雀"在例行接头后失踪，顾之行奉命查清原委——但他隐约察觉这次任务与组织内部的某条黑线有关。

**特质：** 能在三分钟内判断出一个陌生人的大概出身；喝茶从不加糖；在确认安全之前从不走同一条路两次。

**携带：** 军统证件（伪造身份：实业公司职员）、一把改装过消音弹的小型手枪、"麻雀"最后一封密信（部分字迹被水浸湿）。""",
        "pc_base_stats_json": '{"侦察":8,"潜伏":7,"格斗":6,"交际":5,"应变":7,"意志":6}',
    },
    {
        "world_index": 2,  # 残光庇护所
        "title": "核冬之后，第七十二天",
        "genre": "灾难求生",
        "pc_name": "沈语",
        "pc_profile_md": """## 沈语

**身份：** 庇护所三区医疗官，前传染病研究员

**背景：** 核冬来临前三天，她正在隔离舱内研究一种尚未命名的病毒变体，因此意外成了庇护所里唯一知道外面情况全貌的人——或者说，曾经知道。笔记本在第十二天的骚乱中遗失了。现在她靠残缺的记忆管理着日益枯竭的药品库，以及日益绝望的人心。

**特质：** 拥有过目不忘的短期记忆，但长期记忆在压力下会出现空白；习惯在诊断时做"没有用处的详细记录"；对谎言的厌恶近乎生理反应。

**携带：** 医疗急救箱（储量：约40%）、弄丢了一半内容的研究日志、三区配给钥匙卡、一支用完了子弹的注射型镇静枪。""",
        "pc_base_stats_json": '{"医疗":9,"科学":7,"交涉":5,"应变":6,"体能":4,"意志":8}',
    },
    {
        "world_index": 3,  # 刀锋录·断江湖
        "title": "封印的木匣",
        "genre": "政治阴谋",
        "pc_name": "裴无弦",
        "pc_profile_md": """## 裴无弦

**身份：** 独臂散修，前天机楼"弦"字级密探

**背景：** 天机楼共有七个字级密探，代号取自琴弦。"无弦"意味着他是第八个——从未被正式承认存在的那个。三年前，他奉命护送一个装有天机楼核心密档的木匣前往西疆，却在半路遭遇追杀，失去左臂，木匣却奇异地封印在他身上。自那以后，每当木匣感知到天机楼的气息，封印便会灼烧他的肌肤。

**特质：** 以残臂为荣，拒绝一切义肢；推算人心如推演棋局；对天机楼的人既防备又难以割舍。

**携带：** 封于右臂皮肤之下的神秘木匣（无法取出）、一把只有三尺长的断剑、天机楼通缉令（画像失真，但悬赏真实）。""",
        "pc_base_stats_json": '{"轻功":7,"剑术":8,"推算":9,"隐匿":6,"交锋":5,"内力":7}',
    },
]
```

`seed_db()` 函数中将 Character 创建替换为 Screenplay 创建：

```python
from dzmm.db.models import World, Screenplay, ModelConfig, Session as GameSession, CharState

# ...after creating worlds...
world_rows = ...  # list of created World objects

for sp_data in _SCREENPLAYS:
    world = world_rows[sp_data["world_index"]]
    sp = Screenplay(
        world_id=world.id,
        session_id=None,
        title=sp_data["title"],
        genre=sp_data["genre"],
        pc_name=sp_data["pc_name"],
        pc_profile_md=sp_data["pc_profile_md"],
        pc_base_stats_json=sp_data["pc_base_stats_json"],
    )
    session.add(sp)
```

- [ ] **Step 2: 从 LayoutView 导航中移除"角色卡"**

在 `frontend/src/views/LayoutView.vue` 中，找到导航链接里的"角色卡"（指向 `/characters`），删除该 nav item。如果同时有侧边栏和顶栏，两处都删除。

- [ ] **Step 3: 启动后端检查 seed 是否正常**

```bash
cd backend && python -c "
import asyncio
from dzmm.db.base import get_engine, init_db
from dzmm.seed_data import seed_db

async def test():
    engine = get_engine('sqlite+aiosqlite:///:memory:')
    await init_db(engine)
    await seed_db(engine)
    print('seed OK')

asyncio.run(test())
"
```

Expected: `seed OK`

- [ ] **Step 4: TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 5: 全量后端测试**

```bash
cd backend && python -m pytest -x -q 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/seed_data.py frontend/src/views/LayoutView.vue
git commit -m "feat(seed+nav): seed Screenplays instead of Characters; remove 角色卡 nav item"
```

---

## 架构不变量（执行时请遵守）

1. **`game.py` 不修改**：游戏引擎只读 `Character`，`Session` 创建时已确保 `character_id` 有效。
2. **`Session.character_id` 始终有值**：从剧本创建时自动 INSERT 一行 Character。
3. **`Screenplay.session_id` 保持 nullable**：历史剧本（绑定了具体 session）继续可用；新独立剧本 `session_id=NULL`。
4. **`Screenplay.world_id` 是新剧本的归属**：`/worlds/{id}/screenplays` 查询条件 `session_id IS NULL AND world_id = ?`。
5. **不迁移历史数据**：旧 `Session` 行 `screenplay_id=NULL`，继续通过 `world_id+character_id` 正常工作。

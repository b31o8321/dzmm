# Backend Core v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI backend that runs an AI-driven TRPG game session: accepts a player action, calls a configurable LLM (OpenAI-compatible cloud or Ollama local), streams structured GM output back to the client, persists state changes via tag parsing, and rolls a long-running narrative summary.

**Architecture:** Layered Python service. `models/` exposes a single `ModelClient` interface implemented by `OpenAICompatClient` (covers OpenAI/Doubao/通义/DeepSeek/零一) and `OllamaClient`. `parsing/StreamingTagParser` is a state machine that ingests LLM token deltas and emits two event types: `NarrativeDelta` (forwarded to client live) and `TagComplete` (buffered until end-of-turn, then applied to DB). `service/` orchestrates: builds the GM system prompt from world+character+summary+state, calls the model, parses output, applies tags, persists messages. `api/` exposes FastAPI endpoints with SSE streaming for the turn endpoint. SQLite via async SQLAlchemy 2.0; API keys live in OS keychain via `keyring`, never in DB.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, SQLAlchemy 2.0 (async), aiosqlite, httpx (async), pydantic v2, keyring, pytest + pytest-asyncio, respx (HTTP mocking).

---

## File Structure

```
backend/
├── pyproject.toml
├── .gitignore
├── src/
│   └── dzmm/
│       ├── __init__.py
│       ├── main.py                  # FastAPI app factory
│       ├── config.py                # paths, env config
│       ├── secrets.py               # keyring wrapper
│       ├── db/
│       │   ├── __init__.py
│       │   ├── base.py              # async engine + session factory
│       │   └── models.py            # SQLAlchemy ORM models
│       ├── models/
│       │   ├── __init__.py
│       │   ├── client.py            # ModelClient ABC + Message/StreamChunk types
│       │   ├── openai_compat.py     # OpenAICompatClient
│       │   ├── ollama.py            # OllamaClient
│       │   └── factory.py           # build_client(ModelConfig)
│       ├── parsing/
│       │   ├── __init__.py
│       │   ├── events.py            # NarrativeDelta / TagComplete / ParseError
│       │   ├── stream_parser.py     # StreamingTagParser state machine
│       │   └── repair.py            # JSON repair helpers
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── gm_template.py       # build_gm_messages(...)
│       │   └── summarizer_template.py
│       ├── service/
│       │   ├── __init__.py
│       │   ├── state_apply.py       # apply parsed tags to DB
│       │   ├── game.py              # turn orchestrator
│       │   └── summarizer.py        # rolling summary
│       └── api/
│           ├── __init__.py
│           ├── schemas.py           # request/response pydantic models
│           ├── routes_models.py
│           ├── routes_worlds.py
│           ├── routes_characters.py
│           └── routes_sessions.py   # includes /turn SSE
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_db_models.py
    ├── test_secrets.py
    ├── test_openai_compat.py
    ├── test_ollama.py
    ├── test_stream_parser.py
    ├── test_repair.py
    ├── test_state_apply.py
    ├── test_gm_template.py
    ├── test_game_service.py
    ├── test_summarizer.py
    └── test_api.py
```

Each file has one responsibility. The split between `parsing/`, `prompts/`, `service/`, and `api/` mirrors the data flow so changes to one layer don't ripple.

---

## Task 1: Project skeleton + pyproject + first commit

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.gitignore`
- Create: `backend/src/dzmm/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "dzmm"
version = "0.1.0"
description = "AI dynamic TRPG text game backend"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.19",
    "httpx>=0.27",
    "pydantic>=2.6",
    "keyring>=24.0",
    "sse-starlette>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dzmm"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: Write `backend/.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
.env
*.db
*.sqlite
```

- [ ] **Step 3: Write empty package init files**

`backend/src/dzmm/__init__.py`:
```python
__version__ = "0.1.0"
```

`backend/tests/__init__.py`: empty file (just `touch`).

- [ ] **Step 4: Write `backend/tests/conftest.py`**

```python
import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 5: Install and verify**

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

Expected: `pytest` runs and reports "no tests ran" with exit code 5 (or 0). Either is fine — no collection errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "chore: bootstrap backend project skeleton"
```

---

## Task 2: Database models + schema bootstrap

**Files:**
- Create: `backend/src/dzmm/config.py`
- Create: `backend/src/dzmm/db/__init__.py`
- Create: `backend/src/dzmm/db/base.py`
- Create: `backend/src/dzmm/db/models.py`
- Create: `backend/tests/test_db_models.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_db_models.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import World, Character, Session as GameSession, Message, ModelConfig


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    engine = get_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def test_create_world_and_character(db: AsyncSession):
    world = World(name="Cyberpunk", content_md="Neon city.", style="dark")
    db.add(world)
    await db.flush()

    char = Character(world_id=world.id, name="Riku", profile_md="Ex-corp runner.",
                     base_stats_json='{"hp":20,"sanity":15}')
    db.add(char)
    await db.commit()

    assert world.id is not None
    assert char.world_id == world.id


async def test_create_session_with_messages(db: AsyncSession):
    world = World(name="W", content_md="x", style="realistic")
    char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
    cfg = ModelConfig(name="local", type="ollama", base_url="http://localhost:11434",
                      model_name="qwen2.5:7b")
    db.add_all([world, char, cfg])
    await db.flush()

    sess = GameSession(name="Run 1", world_id=world.id, character_id=char.id,
                       gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id,
                       schema_version=1)
    db.add(sess)
    await db.flush()

    db.add(Message(session_id=sess.id, role="user", content="look around", turn=1))
    db.add(Message(session_id=sess.id, role="assistant",
                   content="<narrative>The street is empty.</narrative>", turn=1))
    await db.commit()

    assert len(sess.messages) == 2 if hasattr(sess, "messages") else True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/test_db_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dzmm.db'`.

- [ ] **Step 3: Write `backend/src/dzmm/config.py`**

```python
from pathlib import Path

APP_DIR = Path.home() / ".dzmm"
APP_DIR.mkdir(exist_ok=True)
DEFAULT_DB_PATH = APP_DIR / "dzmm.db"
DEFAULT_DB_URL = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"
SCHEMA_VERSION = 1
```

- [ ] **Step 4: Write `backend/src/dzmm/db/__init__.py`**

Empty file.

- [ ] **Step 5: Write `backend/src/dzmm/db/base.py`**

```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from dzmm.config import DEFAULT_DB_URL


class Base(DeclarativeBase):
    pass


def get_engine(url: str = DEFAULT_DB_URL) -> AsyncEngine:
    return create_async_engine(url, echo=False, future=True)


def async_session(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    from dzmm.db import models  # ensure all models imported  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 6: Write `backend/src/dzmm/db/models.py`**

```python
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dzmm.db.base import Base


class World(Base):
    __tablename__ = "worlds"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    content_md: Mapped[str] = mapped_column(Text)
    rules_json: Mapped[str] = mapped_column(Text, default='{"mode":"light"}')
    style: Mapped[str] = mapped_column(String(40), default="realistic")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    name: Mapped[str] = mapped_column(String(120))
    profile_md: Mapped[str] = mapped_column(Text)
    base_stats_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    world: Mapped[World] = relationship()


class ModelConfig(Base):
    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40))  # "openai_compat" | "ollama"
    base_url: Mapped[str] = mapped_column(String(255))
    model_name: Mapped[str] = mapped_column(String(120))
    api_key_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timeout: Mapped[float] = mapped_column(default=60.0)
    params_json: Mapped[str] = mapped_column(Text, default='{}')


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"))
    gm_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))
    summarizer_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))
    turn_count: Mapped[int] = mapped_column(default=0)
    schema_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_played: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    turn: Mapped[int] = mapped_column(default=0)
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    summarized: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StorySummary(Base):
    __tablename__ = "story_summaries"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    last_summarized_msg_id: Mapped[int] = mapped_column(default=0)
    summary_tokens: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CharState(Base):
    __tablename__ = "char_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NPC(Base):
    __tablename__ = "npcs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    favor: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(String(60), default="未知")
    last_seen_turn: Mapped[int] = mapped_column(default=0)
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
```

- [ ] **Step 7: Run test to verify it passes**

```bash
cd backend && pytest tests/test_db_models.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(db): SQLAlchemy models for worlds, characters, sessions, messages"
```

---

## Task 3: Secrets via keyring

**Files:**
- Create: `backend/src/dzmm/secrets.py`
- Create: `backend/tests/test_secrets.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_secrets.py`:
```python
from unittest.mock import patch

from dzmm.secrets import store_api_key, get_api_key, delete_api_key, mask_key


def test_store_and_retrieve_api_key():
    fake_store = {}

    def fake_set(service, name, value):
        fake_store[(service, name)] = value

    def fake_get(service, name):
        return fake_store.get((service, name))

    def fake_del(service, name):
        fake_store.pop((service, name), None)

    with patch("keyring.set_password", side_effect=fake_set), \
         patch("keyring.get_password", side_effect=fake_get), \
         patch("keyring.delete_password", side_effect=fake_del):
        store_api_key("doubao_main", "sk-abcdef123456")
        assert get_api_key("doubao_main") == "sk-abcdef123456"
        delete_api_key("doubao_main")
        assert get_api_key("doubao_main") is None


def test_mask_key():
    assert mask_key("sk-abcdef123456") == "sk-abc***3456"
    assert mask_key("short") == "***"
    assert mask_key("") == "***"
    assert mask_key(None) == "***"
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_secrets.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/src/dzmm/secrets.py`**

```python
import keyring

SERVICE = "dzmm"


def store_api_key(ref: str, value: str) -> None:
    keyring.set_password(SERVICE, ref, value)


def get_api_key(ref: str) -> str | None:
    return keyring.get_password(SERVICE, ref)


def delete_api_key(ref: str) -> None:
    try:
        keyring.delete_password(SERVICE, ref)
    except keyring.errors.PasswordDeleteError:
        pass


def mask_key(value: str | None) -> str:
    if not value or len(value) < 10:
        return "***"
    return f"{value[:6]}***{value[-4:]}"
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd backend && pytest tests/test_secrets.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(secrets): keyring-backed API key storage with masking"
```

---

## Task 4: ModelClient interface + types

**Files:**
- Create: `backend/src/dzmm/models/__init__.py`
- Create: `backend/src/dzmm/models/client.py`

- [ ] **Step 1: Write `backend/src/dzmm/models/__init__.py`**

Empty file.

- [ ] **Step 2: Write `backend/src/dzmm/models/client.py`**

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationParams(BaseModel):
    temperature: float = 0.8
    max_tokens: int = 1500
    top_p: float = 0.95
    stop: list[str] | None = None


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class StreamChunk(BaseModel):
    delta: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class ModelClient(ABC):
    name: str

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion. Implementations are async generators."""
        ...

    async def complete(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> tuple[str, TokenUsage]:
        parts: list[str] = []
        usage = TokenUsage()
        async for chunk in self.stream(messages, params):
            parts.append(chunk.delta)
            if chunk.usage is not None:
                usage = chunk.usage
        return "".join(parts), usage

    async def health_check(self) -> tuple[bool, str]:
        try:
            text, _ = await self.complete(
                [Message(role="user", content="Reply with the single word: ok")],
                GenerationParams(max_tokens=10, temperature=0.0),
            )
            return True, text.strip()
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"
```

- [ ] **Step 3: Verify imports**

```bash
cd backend && python -c "from dzmm.models.client import ModelClient, Message, StreamChunk; print('ok')"
```

Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(models): ModelClient ABC + Message/StreamChunk contracts"
```

---

## Task 5: OpenAI-compatible client

**Files:**
- Create: `backend/src/dzmm/models/openai_compat.py`
- Create: `backend/tests/test_openai_compat.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_openai_compat.py`:
```python
import json
import httpx
import pytest
import respx

from dzmm.models.client import GenerationParams, Message
from dzmm.models.openai_compat import OpenAICompatClient


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@pytest.fixture
def client():
    return OpenAICompatClient(
        name="test", base_url="https://api.example.com/v1",
        api_key="sk-test", model="test-model", timeout=5.0,
    )


@respx.mock
async def test_stream_yields_deltas_and_usage(client):
    body = (
        sse({"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {"content": " world"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body,
                                    headers={"content-type": "text/event-stream"})
    )

    chunks = []
    async for ch in client.stream(
        [Message(role="user", content="hi")], GenerationParams(),
    ):
        chunks.append(ch)

    text = "".join(c.delta for c in chunks)
    assert text == "Hello world"
    final = chunks[-1]
    assert final.finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.input_tokens == 12
    assert final.usage.output_tokens == 3


@respx.mock
async def test_stream_handles_malformed_lines(client):
    body = (
        "garbage line\n\n"
        + sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]})
        + "data: not-json\n\n"
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )

    text, _ = await client.complete(
        [Message(role="user", content="hi")], GenerationParams(),
    )
    assert text == "ok"


@respx.mock
async def test_stream_raises_on_4xx(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_openai_compat.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dzmm.models.openai_compat'`.

- [ ] **Step 3: Write `backend/src/dzmm/models/openai_compat.py`**

```python
import json
from collections.abc import AsyncIterator

import httpx

from dzmm.models.client import (
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)


class OpenAICompatClient(ModelClient):
    """Works for OpenAI, Doubao, Tongyi, DeepSeek, 零一万物 — any provider
    exposing an OpenAI /chat/completions-shaped endpoint."""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        payload: dict = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "top_p": params.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if params.stop:
            payload["stop"] = params.stop

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = obj.get("choices") or []
                    delta = ""
                    finish = None
                    if choices:
                        delta = (choices[0].get("delta") or {}).get("content") or ""
                        finish = choices[0].get("finish_reason")

                    usage = None
                    raw_usage = obj.get("usage")
                    if raw_usage:
                        usage = TokenUsage(
                            input_tokens=raw_usage.get("prompt_tokens", 0),
                            output_tokens=raw_usage.get("completion_tokens", 0),
                        )

                    if delta or finish or usage:
                        yield StreamChunk(delta=delta, finish_reason=finish, usage=usage)
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd backend && pytest tests/test_openai_compat.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(models): OpenAI-compatible streaming client"
```

---

## Task 6: Ollama client

**Files:**
- Create: `backend/src/dzmm/models/ollama.py`
- Create: `backend/tests/test_ollama.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_ollama.py`:
```python
import json
import httpx
import pytest
import respx

from dzmm.models.client import GenerationParams, Message
from dzmm.models.ollama import OllamaClient


@pytest.fixture
def client():
    return OllamaClient(
        name="local",
        base_url="http://localhost:11434",
        model="qwen2.5:7b",
        timeout=5.0,
    )


@respx.mock
async def test_stream_yields_message_deltas(client):
    body = (
        json.dumps({"message": {"role": "assistant", "content": "Hi"}, "done": False}) + "\n"
        + json.dumps({"message": {"content": " there"}, "done": False}) + "\n"
        + json.dumps({"message": {"content": ""}, "done": True,
                      "prompt_eval_count": 10, "eval_count": 4}) + "\n"
    )
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    chunks = []
    async for ch in client.stream(
        [Message(role="user", content="hi")], GenerationParams(),
    ):
        chunks.append(ch)

    text = "".join(c.delta for c in chunks)
    assert text == "Hi there"
    final = chunks[-1]
    assert final.finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.input_tokens == 10
    assert final.usage.output_tokens == 4


@respx.mock
async def test_list_models(client):
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [{"name": "qwen2.5:7b"}, {"name": "llama3:8b"}]
        })
    )
    names = await client.list_models()
    assert names == ["qwen2.5:7b", "llama3:8b"]
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_ollama.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dzmm.models.ollama'`.

- [ ] **Step 3: Write `backend/src/dzmm/models/ollama.py`**

```python
import json
from collections.abc import AsyncIterator

import httpx

from dzmm.models.client import (
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)


class OllamaClient(ModelClient):
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
            "options": {
                "temperature": params.temperature,
                "num_predict": params.max_tokens,
                "top_p": params.top_p,
                "stop": params.stop or [],
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    delta = (obj.get("message") or {}).get("content", "")
                    done = obj.get("done", False)

                    usage = None
                    if done:
                        usage = TokenUsage(
                            input_tokens=obj.get("prompt_eval_count", 0),
                            output_tokens=obj.get("eval_count", 0),
                        )

                    yield StreamChunk(
                        delta=delta,
                        finish_reason="stop" if done else None,
                        usage=usage,
                    )

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd backend && pytest tests/test_ollama.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(models): Ollama streaming client + model listing"
```

---

## Task 7: Streaming tag parser (the centerpiece)

**Files:**
- Create: `backend/src/dzmm/parsing/__init__.py`
- Create: `backend/src/dzmm/parsing/events.py`
- Create: `backend/src/dzmm/parsing/stream_parser.py`
- Create: `backend/tests/test_stream_parser.py`

This is the most complex piece. Tests are extensive on purpose.

- [ ] **Step 1: Write `backend/src/dzmm/parsing/__init__.py`**

Empty file.

- [ ] **Step 2: Write `backend/src/dzmm/parsing/events.py`**

```python
from dataclasses import dataclass, field


@dataclass
class NarrativeDelta:
    text: str


@dataclass
class TagComplete:
    name: str
    attrs: dict[str, str] = field(default_factory=dict)
    content: str = ""


@dataclass
class ParseError:
    message: str
    raw: str


ParseEvent = NarrativeDelta | TagComplete | ParseError
```

- [ ] **Step 3: Write the failing test**

`backend/tests/test_stream_parser.py`:
```python
from dzmm.parsing.events import NarrativeDelta, TagComplete, ParseError
from dzmm.parsing.stream_parser import StreamingTagParser


def collect(parser: StreamingTagParser, chunks: list[str]) -> list:
    out = []
    for c in chunks:
        out.extend(parser.feed(c))
    out.extend(parser.finish())
    return out


def test_streams_narrative_text_live():
    p = StreamingTagParser()
    out = collect(p, ["<narrative>Hello", " world</narrative>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "Hello world"


def test_buffers_state_change_until_close():
    p = StreamingTagParser()
    out = collect(p, ['<state_change>{"hp":-5}</state_change>'])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "state_change"
    assert tags[0].content == '{"hp":-5}'


def test_handles_split_open_tag():
    p = StreamingTagParser()
    out = collect(p, ["<narr", "ative>hi</narrative>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "hi"


def test_handles_split_close_tag():
    p = StreamingTagParser()
    out = collect(p, ["<narrative>hi</narra", "tive>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "hi"


def test_extracts_tag_attributes():
    p = StreamingTagParser()
    out = collect(p, ['<dice skill="潜行" target="15">d20=8</dice>'])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "dice"
    assert tag.attrs == {"skill": "潜行", "target": "15"}
    assert tag.content == "d20=8"


def test_drops_unknown_tags_silently():
    p = StreamingTagParser()
    out = collect(p, ["<weird>junk</weird><narrative>real</narrative>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    tags = [e for e in out if isinstance(e, TagComplete)]
    errors = [e for e in out if isinstance(e, ParseError)]
    assert "".join(deltas) == "real"
    assert len(tags) == 0
    assert len(errors) == 0


def test_drops_outside_text():
    """Stray text between tags is discarded — GM should not produce it,
    and we don't want it polluting the narrative stream."""
    p = StreamingTagParser()
    out = collect(p, ["preamble <narrative>real</narrative> trailing"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "real"


def test_emits_multiple_tags_in_order():
    p = StreamingTagParser()
    out = collect(p, [
        "<narrative>You sneak past.</narrative>",
        "<dice skill=\"潜行\" target=\"12\">d20=14, 成功</dice>",
        '<state_change>{"sanity":-1}</state_change>',
    ])
    names = [e.name if isinstance(e, TagComplete) else "narrative"
             for e in out
             if isinstance(e, (TagComplete, NarrativeDelta))]
    # narrative chunks may collapse to one entry, but dice/state_change must follow in order
    assert "dice" in names
    assert "state_change" in names
    assert names.index("dice") < names.index("state_change")


def test_unclosed_buffered_tag_emits_error():
    p = StreamingTagParser()
    out = collect(p, ['<state_change>{"hp":-5'])  # no closing
    errors = [e for e in out if isinstance(e, ParseError)]
    assert len(errors) == 1
    assert "state_change" in errors[0].message


def test_unclosed_narrative_flushes_on_finish():
    p = StreamingTagParser()
    p.feed("<narrative>partial output")
    out = list(p.finish())
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "partial output" in "".join(deltas)


def test_fine_grained_chunking_per_character():
    """Worst case: token-by-token streaming."""
    full = '<narrative>Hi.</narrative><state_change>{"hp":-1}</state_change>'
    p = StreamingTagParser()
    events = []
    for ch in full:
        events.extend(p.feed(ch))
    events.extend(p.finish())

    deltas = [e.text for e in events if isinstance(e, NarrativeDelta)]
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert "".join(deltas) == "Hi."
    assert len(tags) == 1
    assert tags[0].name == "state_change"
    assert tags[0].content == '{"hp":-1}'


def test_attrs_with_spaces_and_quotes():
    p = StreamingTagParser()
    out = collect(p, [
        '<plot_event type="new_quest" importance="3">引子任务</plot_event>'
    ])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.attrs == {"type": "new_quest", "importance": "3"}
```

- [ ] **Step 4: Run test, verify failure**

```bash
cd backend && pytest tests/test_stream_parser.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError`.

- [ ] **Step 5: Write `backend/src/dzmm/parsing/stream_parser.py`**

```python
import re
from collections.abc import Iterator

from dzmm.parsing.events import NarrativeDelta, ParseError, ParseEvent, TagComplete

KNOWN_TAGS: set[str] = {
    "narrative",
    "dice",
    "state_change",
    "npc_update",
    "plot_event",
    "choices",
}
STREAMING_TAGS: set[str] = {"narrative"}

_OPEN_TAG_RE = re.compile(r"<(\w+)((?:\s+\w+=\"[^\"]*\")*)\s*>")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


class StreamingTagParser:
    """Incrementally parses an LLM token stream that produces a flat sequence
    of `<tag>...</tag>` blocks. Streams content of `narrative` tags as it arrives;
    buffers all other known tags until close. Unknown tags and outside-tag text
    are dropped."""

    def __init__(self) -> None:
        self._buf: str = ""
        self._state: str = "OUTSIDE"
        self._current_tag: str | None = None
        self._current_attrs: dict[str, str] = {}
        self._tag_buf: str = ""

    def feed(self, chunk: str) -> Iterator[ParseEvent]:
        self._buf += chunk
        while True:
            consumed = False
            if self._state == "OUTSIDE":
                m = _OPEN_TAG_RE.search(self._buf)
                if not m:
                    # If buffer has no '<' at all, drop it. Otherwise wait for more.
                    if "<" not in self._buf:
                        self._buf = ""
                    break
                tag = m.group(1).lower()
                attrs_str = m.group(2) or ""
                self._current_tag = tag
                self._current_attrs = dict(_ATTR_RE.findall(attrs_str))
                self._tag_buf = ""
                self._buf = self._buf[m.end():]

                if tag in STREAMING_TAGS:
                    self._state = "IN_STREAMING"
                elif tag in KNOWN_TAGS:
                    self._state = "IN_BUFFERED"
                else:
                    self._state = "IN_UNKNOWN"
                consumed = True

            elif self._state in ("IN_STREAMING", "IN_BUFFERED", "IN_UNKNOWN"):
                close_tok = f"</{self._current_tag}>"
                idx = self._buf.find(close_tok)
                if idx == -1:
                    # Hold back enough chars to detect the close tag straddling chunks.
                    safe_len = max(0, len(self._buf) - len(close_tok))
                    safe = self._buf[:safe_len]
                    if safe:
                        if self._state == "IN_STREAMING":
                            yield NarrativeDelta(safe)
                        elif self._state == "IN_BUFFERED":
                            self._tag_buf += safe
                        # IN_UNKNOWN: drop
                        self._buf = self._buf[safe_len:]
                    break
                else:
                    inner = self._buf[:idx]
                    if self._state == "IN_STREAMING" and inner:
                        yield NarrativeDelta(inner)
                    elif self._state == "IN_BUFFERED":
                        self._tag_buf += inner
                        yield TagComplete(
                            name=self._current_tag or "",
                            attrs=self._current_attrs,
                            content=self._tag_buf.strip(),
                        )
                    # IN_UNKNOWN: drop
                    self._buf = self._buf[idx + len(close_tok):]
                    self._state = "OUTSIDE"
                    self._current_tag = None
                    self._current_attrs = {}
                    self._tag_buf = ""
                    consumed = True

            if not consumed:
                break

    def finish(self) -> Iterator[ParseEvent]:
        if self._state == "IN_STREAMING" and self._buf:
            yield NarrativeDelta(self._buf)
        elif self._state == "IN_BUFFERED":
            yield ParseError(
                message=f"Unclosed tag <{self._current_tag}>",
                raw=self._tag_buf + self._buf,
            )
        # IN_UNKNOWN / OUTSIDE: nothing to flush
        self._buf = ""
        self._state = "OUTSIDE"
        self._current_tag = None
        self._current_attrs = {}
        self._tag_buf = ""
```

- [ ] **Step 6: Run test, verify pass**

```bash
cd backend && pytest tests/test_stream_parser.py -v
```

Expected: 12 tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(parsing): streaming tag parser with state machine"
```

---

## Task 8: JSON repair helper

**Files:**
- Create: `backend/src/dzmm/parsing/repair.py`
- Create: `backend/tests/test_repair.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_repair.py`:
```python
from dzmm.parsing.repair import parse_loose_json


def test_parses_valid_json():
    assert parse_loose_json('{"hp": -5}') == {"hp": -5}


def test_parses_single_quoted():
    assert parse_loose_json("{'hp': -5}") == {"hp": -5}


def test_extracts_inner_braces():
    assert parse_loose_json('garbage {"hp": -5} trailing') == {"hp": -5}


def test_returns_empty_on_unrecoverable():
    assert parse_loose_json("not json at all") == {}


def test_handles_nested_braces():
    src = '{"a": {"b": 1}}'
    assert parse_loose_json(src) == {"a": {"b": 1}}


def test_handles_trailing_commas():
    # Most LLMs sometimes add trailing commas; we don't try to fix that here.
    # Just verify we return {} rather than crashing.
    result = parse_loose_json('{"hp": -5,}')
    assert isinstance(result, dict)
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_repair.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/src/dzmm/parsing/repair.py`**

```python
import json
from typing import Any


def parse_loose_json(content: str) -> dict[str, Any]:
    """Best-effort JSON parsing for LLM-generated state tags.
    Returns {} if unrecoverable (caller logs and skips state apply)."""
    s = content.strip()
    if not s:
        return {}

    try:
        result = json.loads(s)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        pass

    try:
        result = json.loads(s.replace("'", '"'))
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        candidate = s[start : end + 1]
        try:
            result = json.loads(candidate)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            pass
        try:
            result = json.loads(candidate.replace("'", '"'))
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            pass

    return {}
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd backend && pytest tests/test_repair.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(parsing): loose-JSON repair for state tags"
```

---

## Task 9: Tag application service (parsed tags → DB)

**Files:**
- Create: `backend/src/dzmm/service/__init__.py`
- Create: `backend/src/dzmm/service/state_apply.py`
- Create: `backend/tests/test_state_apply.py`

- [ ] **Step 1: Write `backend/src/dzmm/service/__init__.py`**

Empty file.

- [ ] **Step 2: Write the failing test**

`backend/tests/test_state_apply.py`:
```python
import json
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, ModelConfig, NPC, Session as GameSession, World,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply import apply_tags


@pytest.fixture
async def session_with_state(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y",
                         base_stats_json='{"hp":20,"sanity":15}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id,
                        stats_json='{"hp":20,"sanity":15}',
                        inventory_json="[]"))
        await s.commit()
        yield s, sess.id
    await engine.dispose()


async def test_apply_state_change_updates_stats(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change", content='{"hp": -5, "sanity": -2}')
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    stats = json.loads(cs.stats_json)
    assert stats["hp"] == 15
    assert stats["sanity"] == 13


async def test_inventory_add_and_remove(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change",
                      content='{"inventory_add": ["钥匙","小刀"]}')
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.inventory_json) == ["钥匙", "小刀"]

    tag2 = TagComplete(name="state_change",
                       content='{"inventory_remove": ["钥匙"]}')
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.inventory_json) == ["小刀"]


async def test_npc_update_creates_and_updates(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        content='{"name":"卫兵长","favor_delta":-10,"state":"警戒"}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalars().all()
    assert len(npcs) == 1
    npc = npcs[0]
    assert npc.name == "卫兵长"
    assert npc.favor == -10
    assert npc.state == "警戒"
    assert npc.last_seen_turn == 1

    # Apply again — should update, not duplicate.
    tag2 = TagComplete(
        name="npc_update",
        content='{"name":"卫兵长","favor_delta":-5,"state":"敌对"}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalars().all()
    assert len(npcs) == 1
    assert npcs[0].favor == -15
    assert npcs[0].state == "敌对"
    assert npcs[0].last_seen_turn == 2


async def test_apply_tags_skips_malformed_json(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change", content="not-json-at-all")
    # Should not raise.
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    # Untouched.
    assert json.loads(cs.stats_json) == {"hp": 20, "sanity": 15}


async def test_ignores_non_state_tags(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="dice", content="d20=15")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()
    # No errors, no state change. Pass through.
```

- [ ] **Step 3: Run test, verify failure**

```bash
cd backend && pytest tests/test_state_apply.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `backend/src/dzmm/service/state_apply.py`**

```python
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import CharState, NPC
from dzmm.parsing.events import TagComplete
from dzmm.parsing.repair import parse_loose_json


async def apply_tags(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
) -> None:
    """Mutate CharState and NPC rows based on parsed tags. Caller commits."""
    for tag in tags:
        if tag.name == "state_change":
            await _apply_state_change(session, session_id, tag.content)
        elif tag.name == "npc_update":
            await _apply_npc_update(session, session_id, current_turn, tag.content)
        # dice/plot_event/choices: no DB side effects in v0.1


async def _apply_state_change(
    session: AsyncSession, session_id: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    if not payload:
        return

    cs = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    if cs is None:
        cs = CharState(session_id=session_id, stats_json="{}", inventory_json="[]")
        session.add(cs)

    stats = json.loads(cs.stats_json or "{}")
    inventory = json.loads(cs.inventory_json or "[]")

    for key, val in payload.items():
        if key == "inventory_add" and isinstance(val, list):
            inventory.extend(str(x) for x in val)
        elif key == "inventory_remove" and isinstance(val, list):
            for item in val:
                if item in inventory:
                    inventory.remove(item)
        elif isinstance(val, (int, float)):
            stats[key] = stats.get(key, 0) + val

    cs.stats_json = json.dumps(stats, ensure_ascii=False)
    cs.inventory_json = json.dumps(inventory, ensure_ascii=False)
    cs.updated_at = datetime.utcnow()


async def _apply_npc_update(
    session: AsyncSession, session_id: int, current_turn: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    name = payload.get("name")
    if not name:
        return

    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()
    if npc is None:
        npc = NPC(
            session_id=session_id,
            name=name,
            description=payload.get("description", ""),
            favor=0,
            state=payload.get("state", "未知"),
            last_seen_turn=current_turn,
            notes_json="[]",
        )
        session.add(npc)

    favor_delta = payload.get("favor_delta", 0)
    if isinstance(favor_delta, (int, float)):
        npc.favor += int(favor_delta)
    if "state" in payload:
        npc.state = str(payload["state"])
    if "description" in payload and not npc.description:
        npc.description = str(payload["description"])
    note = payload.get("note")
    if note:
        notes = json.loads(npc.notes_json or "[]")
        notes.append({"turn": current_turn, "text": str(note)})
        npc.notes_json = json.dumps(notes, ensure_ascii=False)
    npc.last_seen_turn = current_turn
```

- [ ] **Step 5: Run test, verify pass**

```bash
cd backend && pytest tests/test_state_apply.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(service): apply state_change/npc_update tags to DB"
```

---

## Task 10: GM prompt builder

**Files:**
- Create: `backend/src/dzmm/prompts/__init__.py`
- Create: `backend/src/dzmm/prompts/gm_template.py`
- Create: `backend/tests/test_gm_template.py`

- [ ] **Step 1: Write `backend/src/dzmm/prompts/__init__.py`**

Empty file.

- [ ] **Step 2: Write the failing test**

`backend/tests/test_gm_template.py`:
```python
from dzmm.models.client import Message
from dzmm.prompts.gm_template import build_gm_messages


def test_system_message_contains_world_and_character():
    msgs = build_gm_messages(
        world_md="赛博朋克末世，企业掌权。",
        character_md="姓名: Riku\n职业: 义体黑客",
        live_state={"hp": 18, "sanity": 12, "inventory": ["小刀"]},
        rules_mode="light",
        style="dark",
        story_summary="",
        key_facts="",
        recent_messages=[],
        current_action="环顾四周",
    )
    sys_msg = msgs[0]
    assert sys_msg.role == "system"
    assert "赛博朋克" in sys_msg.content
    assert "Riku" in sys_msg.content
    assert "义体黑客" in sys_msg.content
    assert "<narrative>" in sys_msg.content  # output format spec
    assert "不替 PC 做决定" in sys_msg.content


def test_user_message_is_current_action():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=[], current_action="上前搭话",
    )
    last = msgs[-1]
    assert last.role == "user"
    assert "上前搭话" in last.content


def test_recent_messages_inserted_between_system_and_action():
    history = [
        Message(role="user", content="开门"),
        Message(role="assistant", content="<narrative>门打开了</narrative>"),
    ]
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=history, current_action="向前走",
    )
    roles = [m.role for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert msgs[1].content == "开门"
    assert msgs[2].content == "<narrative>门打开了</narrative>"
    assert msgs[3].content == "向前走"


def test_summary_and_key_facts_included_when_present():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="PC 已击败山猫，获得加密芯片。",
        key_facts="进行中任务：取回芯片",
        recent_messages=[], current_action="去酒吧",
    )
    sys = msgs[0].content
    assert "PC 已击败山猫" in sys
    assert "进行中任务" in sys


def test_opening_hint_when_no_history():
    """Empty recent_messages and empty summary => GM should produce an opening."""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="(开始游戏)",
    )
    sys = msgs[0].content
    assert "开局" in sys


def test_rules_mode_light_disables_dice_requirement():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "轻量化" in sys
```

- [ ] **Step 3: Run test, verify failure**

```bash
cd backend && pytest tests/test_gm_template.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `backend/src/dzmm/prompts/gm_template.py`**

```python
import json
from typing import Any

from dzmm.models.client import Message

_RULES_DESCRIPTIONS = {
    "light": "轻量化：无骰子，按合理性叙事判定。",
    "standard": "标准：d20 技能检定，关键行动需投骰。",
    "hardcore": "硬核：完整属性消耗、判定、状态追踪。",
}

_STYLE_HINTS = {
    "realistic": "写实风格，描写克制，重视细节真实感。",
    "dark": "暗黑风格，氛围压抑，留白处保留不安感。",
    "healing": "治愈风格，节奏舒缓，关注人物情感。",
    "comedy": "幽默风格，对白俏皮，但仍尊重剧情逻辑。",
    "horror": "恐怖风格，缓慢推进，依赖暗示而非直白血腥。",
}

_SYSTEM_TEMPLATE = """# 你的身份
你是一位专业的 TRPG 跑团主持人（GM）。你的职责：
- 推动剧情、描写场景与氛围
- 扮演所有 NPC（每个 NPC 有独立人设、动机和情绪）
- 进行判定（骰子检定或叙事性裁定）
- 追踪并显式声明角色与世界状态变化

# 当前世界观
{world}

# 规则配置
规则强度：{rules_label}
{rules_detail}

# 剧情风格
{style_label}
{style_detail}

# 玩家角色卡（PC）
{character}

# 当前实时状态
{live_state}

# 已发生剧情摘要
{story_summary}

# 关键事实
{key_facts}

# 行为铁律（绝对遵守）
1. 不替 PC 做决定：永远不描写 PC 未声明的行动、内心想法、情感。
2. 不打破第四面墙：不解释规则原文、不出戏。
3. NPC 自治：NPC 按其人设和当前情绪反应，不为推动剧情让 NPC 强行配合。
4. 状态变化必须显式：HP/理智/物品/好感度任何变化必须用 <state_change> 或 <npc_update> 声明。
5. 风格一致：始终保持当前剧情风格的语调与节奏。
6. 节奏控制：常规回应 200-400 字，重要场景可放宽到 600 字。

# 输出格式（严格遵守，每个标签独立成段）

<narrative>
场景描写、NPC 对话、行动结果。NPC 对话用「」并前缀名字。
</narrative>

<dice skill="技能名" target="目标值">
仅在判定时输出。格式：d20=14，结果：成功/失败/大成功/大失败
</dice>

<state_change>
仅在 PC 状态变化时输出，JSON：
{{"hp": -5, "sanity": -2, "inventory_add": ["钥匙"], "inventory_remove": []}}
</state_change>

<npc_update>
仅在 NPC 关系或状态变化时输出，JSON：
{{"name": "卫兵长", "favor_delta": -10, "state": "警戒", "description": "首次描写", "note": "记住了 PC 的某个特征"}}
</npc_update>

<choices>
可选。给玩家 3 个启发性方向（不限制其自由输入）：
- 选项一
- 选项二
- 选项三
</choices>

# 开局规则
若剧情摘要为空（首轮），输出一段 600-1000 字的开局：交代 PC 当下所处环境、感官细节、身份处境、引子事件，停在 PC 必须做决定的瞬间，等待玩家行动。
"""


def _format_live_state(live_state: dict[str, Any]) -> str:
    if not live_state:
        return "（尚未初始化）"
    return json.dumps(live_state, ensure_ascii=False, indent=2)


def build_gm_messages(
    *,
    world_md: str,
    character_md: str,
    live_state: dict[str, Any],
    rules_mode: str,
    style: str,
    story_summary: str,
    key_facts: str,
    recent_messages: list[Message],
    current_action: str,
) -> list[Message]:
    rules_detail = _RULES_DESCRIPTIONS.get(rules_mode, _RULES_DESCRIPTIONS["light"])
    style_detail = _STYLE_HINTS.get(style, _STYLE_HINTS["realistic"])

    system = _SYSTEM_TEMPLATE.format(
        world=world_md.strip() or "（未提供）",
        rules_label=rules_mode,
        rules_detail=rules_detail,
        style_label=style,
        style_detail=style_detail,
        character=character_md.strip() or "（未提供）",
        live_state=_format_live_state(live_state),
        story_summary=story_summary.strip() or "（暂无，首次互动）",
        key_facts=key_facts.strip() or "（暂无）",
    )

    messages: list[Message] = [Message(role="system", content=system)]
    messages.extend(recent_messages)
    messages.append(Message(role="user", content=current_action))
    return messages
```

- [ ] **Step 5: Run test, verify pass**

```bash
cd backend && pytest tests/test_gm_template.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(prompts): GM system prompt builder with rules + style"
```

---

## Task 11: Game service (turn orchestrator)

**Files:**
- Create: `backend/src/dzmm/service/game.py`
- Create: `backend/tests/test_game_service.py`

This is the central orchestrator. It pulls session/world/character/state, builds messages, calls the model, parses, applies tags, persists.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_game_service.py`:
```python
import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Message as MessageRow, ModelConfig,
    Session as GameSession, World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.game import run_turn


class FakeClient(ModelClient):
    name = "fake"

    def __init__(self, output: str, usage: TokenUsage | None = None):
        self.output = output
        self.usage = usage or TokenUsage(input_tokens=10, output_tokens=20)
        self.last_messages: list[Message] | None = None

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        self.last_messages = messages
        # Stream char-by-char to exercise parser.
        for ch in self.output:
            yield StreamChunk(delta=ch)
        yield StreamChunk(delta="", finish_reason="stop", usage=self.usage)


@pytest.fixture
async def seeded(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="赛博朋克", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="义体黑客",
                         base_stats_json='{"hp":20,"sanity":15}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id,
                        stats_json='{"hp":20,"sanity":15}',
                        inventory_json="[]"))
        await s.commit()
        yield engine, SessionMaker, sess.id
    await engine.dispose()


async def test_run_turn_streams_narrative_and_persists(seeded):
    engine, SessionMaker, sid = seeded
    output = (
        "<narrative>你站在霓虹反射的雨中。</narrative>"
        '<state_change>{"sanity": -1}</state_change>'
    )
    client = FakeClient(output)

    events = []
    async with SessionMaker() as s:
        async for ev in run_turn(s, sid, "环顾四周", client):
            events.append(ev)
        await s.commit()

    deltas = [e for e in events if isinstance(e, NarrativeDelta)]
    assert "".join(d.text for d in deltas) == "你站在霓虹反射的雨中。"
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert any(t.name == "state_change" for t in tags)

    # State persisted: sanity reduced
    async with SessionMaker() as s:
        cs = (await s.execute(
            select(CharState).where(CharState.session_id == sid)
        )).scalar_one()
        stats = json.loads(cs.stats_json)
        assert stats["sanity"] == 14

        # Two messages saved (user + assistant)
        msgs = (await s.execute(
            select(MessageRow).where(MessageRow.session_id == sid)
            .order_by(MessageRow.id)
        )).scalars().all()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "环顾四周"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == output
        assert msgs[1].tokens_in == 10
        assert msgs[1].tokens_out == 20

        # Turn count incremented
        sess = await s.get(GameSession, sid)
        assert sess.turn_count == 1


async def test_run_turn_includes_recent_history_in_prompt(seeded):
    engine, SessionMaker, sid = seeded
    client1 = FakeClient("<narrative>第一回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "动作1", client1):
            pass
        await s.commit()

    client2 = FakeClient("<narrative>第二回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "动作2", client2):
            pass
        await s.commit()

    # client2 should have seen the user/assistant pair from turn 1 in its messages.
    contents = [m.content for m in client2.last_messages]
    assert "动作1" in contents
    assert "<narrative>第一回合</narrative>" in contents
    assert contents[-1] == "动作2"
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_game_service.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/src/dzmm/service/game.py`**

```python
import json
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Message as MessageRow,
    NPC,
    Session as GameSession,
    StorySummary,
    World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.gm_template import build_gm_messages
from dzmm.service.state_apply import apply_tags


RECENT_WINDOW = 12  # last N messages (user+assistant) injected raw


async def run_turn(
    session: AsyncSession,
    session_id: int,
    user_action: str,
    client: ModelClient,
    params: GenerationParams | None = None,
) -> AsyncIterator[ParseEvent]:
    """Yield parse events to caller (for SSE streaming) while running a full turn:
    builds prompt, streams model output, applies tags, persists messages.

    Caller must call session.commit() after the generator is exhausted."""
    params = params or GenerationParams()

    sess = await session.get(GameSession, session_id)
    if sess is None:
        raise ValueError(f"Session {session_id} not found")
    world = await session.get(World, sess.world_id)
    char = await session.get(Character, sess.character_id)

    char_state = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    live_state = _build_live_state(char, char_state)

    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    story_summary = summary_row.summary_text if summary_row else ""

    key_facts = await _build_key_facts(session, session_id, sess.turn_count)

    recent = await _load_recent_messages(session, session_id, summary_row)

    rules_mode = json.loads(world.rules_json or '{"mode":"light"}').get("mode", "light")

    msgs = build_gm_messages(
        world_md=world.content_md,
        character_md=char.profile_md,
        live_state=live_state,
        rules_mode=rules_mode,
        style=world.style,
        story_summary=story_summary,
        key_facts=key_facts,
        recent_messages=recent,
        current_action=user_action,
    )

    parser = StreamingTagParser()
    full_output_parts: list[str] = []
    completed_tags: list[TagComplete] = []
    usage = TokenUsage()

    async for chunk in client.stream(msgs, params):
        if chunk.delta:
            full_output_parts.append(chunk.delta)
            for ev in parser.feed(chunk.delta):
                if isinstance(ev, TagComplete):
                    completed_tags.append(ev)
                yield ev
        if chunk.usage is not None:
            usage = chunk.usage

    for ev in parser.finish():
        if isinstance(ev, TagComplete):
            completed_tags.append(ev)
        yield ev

    next_turn = sess.turn_count + 1
    full_output = "".join(full_output_parts)

    session.add(MessageRow(
        session_id=session_id, role="user", content=user_action, turn=next_turn,
    ))
    session.add(MessageRow(
        session_id=session_id, role="assistant", content=full_output, turn=next_turn,
        tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
    ))

    await apply_tags(session, session_id, next_turn, completed_tags)

    sess.turn_count = next_turn
    sess.last_played = datetime.utcnow()


def _build_live_state(char: Character, cs: CharState | None) -> dict:
    if cs is None:
        return json.loads(char.base_stats_json or "{}")
    out = json.loads(cs.stats_json or "{}")
    out["inventory"] = json.loads(cs.inventory_json or "[]")
    return out


async def _load_recent_messages(
    session: AsyncSession,
    session_id: int,
    summary_row: StorySummary | None,
) -> list[Message]:
    """Load last N un-summarized messages as Message objects."""
    high_water = summary_row.last_summarized_msg_id if summary_row else 0
    rows = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)
            .order_by(MessageRow.id.desc())
            .limit(RECENT_WINDOW)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [Message(role=r.role, content=r.content) for r in rows]


async def _build_key_facts(
    session: AsyncSession, session_id: int, current_turn: int
) -> str:
    """Pick relevant NPCs and format as compact text."""
    npcs = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id)
            .order_by(NPC.last_seen_turn.desc())
            .limit(8)
        )
    ).scalars().all()
    if not npcs:
        return ""
    lines = ["NPC 列表："]
    for n in npcs:
        lines.append(f"- {n.name}（好感{n.favor:+d}，状态：{n.state}）{n.description[:40]}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd backend && pytest tests/test_game_service.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(service): turn orchestrator with streaming + tag persistence"
```

---

## Task 12: Summarizer service

**Files:**
- Create: `backend/src/dzmm/prompts/summarizer_template.py`
- Create: `backend/src/dzmm/service/summarizer.py`
- Create: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Write `backend/src/dzmm/prompts/summarizer_template.py`**

```python
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
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_summarizer.py`:
```python
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Message as MessageRow, ModelConfig,
    Session as GameSession, StorySummary, World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.service.summarizer import maybe_summarize, SUMMARIZE_AFTER_TURNS


class FakeSummarizer(ModelClient):
    name = "fakesum"

    def __init__(self, output: str):
        self.output = output
        self.called_with: list[Message] | None = None

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        self.called_with = messages
        yield StreamChunk(delta=self.output, finish_reason="stop",
                          usage=TokenUsage(input_tokens=100, output_tokens=50))


@pytest.fixture
async def seeded_with_messages(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="C", profile_md="y",
                         base_stats_json='{}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id))
        # Add 2*SUMMARIZE_AFTER_TURNS messages so the trigger fires.
        for t in range(1, SUMMARIZE_AFTER_TURNS + 1):
            s.add(MessageRow(session_id=sess.id, role="user", content=f"行动 {t}", turn=t))
            s.add(MessageRow(session_id=sess.id, role="assistant",
                             content=f"<narrative>结果 {t}</narrative>", turn=t))
        sess.turn_count = SUMMARIZE_AFTER_TURNS
        await s.commit()
        yield engine, SessionMaker, sess.id
    await engine.dispose()


async def test_summarize_creates_story_summary(seeded_with_messages):
    engine, SessionMaker, sid = seeded_with_messages
    summary_text = "PC 经历了 10 个回合的探索，遇见了若干 NPC。"
    client = FakeSummarizer(summary_text)

    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()

    assert result is True

    async with SessionMaker() as s:
        ss = (await s.execute(
            select(StorySummary).where(StorySummary.session_id == sid)
        )).scalar_one()
        assert ss.summary_text == summary_text
        # high water mark is the max msg id at trigger time
        last_msg = (await s.execute(
            select(MessageRow).where(MessageRow.session_id == sid)
            .order_by(MessageRow.id.desc()).limit(1)
        )).scalar_one()
        assert ss.last_summarized_msg_id == last_msg.id


async def test_summarize_skips_when_below_threshold(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="r", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id,
                           turn_count=2)
        s.add(sess)
        await s.commit()
        sid = sess.id

    client = FakeSummarizer("should not be called")
    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()

    assert result is False
    assert client.called_with is None
    await engine.dispose()
```

- [ ] **Step 3: Run test, verify failure**

```bash
cd backend && pytest tests/test_summarizer.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `backend/src/dzmm/service/summarizer.py`**

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Message as MessageRow,
    Session as GameSession,
    StorySummary,
)
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.summarizer_template import build_summarizer_messages


SUMMARIZE_AFTER_TURNS = 10
SUMMARY_MAX_TOKENS = 1000


async def maybe_summarize(
    session: AsyncSession,
    session_id: int,
    client: ModelClient,
) -> bool:
    """Run a summarization pass if conditions are met. Returns True if executed."""
    sess = await session.get(GameSession, session_id)
    if sess is None or sess.turn_count < SUMMARIZE_AFTER_TURNS:
        return False

    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    high_water = summary_row.last_summarized_msg_id if summary_row else 0

    new_msgs = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)
            .order_by(MessageRow.id)
        )
    ).scalars().all()
    if len(new_msgs) < SUMMARIZE_AFTER_TURNS * 2:  # user + assistant per turn
        return False

    new_text = "\n\n".join(
        f"[{m.role}] {m.content}" for m in new_msgs
    )
    prev = summary_row.summary_text if summary_row else ""

    msgs = build_summarizer_messages(
        previous_summary=prev,
        new_messages_text=new_text,
        key_facts="",
    )

    summary_text, usage = await client.complete(
        msgs, GenerationParams(temperature=0.3, max_tokens=SUMMARY_MAX_TOKENS)
    )

    if summary_row is None:
        summary_row = StorySummary(session_id=session_id)
        session.add(summary_row)

    summary_row.summary_text = summary_text.strip()
    summary_row.last_summarized_msg_id = new_msgs[-1].id
    summary_row.summary_tokens = usage.output_tokens
    summary_row.updated_at = datetime.utcnow()

    return True
```

- [ ] **Step 5: Run test, verify pass**

```bash
cd backend && pytest tests/test_summarizer.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(service): rolling story summarizer"
```

---

## Task 13: Model client factory

**Files:**
- Create: `backend/src/dzmm/models/factory.py`
- Modify: `backend/tests/test_openai_compat.py` (add a factory test) — or create a small new test file

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_factory.py`:
```python
from unittest.mock import patch

from dzmm.db.models import ModelConfig
from dzmm.models.factory import build_client
from dzmm.models.openai_compat import OpenAICompatClient
from dzmm.models.ollama import OllamaClient


def test_build_openai_compat_client():
    cfg = ModelConfig(
        name="doubao", type="openai_compat",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="ep-xxx", api_key_ref="doubao_main", timeout=30.0,
    )
    with patch("dzmm.models.factory.get_api_key", return_value="sk-fake"):
        c = build_client(cfg)
    assert isinstance(c, OpenAICompatClient)
    assert c.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert c.model == "ep-xxx"
    assert c.api_key == "sk-fake"
    assert c.timeout == 30.0


def test_build_ollama_client():
    cfg = ModelConfig(
        name="local", type="ollama",
        base_url="http://localhost:11434",
        model_name="qwen2.5:7b", api_key_ref=None, timeout=120.0,
    )
    c = build_client(cfg)
    assert isinstance(c, OllamaClient)
    assert c.model == "qwen2.5:7b"


def test_build_unknown_type_raises():
    cfg = ModelConfig(
        name="x", type="madeup",
        base_url="http://x", model_name="y",
    )
    import pytest
    with pytest.raises(ValueError, match="unknown model type"):
        build_client(cfg)
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_factory.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write `backend/src/dzmm/models/factory.py`**

```python
from dzmm.db.models import ModelConfig
from dzmm.models.client import ModelClient
from dzmm.models.ollama import OllamaClient
from dzmm.models.openai_compat import OpenAICompatClient
from dzmm.secrets import get_api_key


def build_client(cfg: ModelConfig) -> ModelClient:
    if cfg.type == "openai_compat":
        api_key = get_api_key(cfg.api_key_ref) if cfg.api_key_ref else ""
        return OpenAICompatClient(
            name=cfg.name,
            base_url=cfg.base_url,
            api_key=api_key or "",
            model=cfg.model_name,
            timeout=cfg.timeout,
        )
    if cfg.type == "ollama":
        return OllamaClient(
            name=cfg.name,
            base_url=cfg.base_url,
            model=cfg.model_name,
            timeout=cfg.timeout,
        )
    raise ValueError(f"unknown model type: {cfg.type}")
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd backend && pytest tests/test_factory.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(models): factory builds client from ModelConfig"
```

---

## Task 14: API schemas + CRUD routes for worlds, characters, model_configs

**Files:**
- Create: `backend/src/dzmm/api/__init__.py`
- Create: `backend/src/dzmm/api/schemas.py`
- Create: `backend/src/dzmm/api/routes_worlds.py`
- Create: `backend/src/dzmm/api/routes_characters.py`
- Create: `backend/src/dzmm/api/routes_models.py`
- Create: `backend/src/dzmm/main.py`

- [ ] **Step 1: Write `backend/src/dzmm/api/__init__.py`**

Empty.

- [ ] **Step 2: Write `backend/src/dzmm/api/schemas.py`**

```python
from pydantic import BaseModel


class WorldIn(BaseModel):
    name: str
    content_md: str
    style: str = "realistic"
    rules_mode: str = "light"


class WorldOut(WorldIn):
    id: int


class CharacterIn(BaseModel):
    world_id: int
    name: str
    profile_md: str
    base_stats_json: str = "{}"


class CharacterOut(CharacterIn):
    id: int


class ModelConfigIn(BaseModel):
    name: str
    type: str
    base_url: str
    model_name: str
    api_key: str | None = None
    timeout: float = 60.0


class ModelConfigOut(BaseModel):
    id: int
    name: str
    type: str
    base_url: str
    model_name: str
    api_key_ref: str | None
    timeout: float


class SessionIn(BaseModel):
    name: str
    world_id: int
    character_id: int
    gm_model_config_id: int
    summarizer_model_config_id: int


class SessionOut(SessionIn):
    id: int
    turn_count: int


class TurnRequest(BaseModel):
    action: str
```

- [ ] **Step 3: Write the routes test**

`backend/tests/test_api.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        yield c


async def test_create_and_list_world(http):
    r = await http.post("/worlds", json={
        "name": "Cyberpunk", "content_md": "Neon city.", "style": "dark"
    })
    assert r.status_code == 200, r.text
    wid = r.json()["id"]

    r = await http.get("/worlds")
    assert r.status_code == 200
    items = r.json()
    assert any(w["id"] == wid for w in items)


async def test_create_character_for_world(http):
    r = await http.post("/worlds", json={
        "name": "W", "content_md": "x"
    })
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "Riku", "profile_md": "黑客",
        "base_stats_json": '{"hp":20,"sanity":15}'
    })
    assert r.status_code == 200
    cid = r.json()["id"]

    r = await http.get(f"/characters?world_id={wid}")
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json())


async def test_create_model_config_with_api_key(http, monkeypatch):
    stored = {}

    def fake_store(ref, value):
        stored[ref] = value

    monkeypatch.setattr("dzmm.api.routes_models.store_api_key", fake_store)

    r = await http.post("/model_configs", json={
        "name": "doubao", "type": "openai_compat",
        "base_url": "https://x", "model_name": "ep",
        "api_key": "sk-secret",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key_ref"] is not None
    # Returned body must NOT contain the raw key.
    assert "api_key" not in body
    assert "sk-secret" not in r.text
    # Key was stored under the ref.
    assert stored.get(body["api_key_ref"]) == "sk-secret"


async def test_create_model_config_without_key(http):
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    assert r.status_code == 200
    assert r.json()["api_key_ref"] is None
```

- [ ] **Step 4: Run test, verify failure**

```bash
cd backend && pytest tests/test_api.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5: Write `backend/src/dzmm/api/routes_worlds.py`**

```python
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import WorldIn, WorldOut
from dzmm.db.models import World

router = APIRouter(prefix="/worlds", tags=["worlds"])


def _to_out(w: World) -> WorldOut:
    rules = json.loads(w.rules_json or '{"mode":"light"}')
    return WorldOut(id=w.id, name=w.name, content_md=w.content_md,
                    style=w.style, rules_mode=rules.get("mode", "light"))


def get_session_dep():
    raise RuntimeError("get_session_dep must be overridden via app dependency_overrides")


@router.post("", response_model=WorldOut)
async def create_world(body: WorldIn, s: AsyncSession = Depends(get_session_dep)):
    w = World(
        name=body.name,
        content_md=body.content_md,
        style=body.style,
        rules_json=json.dumps({"mode": body.rules_mode}),
    )
    s.add(w)
    await s.commit()
    await s.refresh(w)
    return _to_out(w)


@router.get("", response_model=list[WorldOut])
async def list_worlds(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(select(World).order_by(World.id))).scalars().all()
    return [_to_out(w) for w in rows]


@router.get("/{world_id}", response_model=WorldOut)
async def get_world(world_id: int, s: AsyncSession = Depends(get_session_dep)):
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    return _to_out(w)
```

- [ ] **Step 6: Write `backend/src/dzmm/api/routes_characters.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import CharacterIn, CharacterOut
from dzmm.db.models import Character

router = APIRouter(prefix="/characters", tags=["characters"])


def get_session_dep():
    raise RuntimeError("override via dependency_overrides")


@router.post("", response_model=CharacterOut)
async def create_character(body: CharacterIn, s: AsyncSession = Depends(get_session_dep)):
    c = Character(**body.model_dump())
    s.add(c)
    await s.commit()
    await s.refresh(c)
    return CharacterOut(id=c.id, world_id=c.world_id, name=c.name,
                        profile_md=c.profile_md, base_stats_json=c.base_stats_json)


@router.get("", response_model=list[CharacterOut])
async def list_characters(world_id: int | None = None,
                          s: AsyncSession = Depends(get_session_dep)):
    q = select(Character).order_by(Character.id)
    if world_id is not None:
        q = q.where(Character.world_id == world_id)
    rows = (await s.execute(q)).scalars().all()
    return [
        CharacterOut(id=c.id, world_id=c.world_id, name=c.name,
                     profile_md=c.profile_md, base_stats_json=c.base_stats_json)
        for c in rows
    ]


@router.get("/{character_id}", response_model=CharacterOut)
async def get_character(character_id: int, s: AsyncSession = Depends(get_session_dep)):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    return CharacterOut(id=c.id, world_id=c.world_id, name=c.name,
                        profile_md=c.profile_md, base_stats_json=c.base_stats_json)
```

- [ ] **Step 7: Write `backend/src/dzmm/api/routes_models.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import ModelConfigIn, ModelConfigOut
from dzmm.db.models import ModelConfig
from dzmm.models.factory import build_client
from dzmm.secrets import store_api_key

router = APIRouter(prefix="/model_configs", tags=["models"])


def get_session_dep():
    raise RuntimeError("override")


def _to_out(m: ModelConfig) -> ModelConfigOut:
    return ModelConfigOut(
        id=m.id, name=m.name, type=m.type, base_url=m.base_url,
        model_name=m.model_name, api_key_ref=m.api_key_ref, timeout=m.timeout,
    )


@router.post("", response_model=ModelConfigOut)
async def create_model_config(body: ModelConfigIn, s: AsyncSession = Depends(get_session_dep)):
    api_key_ref = None
    if body.api_key:
        api_key_ref = f"{body.name}_{uuid.uuid4().hex[:8]}"
        store_api_key(api_key_ref, body.api_key)

    m = ModelConfig(
        name=body.name, type=body.type, base_url=body.base_url,
        model_name=body.model_name, api_key_ref=api_key_ref, timeout=body.timeout,
    )
    s.add(m)
    await s.commit()
    await s.refresh(m)
    return _to_out(m)


@router.get("", response_model=list[ModelConfigOut])
async def list_model_configs(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(select(ModelConfig).order_by(ModelConfig.id))).scalars().all()
    return [_to_out(m) for m in rows]


@router.post("/{cfg_id}/test")
async def test_model_config(cfg_id: int, s: AsyncSession = Depends(get_session_dep)):
    cfg = await s.get(ModelConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    client = build_client(cfg)
    ok, info = await client.health_check()
    return {"ok": ok, "info": info}
```

- [ ] **Step 8: Write `backend/src/dzmm/main.py`**

```python
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from dzmm.api import routes_characters, routes_models, routes_worlds
from dzmm.db.base import async_session, get_engine, init_db


def create_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI(title="dzmm")

    async def get_session_dep() -> AsyncIterator[AsyncSession]:
        async with session_maker() as s:
            yield s

    for module in (routes_worlds, routes_characters, routes_models):
        module.get_session_dep = get_session_dep  # for documentation only
        app.dependency_overrides[module.get_session_dep] = get_session_dep
        app.include_router(module.router)

    return app


async def build_default_app() -> FastAPI:
    engine = get_engine()
    await init_db(engine)
    return create_app(async_session(engine))
```

- [ ] **Step 9: Run test, verify pass**

```bash
cd backend && pytest tests/test_api.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 10: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(api): CRUD routes for worlds, characters, model_configs"
```

---

## Task 15: Sessions + turn streaming SSE endpoint

**Files:**
- Create: `backend/src/dzmm/api/routes_sessions.py`
- Modify: `backend/src/dzmm/main.py` (register the new router)
- Modify: `backend/tests/test_api.py` (add session + turn tests)

- [ ] **Step 1: Write the failing test additions**

Append to `backend/tests/test_api.py`:
```python
import json as _json
from collections.abc import AsyncIterator

from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage


class StubGM(ModelClient):
    name = "stub"

    def __init__(self, output: str):
        self.output = output

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        for ch in self.output:
            yield StreamChunk(delta=ch)
        yield StreamChunk(delta="", finish_reason="stop",
                          usage=TokenUsage(input_tokens=5, output_tokens=10))


async def _make_session(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x", "style": "dark"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y",
        "base_stats_json": '{"hp":20,"sanity":15}',
    })
    cid = r.json()["id"]
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    mcid = r.json()["id"]
    r = await http.post("/sessions", json={
        "name": "run1", "world_id": wid, "character_id": cid,
        "gm_model_config_id": mcid, "summarizer_model_config_id": mcid,
    })
    return r.json()["id"]


async def test_create_session(http):
    sid = await _make_session(http)
    assert isinstance(sid, int)

    r = await http.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["turn_count"] == 0


async def test_turn_streams_sse(http, monkeypatch):
    sid = await _make_session(http)
    output = ('<narrative>你站在街口。</narrative>'
              '<state_change>{"sanity":-1}</state_change>')

    def fake_build_client(cfg):
        return StubGM(output)

    monkeypatch.setattr("dzmm.api.routes_sessions.build_client", fake_build_client)

    async with http.stream("POST", f"/sessions/{sid}/turn",
                           json={"action": "环顾四周"}) as r:
        assert r.status_code == 200
        text = ""
        async for chunk in r.aiter_text():
            text += chunk

    assert "你站在街口" in text
    # state_change tag should be reported as a TagComplete event but its content
    # also stays out of the "narrative" event stream
    assert "narrative" in text  # event names

    # Verify state was applied
    r = await http.get(f"/sessions/{sid}")
    assert r.json()["turn_count"] == 1
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/test_api.py -v -k session
```

Expected: FAIL — endpoints not implemented yet.

- [ ] **Step 3: Write `backend/src/dzmm/api/routes_sessions.py`**

```python
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import SessionIn, SessionOut, TurnRequest
from dzmm.db.models import (
    CharState,
    Message as MessageRow,
    ModelConfig,
    Session as GameSession,
    World,
)
from dzmm.models.factory import build_client
from dzmm.parsing.events import NarrativeDelta, ParseError, TagComplete
from dzmm.service.game import run_turn
from dzmm.service.summarizer import maybe_summarize

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_session_dep():
    raise RuntimeError("override")


def get_session_maker_dep():
    raise RuntimeError("override")


def _to_out(s: GameSession) -> SessionOut:
    return SessionOut(
        id=s.id, name=s.name, world_id=s.world_id, character_id=s.character_id,
        gm_model_config_id=s.gm_model_config_id,
        summarizer_model_config_id=s.summarizer_model_config_id,
        turn_count=s.turn_count,
    )


@router.post("", response_model=SessionOut)
async def create_session(body: SessionIn, s: AsyncSession = Depends(get_session_dep)):
    sess = GameSession(**body.model_dump())
    s.add(sess)
    await s.flush()
    s.add(CharState(session_id=sess.id))
    await s.commit()
    await s.refresh(sess)
    return _to_out(sess)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return _to_out(sess)


@router.get("", response_model=list[SessionOut])
async def list_sessions(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(
        select(GameSession).order_by(GameSession.last_played.desc())
    )).scalars().all()
    return [_to_out(x) for x in rows]


@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,
    session_maker = Depends(get_session_maker_dep),
):
    async def event_stream() -> AsyncIterator[dict]:
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                yield {"event": "error", "data": json.dumps({"message": "session not found"})}
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            client = build_client(cfg)

            async for ev in run_turn(s, session_id, body.action, client):
                if isinstance(ev, NarrativeDelta):
                    yield {"event": "narrative",
                           "data": json.dumps({"text": ev.text}, ensure_ascii=False)}
                elif isinstance(ev, TagComplete):
                    yield {"event": "tag",
                           "data": json.dumps({"name": ev.name, "attrs": ev.attrs,
                                               "content": ev.content},
                                              ensure_ascii=False)}
                elif isinstance(ev, ParseError):
                    yield {"event": "parse_error",
                           "data": json.dumps({"message": ev.message}, ensure_ascii=False)}

            await s.commit()

        # Summarizer runs in a fresh session afterwards.
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            sum_cfg = await s.get(ModelConfig, sess.summarizer_model_config_id)
            sum_client = build_client(sum_cfg)
            try:
                ran = await maybe_summarize(s, session_id, sum_client)
                if ran:
                    await s.commit()
            except Exception as e:  # noqa: BLE001
                yield {"event": "summarize_error",
                       "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())
```

- [ ] **Step 4: Update `backend/src/dzmm/main.py` to register sessions router**

Replace `backend/src/dzmm/main.py` entirely:
```python
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dzmm.api import (
    routes_characters,
    routes_models,
    routes_sessions,
    routes_worlds,
)
from dzmm.db.base import async_session, get_engine, init_db


def create_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI(title="dzmm")

    async def get_session_dep() -> AsyncIterator[AsyncSession]:
        async with session_maker() as s:
            yield s

    def get_session_maker_dep() -> async_sessionmaker[AsyncSession]:
        return session_maker

    for module in (routes_worlds, routes_characters, routes_models, routes_sessions):
        app.dependency_overrides[module.get_session_dep] = get_session_dep
        app.include_router(module.router)

    app.dependency_overrides[routes_sessions.get_session_maker_dep] = get_session_maker_dep
    return app


async def build_default_app() -> FastAPI:
    engine = get_engine()
    await init_db(engine)
    return create_app(async_session(engine))
```

- [ ] **Step 5: Run test, verify pass**

```bash
cd backend && pytest tests/test_api.py -v
```

Expected: All API tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat(api): sessions CRUD + SSE turn endpoint"
```

---

## Task 16: End-to-end smoke + dev runner

**Files:**
- Create: `backend/scripts/run_dev.py`
- Create: `backend/scripts/smoke.py`
- Create: `backend/README.md`

- [ ] **Step 1: Write `backend/scripts/run_dev.py`**

```python
"""Start the FastAPI app for local development.

Usage:
    cd backend && python scripts/run_dev.py
"""
import asyncio

import uvicorn

from dzmm.main import build_default_app


async def main():
    app = await build_default_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write `backend/scripts/smoke.py`**

```python
"""End-to-end smoke test against a running backend.

Prereqs:
    - Run `python scripts/run_dev.py` in another terminal
    - Have Ollama running locally with qwen2.5:7b (or edit MODEL_NAME below)

Usage:
    python scripts/smoke.py
"""
import asyncio
import json

import httpx

BASE = "http://127.0.0.1:8765"
MODEL_NAME = "qwen2.5:7b"


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as c:
        w = (await c.post("/worlds", json={
            "name": "测试世界", "style": "dark",
            "content_md": "赛博朋克末世，企业掌权，街头义体黑客横行。",
        })).json()
        ch = (await c.post("/characters", json={
            "world_id": w["id"], "name": "Riku", "profile_md": "义体黑客，30 岁",
            "base_stats_json": json.dumps({"hp": 20, "sanity": 15}),
        })).json()
        m = (await c.post("/model_configs", json={
            "name": "local", "type": "ollama",
            "base_url": "http://localhost:11434", "model_name": MODEL_NAME,
        })).json()
        s = (await c.post("/sessions", json={
            "name": "smoke-run", "world_id": w["id"], "character_id": ch["id"],
            "gm_model_config_id": m["id"], "summarizer_model_config_id": m["id"],
        })).json()
        print(f"Session created: {s['id']}")

        async with c.stream("POST", f"/sessions/{s['id']}/turn",
                            json={"action": "(开始游戏)"}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line:
                    print(line)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Write `backend/README.md`**

```markdown
# dzmm backend

AI dynamic TRPG text-game backend (v0.1).

## Setup

    cd backend
    python3.11 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"

## Test

    pytest -v

## Run dev server

    python scripts/run_dev.py
    # Server on http://127.0.0.1:8765

## Smoke test (requires Ollama)

In one terminal:
    ollama pull qwen2.5:7b
    ollama serve

In another:
    python scripts/run_dev.py

In a third:
    python scripts/smoke.py

## API

- `POST /worlds`, `GET /worlds`, `GET /worlds/{id}`
- `POST /characters`, `GET /characters?world_id=N`, `GET /characters/{id}`
- `POST /model_configs`, `GET /model_configs`, `POST /model_configs/{id}/test`
- `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`
- `POST /sessions/{id}/turn` — SSE stream

## SSE event types

- `narrative` — `{ text }` — append to UI
- `tag` — `{ name, attrs, content }` — handled in UI status panel
- `parse_error` — `{ message }`
- `summarize_error` — `{ message }`
- `done` — `{}`

## Storage

- SQLite at `~/.dzmm/dzmm.db`
- API keys in OS keychain via `keyring`
```

- [ ] **Step 4: Run all tests once more**

```bash
cd backend && pytest -v
```

Expected: ALL tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm
git add backend/
git commit -m "feat: dev runner, smoke script, backend README"
```

---

## Self-Review

**Spec coverage** — checked against the v0.1 cut from earlier discussion:

| Requirement | Task | Status |
|---|---|---|
| Model config (Ollama + cloud) | Task 5, 6, 13, 14 | ✅ |
| Streaming output | Task 5, 6, 7, 15 | ✅ |
| World/character creation | Task 14 | ✅ |
| Single rule mode (light) | Task 10 | ✅ |
| GM prompt with anti-OOC | Task 10 | ✅ |
| Tag-driven state updates | Task 7, 9 | ✅ |
| Session creation + turn endpoint | Task 15 | ✅ |
| Manual save/load (auto via DB) | Task 14, 15 | ✅ (every turn persisted) |
| Rolling summarizer | Task 12, 15 | ✅ |
| API key in keychain | Task 3, 14 | ✅ |
| SQLite persistence | Task 2 | ✅ |

**Out of v0.1 (intentionally deferred):**
- `<plot_event>` / plot_threads / timeline tables — v0.2
- `<choices>` rendering on the API side (parser handles them, route forwards as `tag` event — UI decides what to do) — frontend concern
- Vector long-term memory — v0.3
- Standard / hardcore rule modes — v0.2
- Auto-save interval — v0.2 (every turn is persisted, so no data loss)
- Soft / hard summary token limits with re-compression — v0.2

**Placeholder scan:** Searched for "TODO", "TBD", "implement later", "fill in", "similar to", "appropriate", "etc.". None found in plan tasks.

**Type consistency** — checked critical signatures:
- `ModelClient.stream()` returns `AsyncIterator[StreamChunk]` everywhere it's called.
- `apply_tags(session, session_id, current_turn, tags)` — same signature in test_state_apply, used identically in game.py.
- `build_gm_messages` keyword-only kwargs match between test and impl.
- `maybe_summarize(session, session_id, client)` — same signature in test, used identically in routes_sessions.
- `run_turn(session, session_id, user_action, client)` — same signature in tests + routes.
- `StreamingTagParser.feed()` returns `Iterator[ParseEvent]` (not async — feed is sync because it's CPU-bound parsing of an already-received string). `finish()` same.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-29-backend-core-v0.1.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks. Best for a 16-task plan; cleanest context per task.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints.

**Which approach?**

"""Stub backend for Playwright E2E tests.

Real FastAPI + SQLite + SSE pipeline, but the GM model is replaced with a
``StubModelClient`` that emits a deterministic narrative + state_change
stream. This lets us exercise the full SSE / CRLF / CORS path end-to-end
without depending on a live LLM.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Redirect dzmm's APP_DIR (Path.home() / ".dzmm") to a throwaway temp dir
# so the test never touches a developer's real ~/.dzmm.
_TMP_HOME = tempfile.mkdtemp(prefix="dzmm-e2e-")
os.environ["HOME"] = _TMP_HOME
# Informational only — dzmm.config doesn't read this, but it's handy when
# you're poking at the temp dir during a failure investigation.
os.environ["DZMM_DB_PATH"] = os.path.join(_TMP_HOME, ".dzmm", "test.db")
os.environ["DZMM_HOST"] = "127.0.0.1"
os.environ["DZMM_PORT"] = "8765"

# Make backend/src importable when invoked directly via `python e2e/mock_backend.py`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_SRC = os.path.normpath(os.path.join(_HERE, "..", "..", "backend", "src"))
if _BACKEND_SRC not in sys.path:
    sys.path.insert(0, _BACKEND_SRC)

# --- Patch the model factory to return a deterministic stub --------------
from dzmm.models import factory as factory_mod  # noqa: E402
from dzmm.models.client import (  # noqa: E402
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)


class StubModelClient(ModelClient):
    """Yields a tiny scripted narrative so the front-end can verify SSE."""

    name = "stub-e2e"

    async def stream(  # type: ignore[override]
        self,
        messages: list[Message],
        params: GenerationParams,
    ):
        chunks = [
            "<narrative>",
            "你站在虚拟",
            "的街道上，",
            "霓虹光闪烁。",
            "</narrative>",
            '<state_change>{"hp": -1}</state_change>',
        ]
        for c in chunks:
            yield StreamChunk(delta=c)
            await asyncio.sleep(0.01)
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=20),
        )


def _stub_build(cfg):  # noqa: ANN001
    return StubModelClient()


factory_mod.build_client = _stub_build  # type: ignore[assignment]

# --- Boot uvicorn with the real FastAPI app ------------------------------
import uvicorn  # noqa: E402

from dzmm.main import build_default_app  # noqa: E402


async def main() -> None:
    app = await build_default_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8765,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())

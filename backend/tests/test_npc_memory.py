"""Tests for npc_memory module — focus on graceful degradation when
Ollama / ChromaDB infrastructure is missing.  The happy path requires a
real embedding service which we don't run in CI.
"""
import asyncio
from pathlib import Path

import pytest

from dzmm.service.npc_memory import (
    init_npc_memory,
    record_memory,
    retrieve_memories,
)


def test_record_memory_silent_when_no_url(tmp_path: Path):
    """Empty ollama_url → silent no-op (no exception)."""
    init_npc_memory(tmp_path)
    asyncio.run(record_memory(1, 5, "test memory line", ollama_url=""))
    # No assertion — just verify no exception raised


def test_record_memory_silent_when_short_text(tmp_path: Path):
    """Text under 20 chars is silently ignored (too short to be useful)."""
    init_npc_memory(tmp_path)
    asyncio.run(record_memory(1, 5, "hi", ollama_url="http://localhost:11434"))
    # No assertion — no exception


def test_retrieve_memories_silent_when_no_url(tmp_path: Path):
    init_npc_memory(tmp_path)
    out = asyncio.run(retrieve_memories(1, "some query", ollama_url=""))
    assert out == []


def test_retrieve_memories_silent_when_empty_query(tmp_path: Path):
    init_npc_memory(tmp_path)
    out = asyncio.run(retrieve_memories(1, "", ollama_url="http://localhost:11434"))
    assert out == []


def test_retrieve_memories_silent_when_whitespace_query(tmp_path: Path):
    init_npc_memory(tmp_path)
    out = asyncio.run(retrieve_memories(1, "   ", ollama_url="http://localhost:11434"))
    assert out == []


def test_retrieve_memories_silent_when_uninitialized():
    """No init_npc_memory call → silent no-op (returns [])."""
    from dzmm.service import npc_memory as nm
    saved = nm._APP_DIR
    try:
        nm._APP_DIR = None
        out = asyncio.run(
            retrieve_memories(1, "some query", ollama_url="http://localhost:11434")
        )
        assert out == []
    finally:
        nm._APP_DIR = saved


def test_record_memory_silent_when_uninitialized():
    """No init_npc_memory call → silent no-op (no exception)."""
    from dzmm.service import npc_memory as nm
    saved = nm._APP_DIR
    try:
        nm._APP_DIR = None
        asyncio.run(
            record_memory(1, 1, "some text that is long enough", ollama_url="http://localhost:11434")
        )
    finally:
        nm._APP_DIR = saved


def test_init_creates_directory(tmp_path: Path):
    """init_npc_memory should create the chroma_npc subdirectory."""
    init_npc_memory(tmp_path)
    assert (tmp_path / "chroma_npc").is_dir()


def test_delete_npc_memory_silent_when_uninitialized():
    """No init_npc_memory call → silent no-op."""
    from dzmm.service import npc_memory as nm
    saved = nm._APP_DIR
    try:
        nm._APP_DIR = None
        nm.delete_npc_memory(42)  # must not raise
    finally:
        nm._APP_DIR = saved


def test_delete_npc_memory_silent_when_collection_missing(tmp_path: Path):
    """delete_npc_memory should swallow ChromaDB error when collection
    doesn't exist (e.g. NPC never had any memory recorded)."""
    init_npc_memory(tmp_path)
    from dzmm.service.npc_memory import delete_npc_memory
    delete_npc_memory(99999)  # never created — must not raise

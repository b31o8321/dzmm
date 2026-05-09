"""Per-NPC long-term memory backed by ChromaDB.

Each NPC gets its own collection (``npc_mem_{npc_id}``).  After every
``<say speaker="X">…</say>`` event the speaker's NPC row gets a one-line
memory written to its collection.  Before the GM takes a turn,
retrieve top-k memories for each on-stage NPC matching the current user
action; inject into key_facts so NPC behaviour stays consistent with
what they previously said/did.

Storage: ``~/.dzmm/chroma_npc/``

**Design choice – no LLM summariser in v1.**
The spec mentioned an LLM-driven summariser before embedding.  For v1 we
store the raw ``<say>`` text (capped at 300 chars) directly.  This avoids
extra LLM round-trips and complex wiring; LLM summarisation can be added
as a future enhancement when text exceeds ~200 chars.

**Failure mode.**
Every public function silently no-ops on any infrastructure issue (no
Ollama, no embedding service, ChromaDB error).  Memory is a soft
enhancement; loss of a memory line never blocks the turn.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_TOP_K = 3
_APP_DIR: Path | None = None


def init_npc_memory(app_dir: Path) -> None:
    """Call once at startup.  Creates the chroma_npc storage directory."""
    global _APP_DIR
    _APP_DIR = app_dir
    (app_dir / "chroma_npc").mkdir(parents=True, exist_ok=True)


def _coll_name(npc_id: int) -> str:
    return f"npc_mem_{npc_id}"


def _client():
    import chromadb  # lazy — ChromaDB is optional in test environments
    if _APP_DIR is None:
        raise RuntimeError("init_npc_memory() not called")
    return chromadb.PersistentClient(path=str(_APP_DIR / "chroma_npc"))


def _embed_sync(base_url: str, text: str) -> list[float]:
    """Synchronous embedding call — runs inside a thread pool."""
    from dzmm.service.world_rag import OllamaEmbedder
    embedder = OllamaEmbedder(base_url=base_url)
    return embedder.embed_query(text)


async def record_memory(
    npc_id: int,
    turn: int,
    text: str,
    ollama_url: str,
) -> None:
    """Record a single memory line for *npc_id* at turn *N*.

    *text* is stored as-is (capped at 300 chars).  Fire-and-forget: callers
    should wrap in ``asyncio.create_task`` so they don't await this.
    """
    if not text.strip() or _APP_DIR is None or not ollama_url:
        return
    try:
        doc = text[:300]
        emb = await asyncio.to_thread(_embed_sync, ollama_url, doc)
        coll = await asyncio.to_thread(_client().get_or_create_collection, _coll_name(npc_id))
        count = await asyncio.to_thread(coll.count)
        await asyncio.to_thread(
            coll.add,
            ids=[f"t{turn}_{count}"],
            documents=[doc],
            embeddings=[emb],
            metadatas=[{"turn": turn}],
        )
    except Exception as e:  # noqa: BLE001
        log.debug("npc_memory: record failed for npc %d: %s", npc_id, e)


def delete_npc_memory(npc_id: int) -> None:
    """Drop the ChromaDB collection for *npc_id*. Used by cascade-delete paths
    (session delete / NPC delete / NER auto-cleanup) so an NPC's vector
    memories don't outlive the NPC row itself.

    Silently no-ops on any failure (uninitialised _APP_DIR, missing
    collection, ChromaDB error) — memory cleanup is best-effort and must
    never block the delete.
    """
    if _APP_DIR is None:
        return
    try:
        client = _client()
        client.delete_collection(_coll_name(npc_id))
    except Exception as e:  # noqa: BLE001
        log.debug("npc_memory: delete failed for npc %d: %s", npc_id, e)


async def retrieve_memories(
    npc_id: int,
    query: str,
    ollama_url: str,
    k: int = _TOP_K,
) -> list[str]:
    """Return top-k memory lines for *npc_id* matching *query*.

    Returns an empty list on any failure or when the collection is empty.
    """
    if not query.strip() or _APP_DIR is None or not ollama_url:
        return []
    try:
        q_emb = await asyncio.to_thread(_embed_sync, ollama_url, query[:200])

        def _query_chroma() -> list[str]:
            coll = _client().get_or_create_collection(_coll_name(npc_id))
            if coll.count() == 0:
                return []
            result = coll.query(
                query_embeddings=[q_emb],
                n_results=min(k, coll.count()),
            )
            docs = result.get("documents") or []
            return docs[0] if docs else []

        return await asyncio.to_thread(_query_chroma)
    except Exception as e:  # noqa: BLE001
        log.debug("npc_memory: retrieve failed for npc %d: %s", npc_id, e)
        return []

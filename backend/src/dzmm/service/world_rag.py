# ============================================================
# Phase A — LangChain RAG：世界书向量检索
# ============================================================
# 【用途】
#   把世界书 Markdown 分块 → 向量化（embedding）→ 存入 ChromaDB。
#   每回合用玩家行动作为 query 检索最相关的 top-k 块，
#   只把这些块注入 Prompt，而不是把整本世界书塞进去。
#
# 【LangChain 知识点】
#   Embeddings: langchain_core 定义的抽象接口（ABC），任何 embedding 模型都实现它。
#   RecursiveCharacterTextSplitter: 递归按段落/句子/字符拆分，保证每块不超过 chunk_size。
#   ChromaDB: 本地向量数据库，存储在 ~/.dzmm/chroma/{world_id}/，不需要外部服务。
# ============================================================

import asyncio
import logging
from pathlib import Path

import httpx
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from dzmm.config import APP_DIR

log = logging.getLogger(__name__)

_EMBED_MODEL = "nomic-embed-text"
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
_TOP_K = 4
_SHORT_WORLD_THRESHOLD = 800  # 字符数低于此值时跳过 RAG，直接注入全文


# ── LangChain Embeddings 接口实现 ────────────────────────
class OllamaEmbedder(Embeddings):
    """通过 Ollama /api/embeddings 接口实现 LangChain Embeddings ABC。

    【学习点：LangChain Embeddings 接口】
      embed_documents(texts) → list[list[float]]: 批量向量化文档
      embed_query(text) → list[float]: 向量化单条查询
      两者分开是因为有些模型对查询和文档用不同的前缀（如 E5 系列）。
    """

    def __init__(self, base_url: str, model: str = _EMBED_MODEL) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        resp = httpx.post(
            f"{self._base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


# ── 路径工具 ────────────────────────────────────────────
def _persist_dir(world_id: int, app_dir: Path | None = None) -> str:
    base = app_dir if app_dir is not None else APP_DIR
    return str(base / "chroma" / str(world_id))


def is_indexed(world_id: int, app_dir: Path | None = None) -> bool:
    """检查此 world_id 是否已有向量索引（目录是否存在）。"""
    return Path(_persist_dir(world_id, app_dir)).exists()


# ── 索引 ─────────────────────────────────────────────────
def index_world(
    world_id: int,
    content_md: str,
    ollama_url: str,
    model: str = _EMBED_MODEL,
    _embedder: Embeddings | None = None,
    app_dir: Path | None = None,
) -> None:
    """把 content_md 分块、向量化并存入 ChromaDB。

    【学习点：RecursiveCharacterTextSplitter】
      chunk_size=500: 每块最多 500 字符
      chunk_overlap=50: 相邻块重叠 50 字符，防止语义在块边界断裂
    """
    import chromadb  # 延迟导入

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(content_md)
    if not chunks:
        log.warning("world_rag: world %d has no splittable content, skipping", world_id)
        return

    embedder = _embedder or OllamaEmbedder(ollama_url, model)
    persist_path = _persist_dir(world_id, app_dir)
    client = chromadb.PersistentClient(path=persist_path)
    col_name = f"world_{world_id}"

    # 幂等：先删旧 collection 再建新的，保证重新索引覆盖旧数据
    try:
        client.delete_collection(col_name)
    except Exception:
        pass
    col = client.create_collection(col_name)

    embeddings = embedder.embed_documents(chunks)
    col.add(
        ids=[f"{world_id}_{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embeddings,
    )
    log.info("world_rag: indexed world %d → %d chunks", world_id, len(chunks))


async def index_world_async(
    world_id: int,
    content_md: str,
    ollama_url: str,
    model: str = _EMBED_MODEL,
) -> None:
    """index_world 的异步包装 — 在线程池中运行（ChromaDB 是同步的）。"""
    await asyncio.to_thread(index_world, world_id, content_md, ollama_url, model)


# ── 检索 ─────────────────────────────────────────────────
def retrieve_world_context(
    world_id: int,
    query: str,
    ollama_url: str,
    model: str = _EMBED_MODEL,
    k: int = _TOP_K,
    _embedder: Embeddings | None = None,
    app_dir: Path | None = None,
) -> str:
    """从 ChromaDB 检索与 query 最相关的 top-k 世界书片段，拼接后返回。

    【学习点：向量相似度搜索】
      query → 向量化 → 与库中所有向量计算余弦相似度 → 取 top-k 最近的文档
      这就是 RAG（Retrieval-Augmented Generation）的核心："先检索再生成"。
    """
    import chromadb

    _app_dir = app_dir if app_dir is not None else APP_DIR
    embedder = _embedder or OllamaEmbedder(ollama_url, model)
    client = chromadb.PersistentClient(path=_persist_dir(world_id, _app_dir))
    col = client.get_collection(f"world_{world_id}")

    count = col.count()
    if count == 0:
        return ""

    query_embedding = embedder.embed_query(query)
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=min(k, count),
    )
    docs: list[str] = results["documents"][0]
    return "\n\n---\n\n".join(docs)


def get_world_md(
    world_id: int,
    content_md: str,
    query: str,
    ollama_url: str | None,
    model: str = _EMBED_MODEL,
    k: int = _TOP_K,
    _embedder: Embeddings | None = None,
    app_dir: Path | None = None,
) -> str:
    """决策函数：返回该回合应注入 Prompt 的世界书内容。

    规则（按优先级）：
    1. ollama_url 为 None → 返回全文（无法 embed）
    2. content_md 长度 < 800 → 返回全文（不值得 RAG）
    3. 未建立索引 → 返回全文（fallback，不报错）
    4. 已建立索引 → 返回 top-k 检索结果；异常时 fallback 全文

    【设计原则：优雅降级】
      RAG 不可用时静默 fallback 到全文，保证游戏不中断。
    """
    _app_dir = app_dir if app_dir is not None else APP_DIR
    text = content_md or ""
    if not ollama_url or len(text) < _SHORT_WORLD_THRESHOLD:
        return text
    if not is_indexed(world_id, _app_dir):
        return text
    try:
        return retrieve_world_context(
            world_id, query, ollama_url, model, k, _embedder, _app_dir
        )
    except Exception as exc:
        log.warning(
            "world_rag: retrieval failed for world %d, falling back to full text: %s",
            world_id, exc,
        )
        return text

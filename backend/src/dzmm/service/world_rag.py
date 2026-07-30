# ============================================================
# world_rag.py — 世界书 RAG（检索增强生成）
# ============================================================
# 【什么是 RAG？】
#   RAG = Retrieval-Augmented Generation（检索增强生成）
#   传统做法：把整本世界书（可能几千字）全塞进每次的 Prompt。
#   问题：浪费 token，而且模型注意力会被无关内容分散。
#
#   RAG 做法：
#   1. 提前把世界书切成小块（chunk），每块向量化（转成一串数字）
#   2. 存入向量数据库 ChromaDB
#   3. 每回合用玩家行动作为"查询"，找出最相关的 top-k 块
#   4. 只把这几块注入 Prompt
#
# 【什么是向量/向量搜索？】
#   向量（embedding）是把一段文字用数学方式表示成一串浮点数（如 768 维）。
#   语义相似的文字，向量也相近（余弦距离小）。
#   向量搜索 = 给定查询向量，从数据库里找出最近邻的文档向量。
#   直觉：把每段文字想象成空间里的一个点，搜索就是找"离查询点最近的几个点"。
#
# 【LangChain 知识点】
#   Embeddings: LangChain 定义的接口，任何 embedding 模型都实现它
#   RecursiveCharacterTextSplitter: 递归按段落→句子→字符拆分，保证每块不超过 chunk_size
#   ChromaDB: 本地向量数据库，存储在 ~/.dzmm/chroma/{world_id}/，无需外部服务
# ============================================================

import asyncio
import logging
from pathlib import Path

import httpx                                          # HTTP 客户端，用于调用 Ollama API
from langchain_core.embeddings import Embeddings      # LangChain embedding 接口（抽象基类）
from langchain_text_splitters import RecursiveCharacterTextSplitter  # 文本分块工具

from dzmm.config import APP_DIR  # 应用数据目录（如 ~/.dzmm/）

log = logging.getLogger(__name__)

_EMBED_MODEL = "nomic-embed-text"  # Ollama embedding 模型名（本地运行，免费）
_CHUNK_SIZE = 500       # 每块最多 500 字符
_CHUNK_OVERLAP = 50     # 相邻块重叠 50 字符，防止语义在块边界断裂
_TOP_K = 4              # 每次检索返回最相关的 4 块
_SHORT_WORLD_THRESHOLD = 800  # 世界书短于 800 字符时，直接注入全文，不走 RAG


# ── LangChain Embeddings 接口实现 ────────────────────────────────────────────
# 【为什么要实现这个类？】
#   LangChain 定义了 Embeddings 抽象接口，ChromaDB 集成需要它。
#   Ollama 不在 LangChain 内置支持里（或版本不匹配），所以手动实现。
class OllamaEmbedder(Embeddings):
    # 通过 Ollama /api/embeddings 接口实现 LangChain Embeddings ABC
    #
    # 【LangChain Embeddings 接口的两个核心方法】
    #   embed_documents(texts): 批量向量化文档（存入 ChromaDB 时用）
    #   embed_query(text): 向量化单条查询（搜索时用）
    #   分开是因为某些模型对查询和文档用不同的前缀（如微软 E5 系列模型）

    def __init__(self, base_url: str, model: str = _EMBED_MODEL) -> None:
        self._base_url = base_url.rstrip("/")  # 去掉末尾斜杠，避免拼接出双斜杠
        self._model = model

    # 批量向量化：逐条调用 _embed，返回向量列表
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    # 单条查询向量化
    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        # 调用本地 Ollama API，发送 POST 请求，返回 embedding 浮点数组
        resp = httpx.post(
            f"{self._base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
            timeout=30.0,  # 30 秒超时，本地模型一般很快
        )
        resp.raise_for_status()  # HTTP 非 2xx 时抛异常
        return resp.json()["embedding"]  # Ollama 返回格式：{"embedding": [...]}


# ── 路径工具函数 ──────────────────────────────────────────────────────────────
def _persist_dir(world_id: int, app_dir: Path | None = None) -> str:
    # 返回 ChromaDB 向量数据库的存储目录路径（字符串形式）
    # 每个世界书独立一个子目录：~/.dzmm/chroma/{world_id}/
    base = app_dir if app_dir is not None else APP_DIR
    return str(base / "chroma" / str(world_id))


def is_indexed(world_id: int, app_dir: Path | None = None) -> bool:
    # 检查此 world_id 是否已建立向量索引（通过目录是否存在判断）
    # 用于决定是走 RAG 还是直接返回全文
    return Path(_persist_dir(world_id, app_dir)).exists()


# ── 索引（建库）────────────────────────────────────────────────────────────────
def index_world(
    world_id: int,
    content_md: str,      # 世界书的 Markdown 全文
    ollama_url: str,      # Ollama 服务地址（如 http://localhost:11434）
    model: str = _EMBED_MODEL,
    _embedder: Embeddings | None = None,  # 测试时可注入 mock embedder
    app_dir: Path | None = None,
) -> None:
    # 把 content_md 分块、向量化，存入 ChromaDB
    # 此函数是同步的（ChromaDB Python SDK 不支持 async），调用方用 asyncio.to_thread 包装
    #
    # 【RecursiveCharacterTextSplitter 工作原理】
    #   优先在段落边界（\n\n）分块，其次是单换行，最后才在字符中间截断
    #   chunk_overlap=50 让相邻块有 50 字符重叠，防止关键信息正好在块边界被切断
    import chromadb  # 延迟导入：没安装 chromadb 时不影响启动

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(content_md)
    if not chunks:
        log.warning("world_rag: world %d has no splittable content, skipping", world_id)
        return

    # 使用传入的 embedder 或创建默认的 OllamaEmbedder
    embedder = _embedder or OllamaEmbedder(ollama_url, model)
    persist_path = _persist_dir(world_id, app_dir)
    # PersistentClient：向量数据库存储到磁盘（不是内存），重启后数据还在
    with chromadb.PersistentClient(path=persist_path) as client:
        col_name = f"world_{world_id}"  # collection（集合）名称，相当于数据库里的表名

        # 幂等设计：先删除旧 collection 再建新的
        # 这样重新索引时不会出现"旧数据 + 新数据"混在一起的情况
        try:
            client.delete_collection(col_name)
        except Exception:
            pass  # 不存在时删除会报错，忽略即可
        col = client.create_collection(col_name)

        # 批量向量化所有文本块（可能有几十个块，每个调用一次 Ollama API）
        embeddings = embedder.embed_documents(chunks)
        # 把文本 + 向量一起存入 ChromaDB
        # ids: 每条记录的唯一标识，格式 "world_id_序号"
        col.add(
            ids=[f"{world_id}_{i}" for i in range(len(chunks))],
            documents=chunks,      # 原始文本（检索时返回给调用方）
            embeddings=embeddings, # 对应的向量（用于计算相似度）
        )
    log.info("world_rag: indexed world %d → %d chunks", world_id, len(chunks))


async def index_world_async(
    world_id: int,
    content_md: str,
    ollama_url: str,
    model: str = _EMBED_MODEL,
) -> None:
    # index_world 的异步包装版本
    # asyncio.to_thread 把同步函数放到线程池执行，不阻塞事件循环
    # （ChromaDB 是同步库，直接在 async 代码里调用会卡住整个服务器）
    await asyncio.to_thread(index_world, world_id, content_md, ollama_url, model)


def delete_world_index(world_id: int, app_dir: Path | None = None) -> None:
    # 删除这个世界书的 ChromaDB 磁盘目录
    # 在世界书被删除时调用（级联删除），防止向量数据占用磁盘但对应记录已不存在
    # 任何失败都静默处理 —— 索引清理是"尽力而为"，不能因此阻断删除操作
    #
    # 注意：不在这里创建 PersistentClient，否则 Windows 上 sqlite 文件会被锁住
    # 导致后续 rmtree 失败（PermissionError）。直接删目录即可，不需要先删 collection。
    import shutil
    import stat

    persist_path = Path(_persist_dir(world_id, app_dir))
    if not persist_path.exists():
        return  # 目录不存在，无需操作

    def _remove_readonly(func, path, _exc):
        # Windows 上部分文件可能是只读属性，先改权限再重试
        Path(path).chmod(stat.S_IWRITE)
        func(path)

    try:
        shutil.rmtree(persist_path, onerror=_remove_readonly)  # 递归删除整个目录
    except Exception as e:  # noqa: BLE001
        log.debug("world_rag: rmtree failed for world %d: %s", world_id, e)


# ── 检索（查询）────────────────────────────────────────────────────────────────
def retrieve_world_context(
    world_id: int,
    query: str,       # 用玩家这回合的行动文本作为查询
    ollama_url: str,
    model: str = _EMBED_MODEL,
    k: int = _TOP_K,
    _embedder: Embeddings | None = None,
    app_dir: Path | None = None,
) -> str:
    # 从 ChromaDB 检索与 query 最相关的 top-k 世界书片段，拼接后返回
    #
    # 【向量相似度搜索的原理】
    #   1. 把 query 文本向量化（转成一串浮点数）
    #   2. 在数据库里计算 query 向量与所有存储向量的余弦相似度
    #   3. 返回相似度最高的 k 个文档
    #   直觉：语义上"更像"的文本，在向量空间里距离更近
    import chromadb

    _app_dir = app_dir if app_dir is not None else APP_DIR
    embedder = _embedder or OllamaEmbedder(ollama_url, model)
    with chromadb.PersistentClient(path=_persist_dir(world_id, _app_dir)) as client:
        col = client.get_collection(f"world_{world_id}")

        count = col.count()
        if count == 0:
            return ""  # 空数据库，直接返回空字符串

        # 向量化查询文本
        query_embedding = embedder.embed_query(query)
        # n_results 不能超过数据库里实际有的条数（ChromaDB 限制）
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=min(k, count),
        )
    # results["documents"] 是二维列表（支持批量查询），取第一个查询的结果
    docs: list[str] = results["documents"][0]
    # 用分割线拼接各块，让 GM 看到清晰的段落分隔
    return "\n\n---\n\n".join(docs)


def get_world_md(
    world_id: int,
    content_md: str,       # 世界书原始全文
    query: str,            # 本回合的搜索查询
    ollama_url: str | None,  # 若为 None 表示没有配置 Ollama
    model: str = _EMBED_MODEL,
    k: int = _TOP_K,
    _embedder: Embeddings | None = None,
    app_dir: Path | None = None,
) -> str:
    # 决策函数：返回该回合应注入 Prompt 的世界书内容
    #
    # 【优先级规则（优雅降级设计）】
    # 1. 没配置 ollama_url → 无法 embed → 返回全文
    # 2. 世界书很短（< 800 字符）→ RAG 没有意义 → 返回全文
    # 3. 还没建立索引 → Fallback 全文（不报错，保证游戏不中断）
    # 4. 已建立索引 → 返回 top-k 检索结果；检索出错也 fallback 全文
    #
    # 【设计原则：优雅降级】
    #   RAG 是优化功能，不是核心功能。任何环节出错都不应影响游戏运行，
    #   所以每个失败路径都有一个安全的 fallback。
    _app_dir = app_dir if app_dir is not None else APP_DIR
    text = content_md or ""
    # 没有 Ollama 或世界书太短，直接返回全文
    if not ollama_url or len(text) < _SHORT_WORLD_THRESHOLD:
        return text
    # 还没建立向量索引，返回全文（首次启动时常见，索引由后台任务异步建立）
    if not is_indexed(world_id, _app_dir):
        return text
    try:
        return retrieve_world_context(
            world_id, query, ollama_url, model, k, _embedder, _app_dir
        )
    except Exception as exc:
        # 检索失败时记录警告并 fallback 全文，保证游戏不中断
        log.warning(
            "world_rag: retrieval failed for world %d, falling back to full text: %s",
            world_id, exc,
        )
        return text

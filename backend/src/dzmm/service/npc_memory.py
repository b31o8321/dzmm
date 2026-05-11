# ============================================================
# npc_memory.py — NPC 长期记忆系统（向量存储）
# ============================================================
# 【NPC 记忆系统是什么？】
#   每个 NPC 都有自己的"记忆库"，存储它说过的话和经历过的事件。
#   每次 NPC 说话（<say speaker="X">...</say>），就往它的记忆库里存一条。
#   GM 开始新的一回合前，先从每个在场 NPC 的记忆库里检索与当前情节最相关的几条，
#   注入到 key_facts 里，帮助 GM 保持 NPC 行为前后一致。
#
# 【为什么需要这个系统？】
#   LLM 只能记住 Prompt 里的内容，但 Prompt 长度有限制。
#   如果游戏已经进行了 50 回合，早期的对话早就被截断了。
#   NPC 记忆系统用向量搜索从"记忆长河"中捞出最相关的片段，
#   让 NPC 表现得像真的记得过去的事情。
#
# 【存储位置】
#   ~/.dzmm/chroma_npc/（每个 NPC 一个独立的 ChromaDB collection）
#
# 【v1 设计决策：不使用 LLM 摘要器】
#   规格书提到了先用 LLM 摘要再存储，但 v1 直接存原始 <say> 文本（限 300 字）。
#   理由：避免额外的 LLM 调用，简化实现；摘要可以作为未来优化加入。
#
# 【故障处理原则】
#   所有公开函数在遇到任何基础设施问题时（Ollama 不可用、ChromaDB 报错）
#   都静默跳过。记忆是"增强"功能，丢失一条记忆绝不能中断游戏。
# ============================================================
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_TOP_K = 3        # 每次检索返回最相关的 3 条记忆
_APP_DIR: Path | None = None  # 应用数据目录（由 init_npc_memory 在启动时设置）


def init_npc_memory(app_dir: Path) -> None:
    # 启动时调用一次，设置存储目录并确保目录存在
    # 必须在首次调用 record_memory/retrieve_memories 之前调用
    global _APP_DIR
    _APP_DIR = app_dir
    # parents=True: 若父目录不存在也一起创建
    # exist_ok=True: 目录已存在时不报错（幂等）
    (app_dir / "chroma_npc").mkdir(parents=True, exist_ok=True)


def _coll_name(npc_id: int) -> str:
    # 生成 NPC 的 ChromaDB collection 名称
    # 每个 NPC 独立一个 collection，隔离各 NPC 的记忆
    return f"npc_mem_{npc_id}"


def _client():
    # 创建 ChromaDB 客户端
    # 延迟导入 chromadb：测试环境可能没安装，不应在模块加载时就报错
    import chromadb
    if _APP_DIR is None:
        raise RuntimeError("init_npc_memory() not called")
    # PersistentClient：数据存到磁盘，重启后记忆不消失
    return chromadb.PersistentClient(path=str(_APP_DIR / "chroma_npc"))


def _embed_sync(base_url: str, text: str) -> list[float]:
    # 同步版向量化函数，在线程池内运行
    # （asyncio.to_thread 会把它放到线程池，所以这里可以用同步代码）
    from dzmm.service.world_rag import OllamaEmbedder
    embedder = OllamaEmbedder(base_url=base_url)
    return embedder.embed_query(text)  # 返回浮点数列表（embedding 向量）


async def record_memory(
    npc_id: int,      # 哪个 NPC 的记忆
    turn: int,        # 这条记忆发生在第几回合（用于检索时提供元数据）
    text: str,        # 记忆内容（NPC 说的话或做的事）
    ollama_url: str,  # Ollama 服务地址（用于向量化）
) -> None:
    # 为指定 NPC 存入一条记忆
    # 【调用方式】应使用 asyncio.create_task() 调用（fire-and-forget），
    # 不要 await，这样不会拖慢当前回合的响应速度
    if not text.strip() or _APP_DIR is None or not ollama_url:
        return  # 空文本或未初始化，跳过
    try:
        doc = text[:300]  # 限制 300 字，避免单条记忆过大影响向量质量
        # asyncio.to_thread 把同步的向量化放到线程池，不阻塞事件循环
        emb = await asyncio.to_thread(_embed_sync, ollama_url, doc)
        # get_or_create_collection: collection 不存在时自动创建（幂等）
        coll = await asyncio.to_thread(_client().get_or_create_collection, _coll_name(npc_id))
        count = await asyncio.to_thread(coll.count)  # 获取当前记忆条数（用于生成唯一 ID）
        await asyncio.to_thread(
            coll.add,
            ids=[f"t{turn}_{count}"],    # 格式：t{回合号}_{序号}，确保唯一
            documents=[doc],              # 原始文本
            embeddings=[emb],             # 向量
            metadatas=[{"turn": turn}],   # 元数据，方便后续按回合过滤
        )
    except Exception as e:  # noqa: BLE001
        # 静默失败：记忆是增强功能，不应因此中断游戏
        log.debug("npc_memory: record failed for npc %d: %s", npc_id, e)


def delete_npc_memory(npc_id: int) -> None:
    # 删除某个 NPC 的全部 ChromaDB 记忆
    # 在以下场景调用：存档删除 / NPC 删除 / NER 自动清理
    # 防止向量数据在 NPC 行已删除后仍占用磁盘
    #
    # 任何失败都静默处理（_APP_DIR 未初始化、collection 不存在、ChromaDB 报错）
    # 内存清理是"尽力而为"，绝对不能因此阻断删除操作
    if _APP_DIR is None:
        return
    try:
        client = _client()
        client.delete_collection(_coll_name(npc_id))
    except Exception as e:  # noqa: BLE001
        log.debug("npc_memory: delete failed for npc %d: %s", npc_id, e)


async def retrieve_memories(
    npc_id: int,        # 哪个 NPC 的记忆库
    query: str,         # 用当前场景/玩家行动作为查询
    ollama_url: str,    # 向量化服务地址
    k: int = _TOP_K,    # 返回几条最相关的记忆
) -> list[str]:
    # 从 NPC 的记忆库里检索与当前情节最相关的 top-k 条记忆，返回文本列表
    # 任何失败时返回空列表（调用方可以安全地忽略空结果）
    if not query.strip() or _APP_DIR is None or not ollama_url:
        return []
    try:
        # 把查询文本也向量化（限制 200 字，查询不需要太长）
        q_emb = await asyncio.to_thread(_embed_sync, ollama_url, query[:200])

        def _query_chroma() -> list[str]:
            # 这个内部函数在线程池里运行（ChromaDB 是同步的）
            coll = _client().get_or_create_collection(_coll_name(npc_id))
            if coll.count() == 0:
                return []  # 空记忆库，直接返回
            result = coll.query(
                query_embeddings=[q_emb],            # 查询向量
                n_results=min(k, coll.count()),      # 不超过库里实际有的条数
            )
            docs = result.get("documents") or []
            return docs[0] if docs else []  # 取第一个查询的结果（支持批量查询，取第一批）

        return await asyncio.to_thread(_query_chroma)
    except Exception as e:  # noqa: BLE001
        # 检索失败静默返回空列表，不中断游戏流程
        log.debug("npc_memory: retrieve failed for npc %d: %s", npc_id, e)
        return []

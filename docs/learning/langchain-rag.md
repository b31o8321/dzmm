# Phase A：LangChain RAG 实现

> 本文对应 `service/world_rag.py`，讲解 RAG 的完整流程和所用到的 LangChain 技术。

---

## 1. 什么是 RAG

RAG = Retrieval-Augmented Generation（检索增强生成）。

**问题：** 世界书全文塞进 Prompt 太长，7B 模型处理不了。

**解法：**
```
世界书 → 分块 → 向量化 → 存入向量库
每回合: 玩家行动 → 向量化 → 相似度搜索 → 取 top-k 块 → 注入 Prompt
```

---

## 2. LangChain Embeddings 接口

[`service/world_rag.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/world_rag.py) — `OllamaEmbedder`：

```python
from langchain_core.embeddings import Embeddings

class OllamaEmbedder(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
```

`Embeddings` 是 LangChain 定义的 ABC（抽象基类），任何向量模型都实现它。
项目里用 `httpx` 直接调用 Ollama `/api/embeddings`，不依赖 `langchain-community` 的 Ollama 集成，更轻量。

---

## 3. RecursiveCharacterTextSplitter

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_text(content_md)
```

递归按 `["\n\n", "\n", "。", " ", ""]` 顺序切割：优先段落边界，实在不行才硬切字符。
`chunk_overlap=50` 让相邻块重叠 50 字符，防止语义在边界断裂。

---

## 4. ChromaDB 本地向量库

```python
import chromadb

client = chromadb.PersistentClient(path="~/.dzmm/chroma/1")
col = client.create_collection("world_1")
col.add(ids=["1_0", "1_1"], documents=["块A", "块B"], embeddings=[[...], [...]])
```

ChromaDB 是本地文件向量库，不需要额外服务。数据存在磁盘，重启后不丢失。

检索：
```python
results = col.query(query_embeddings=[query_vec], n_results=4)
docs = results["documents"][0]   # list[str]
```

---

## 5. 优雅降级

`get_world_md()` 是决策函数，按优先级：
1. `ollama_url=None` → 全文（embed 不可用）
2. `len(content_md) < 800` → 全文（不值得 RAG）
3. `not is_indexed(world_id)` → 全文（未建索引）
4. 否则 → top-k 检索结果；异常时 fallback 全文

这样 RAG 不影响未索引的世界，也不会因 Ollama 不可用而崩溃。

---

## 6. 异步包装

ChromaDB 是同步 API。在 async 代码里调用同步 I/O 会阻塞事件循环：

```python
# 错误：直接在 async 函数里调用同步阻塞操作
# 正确：用 asyncio.to_thread 放到线程池
await asyncio.to_thread(index_world, world_id, content_md, ollama_url)
```

`asyncio.to_thread` 把同步函数交给线程池执行，不阻塞事件循环。
这是 FastAPI/asyncio 项目中调用同步库的标准做法。

---

## 7. 使用流程

1. **首次创建世界书**：创建/更新世界后，系统自动触发 `index_world_async`（fire-and-forget）
2. **手动重索引**：大量修改世界书后，调用 `POST /worlds/{id}/reindex` 刷新
3. **游戏中**：每回合自动检索，无需手动操作
4. **Embedding 模型**：需要 Ollama 运行 `nomic-embed-text`（`ollama pull nomic-embed-text`）

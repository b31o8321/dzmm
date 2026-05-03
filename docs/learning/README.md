# DZMM 学习笔记目录

> 本目录整理了项目中用到的关键技术，特别是 **LLM 工程化**相关的设计决策和实现方式。
> 适合有 Java 背景、Python 基础的开发者阅读。

---

## 文档列表

| 文档 | 内容 |
|------|------|
| [01-架构总览](01-architecture.md) | 项目整体架构、技术栈、分层设计 |
| [02-LLM工程化](02-llm-engineering.md) | **核心**：Prompt 设计、上下文管理、流式处理、弱模型适配 |
| [03-Python入门](03-python-for-java-devs.md) | 面向 Java 开发者的 Python 关键语法对比 |

---

## 快速跳转：核心文件（含注释）

所有带注释的源文件都在这里：

**Python 后端：**
- [db/models.py](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/db/models.py) — 数据库 ORM 实体（SQLAlchemy）
- [models/client.py](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/models/client.py) — LLM 抽象接口（ABC + async generator）
- [parsing/stream_parser.py](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/parsing/stream_parser.py) — 流式 XML 解析（状态机）
- [service/game.py](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/game.py) — 游戏引擎核心（async generator 驱动）
- [api/routes_sessions/turn.py](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/api/routes_sessions/turn.py) — HTTP 路由（FastAPI + SSE）

**Vue3 前端：**
- [composables/useGameTurn.ts](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useGameTurn.ts) — 回合状态管理（Composable）

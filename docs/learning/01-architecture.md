# 01 — 项目架构总览

## 整体结构

```
dzmm/
├── backend/          Python 后端（FastAPI + SQLAlchemy + 异步）
│   └── src/dzmm/
│       ├── api/          HTTP 路由层（Controller）
│       ├── service/      业务逻辑层（Service）
│       ├── db/           数据库层（ORM 实体 + 初始化）
│       ├── models/       LLM 客户端抽象层
│       ├── parsing/      流式 XML 解析器
│       └── prompts/      GM Prompt 模板
└── frontend/         Vue3 前端（Vite + TypeScript + Element Plus）
    └── src/
        ├── views/        页面组件
        ├── components/   可复用 UI 组件
        ├── composables/  业务逻辑 Hooks（类比后端 Service）
        ├── stores/       全局状态（Pinia）
        └── api/          HTTP 请求封装
```

## 技术栈

| 层次 | 技术 | Java 对比 |
|------|------|-----------|
| HTTP 框架 | FastAPI | Spring MVC |
| ORM | SQLAlchemy（async） | JPA/Hibernate |
| 数据库 | SQLite（开发）/ 可换 Postgres | H2/MySQL |
| 数据校验 | Pydantic | Bean Validation / Lombok |
| 异步运行时 | asyncio | CompletableFuture / Project Reactor |
| 前端框架 | Vue3 Composition API | — |
| 前端状态 | Pinia | — |
| 前端 HTTP | axios | OkHttp |
| LLM 本地部署 | Ollama | — |

## 一次回合的完整链路

```
玩家输入行动
    ↓
前端 useGameTurn.sendAction()
    ↓ HTTP POST /sessions/{id}/turn (SSE)
后端 API: take_turn()
    ↓
后端 Service: run_turn() [async generator]
    ├── 读 DB（世界/角色/NPC/剧本/摘要）
    ├── 组装 GM System Prompt
    ├── 调用 LLM 流式生成（client.stream()）
    ├── 边生成边解析 XML（StreamingTagParser.feed()）
    ├── yield ParseEvent → API 层 → SSE → 前端
    └── 写 DB（apply_tags、持久化消息）
    ↓
前端 onTag() / onNarrative() 处理事件 → 更新 UI
```

## 为什么用 SSE 而不是 WebSocket？

- SSE 是单向推送（服务器→客户端），WebSocket 是双向通信
- 我们的场景是服务器主动推送流式文本，不需要客户端实时发消息
- SSE 基于普通 HTTP，不需要额外协议，兼容性更好
- SSE 断线自动重连，WebSocket 需要手动实现

# DZMM 学习文档

> 每篇文档都直接引用项目源码，点 GitHub 链接可跳到对应行。

## 文档

| 文档 | 内容 |
|------|------|
| [Python 后端实现](python-backend.md) | async/await、SQLAlchemy、FastAPI、数据库迁移 |
| [LLM 工程化实现](llm-engineering.md) | Prompt 设计、流式解析、上下文管理、弱模型容错 |
| [Vue3 前端实现](vue-frontend.md) | SSE 消费、Composable、Pinia Store、响应式原理 |

## 一次回合走完整个调用链

```
玩家点击"发送"
  ↓ useGameTurn.sendAction()           [frontend/composables/useGameTurn.ts]
  ↓ streamTurn()                       [frontend/composables/useTurnStream.ts]
  ↓ fetch POST /sessions/{id}/turn     HTTP SSE
  ↓ take_turn() API 路由               [backend/api/routes_sessions/turn.py]
  ↓ run_turn() 业务逻辑                [backend/service/game.py]
  ↓   读 DB（世界/角色/剧本/NPC）
  ↓   组装 GM System Prompt
  ↓   client.stream() LLM 调用         [backend/models/ollama.py]
  ↓   StreamingTagParser.feed()        [backend/parsing/stream_parser.py]
  ↓   yield ParseEvent → SSE 推送
  ↓   apply_tags() 写 DB               [backend/service/state_apply/_impl.py]
  ↓ 前端 onNarrative/onTag 回调
  ↓ turn.narrative += text → Vue 重渲染
```

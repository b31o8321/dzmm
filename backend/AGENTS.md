# Backend Agent Guide

本文件适用于 `backend/`。同时遵守根目录 `AGENTS.md`。

## 边界与入口

- 应用构建：`src/dzmm/main.py`；开发启动：`scripts/run_dev.py`。
- API 只负责校验、事务编排和 SSE 映射；可复用业务逻辑放在 `service/` 或 `engine/`。
- `db/models.py` 是 ORM；`models/` 是 LLM 协议客户端。讨论“模型”时写清是哪一种。
- Session 路由已拆到 `api/routes_sessions/`，新增 session 能力放入最贴近资源的模块，
  不要继续扩大聚合入口。

## LLM 客户端契约

- 所有提供方通过 `models/client.py::ModelClient` 暴露 `stream()`。
- `models/factory.py::build_client()` 根据持久化的 `ModelConfig.type` 选择协议。
- Ollama 流是逐行 JSON；OpenAI-compatible/LM Studio 流是 `data:` SSE。不要混用解析器。
- HTTP 成功不等于生成成功。错误 JSON、空流、缺少终止块和空文本必须成为可观察失败，
  不能推进一个内容为空的正常回合。
- 调整 payload 或解析时，分别覆盖协议端点、增量内容、结束原因、usage、服务错误和畸形 200。

相关聚焦测试：

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_ollama.py tests/test_ollama_usage.py
.venv/bin/python -m pytest -q tests/test_openai_compat.py tests/test_factory.py
.venv/bin/python -m pytest -q tests/test_model_check.py
```

## 回合与事务

`api/routes_sessions/turn.py` 是 HTTP/SSE 边界；主业务和 agent 编排在 `service/game.py`、
`service/agents/`，状态标签落库在 `service/state_apply/`。

- user/assistant 消息、解析事件、状态应用、usage 和 turn 计数应表达同一次回合结果。
- 模型失败或空输出时，不要制造“成功但空白”的历史；明确 error 事件及可重试语义。
- SSE 消费者可能中途断开。修改提交时机前，先画清已持久化和仅流出的状态。
- Director、Scene、NPC agent 有独立 stream/history；不要把相邻 agent 的失败等同于主叙事失败。
- Python-first 规则结果应先计算，再作为事实提供给 LLM 叙述。

聚焦回合测试优先搜索 `tests/test_*turn*.py`、`tests/test_orchestrator.py`、
`tests/test_state_apply.py` 和目标 handler 的测试。

## 数据库与文件

- 开发默认库也是 `~/.dzmm/dzmm.db`；自动化测试必须使用 fixture/临时路径。
- 本项目使用 `db/base.py` 中的启动时兼容迁移，不可假设所有用户从空库开始。
- schema 改动需同时验证新库、旧库升级、重复启动和默认值。
- API key 只能经 `secrets.py` 进入 OS keychain，不写入 DB、日志或错误响应。
- 上传资源和向量数据属于用户数据；删除操作要有明确目标和授权。

## Python 风格与验证

- 匹配现有 async SQLAlchemy/Pydantic 2 写法，不在 event loop 中加入阻塞网络或磁盘操作。
- 新行为先写能复现边界的测试，再做最小实现。
- 使用 `respx` 测外部 HTTP；禁止单测访问真实模型服务。
- 最低交付证据是目标 pytest；跨模块或 schema 改动再跑后端全量和 Ruff。


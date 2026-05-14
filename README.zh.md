# dzmm

在你自己的机器上运行的 AI 驱动 TRPG 文字冒险游戏。GM 是本地或云端 LLM；你带来世界观、角色和想象力。无需订阅，无需其他玩家。

> **English** → [README.md](README.md)

> **状态：** 暂停更新 · 最终版本 **v0.10.2**。完整更新历史见 [CHANGELOG](CHANGELOG.md)。
>
> 该项目作为一个完整的学习案例存档。代码里附有详细的中文注释（面向只懂 Python 语法的初学者），配套学习文档见 [docs/learning/](docs/learning/)。

---

## 功能一览

- **多 Agent stateful GM（v0.10）** — GM 拆分为 **Director**（长期剧情决策，每 5 回合或重大事件触发一次）、**Scene**（叙事 + 骰子 + 状态，每回合流式生成）、**每个主要 NPC**（各自独立 stateful 对话历史，保证人格不漂移）。解决了"单 LLM 把 NPC 张冠李戴"和"既要管长期剧情又要管短期场景导致节奏差"两大根本问题。
- **场景拓扑（v0.10）** — 显式 `LocationEdge` 关系图（contains / adjacent / connects / blocked），杜绝"实验室在修道院地下→几回合后从修道院出来回到实验室"这种空间漂移。GM 首次登记新地点时被强制声明它和已知地点的关系。
- **向导式世界观 + 角色创建** — 6 步引导式 LLM 生成（世界简介 → 世界详情 → 角色 → NPC 阵容 → 剧本大纲 → 审阅）。每步均可独立编辑和重新生成。
- **首回合自动生成剧本大纲** — 第一回合结束后，GM 自动接收章节化大纲（主要事件 / 可选支线 / 主要角色 / 完结条件），让故事从一开始就保持连贯。
- **流式叙事** — 文字逐字出现，如同真人 GM 边打边发。
- **结构化状态追踪** — HP / 理智 / 背包 / NPC 好感 / 情绪通过 GM 输出的类 XML 标签自动更新（`<state_change>`, `<npc_update>`, `<pc_goal>`, `<pc_mood>` 等）。
- **场景与 NPC 位置追踪** — GM 记录 PC 所在位置、在场 NPC 及场景物品。NPC 离场时自动从场景清除。
- **NPC 主动行为** — 沉默数回合后，高热情值的 NPC 会自动主动联系 PC（无需玩家输入），让世界保持生命力。
- **剧情线** — 任务、钩子和重大事件被追踪并重新注入到未来的 prompt，保持战役连贯。
- **剧本驱动节奏** — GM 被引导每 1-2 回合推进主线事件；滞留时 key_facts 中会出现"剧情强推"警告。
- **骰子系统** — d20 + DC 检定（标准模式）；失败产生真实后果，而非"什么都没发生"。
- **手机 / 平板访问** — 可选 LAN 模式，让同一 WiFi 下的任何设备都能游玩。
- **导出** — 以 JSON 或 Markdown 格式下载完整会话。

---

## 快速开始

### 方案 A：预构建应用（推荐）

1. 安装 [Ollama](https://ollama.com/download)，然后拉取模型：
   ```bash
   ollama pull qwen2.5:7b
   ```
2. 从 [Releases](https://github.com/YOUR_USERNAME/dzmm/releases) 下载最新版本：
   - **macOS（Apple Silicon）**：`dzmm_x.y.z_aarch64.dmg`
   - **Windows x64**：`dzmm_x.y.z_x64-setup.exe`
3. 安装并启动。macOS 首次运行：右键 → 打开（Gatekeeper 警告）。
4. 点击 **跑团 → + 新开一局**。内置四个预设世界观——选一个开始游玩。

### 方案 B：从源码开发

依赖：Python 3.11+、Node 18+、Rust stable、Ollama。

```bash
git clone https://github.com/YOUR_USERNAME/dzmm.git
cd dzmm

# 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 前端
cd ../frontend && npm install

# 启动（3 个终端）
# 1) ollama serve
# 2) cd backend && python scripts/run_dev.py
# 3) cd frontend && npm run dev
```

打开 http://localhost:5173。

---

## 推荐模型

GM prompt 使用结构化类 XML 标签。产生大量推理 token（`<think>` 块）或忽略格式指令的模型会出现问题。

| 模型 | 大小 | 说明 |
|---|---|---|
| `qwen2.5:7b` | 4.7 GB | 本地**最佳平衡** — 标签格式遵守好 |
| `qwen2.5:14b` | 9 GB | 叙事深度更好；需要 ≥16 GB RAM |
| `llama3.1:8b` | 4.7 GB | 不错的备选 |
| `gpt-4o-mini`（云端） | — | 格式遵守极佳，约 $0.08 / 游戏小时 |
| `claude-haiku-4`（云端） | — | 格式遵守极佳，成本相近 |

云端模型使用 `openai_compat` 配置类型 — 适用于 OpenAI、Anthropic（via proxy）、DeepSeek、豆包、通义、零一万物，或任何 OpenAI 格式的 API。

---

## 架构概览

```
┌──────────────────────────────────────────────┐
│  Tauri 2 外壳（Rust）                         │
│  • 启动时生成后端 sidecar                      │
│  • 承载前端 webview                           │
│  • 窗口关闭时终止后端                          │
└─────────────────┬────────────────────────────┘
                  │
      ┌───────────▼──────────────┐    ┌────────────────────┐
      │ FastAPI 后端（:8765）    │───▶│  Ollama / 云端 LLM  │
      │  /sessions/{id}/turn     │    └────────────────────┘
      │  SSE 流式               │
      │  SQLite 持久化           │
      │  标签驱动状态更新         │
      └───────────┬──────────────┘
                  ▲
                  │ axios + fetch（SSE）
      ┌───────────┴──────────────┐
      │ Vue 3 + Vite 前端        │
      │  流式解析器              │
      │  Element Plus UI         │
      │  Pinia 状态管理          │
      └──────────────────────────┘
```

- **后端：** Python 3.11+ · FastAPI · SQLAlchemy 2.0 async · aiosqlite
- **前端：** Vue 3 · TypeScript · Element Plus · Tailwind CSS · Pinia
- **桌面端：** Tauri 2（Rust 外壳，约 5 MB）+ PyInstaller 打包后端（约 45 MB）
- **存储：** SQLite 位于 `~/.dzmm/dzmm.db`；日志位于 `~/.dzmm/dzmm.log`（5 MB × 3 轮转）；API key 存 OS 密钥链

深度技术解读见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## LAN / 手机访问

在应用欢迎对话框中选择 **启用手机访问**。后端将绑定至 `0.0.0.0:8765` 并显示你的 LAN URL。在手机浏览器中输入该 URL — 两台设备须在同一 WiFi 网络。

> 不要在不受信任的网络（咖啡馆等）上启用 — 后端无鉴权。

---

## 从源码构建

```bash
# macOS / Linux
python packaging/build.py

# Windows（PowerShell）
.\packaging\build.ps1
```

产物输出至 `packaging/dist/`。部分重构（仅后端，或复用已有后端运行时）见 [packaging/README.md](packaging/README.md)。

推送 `v*` tag（如 `v0.2.7`）会触发 `.github/workflows/release.yml`，并行构建 macOS 和 Windows 并发布 GitHub Release。

---

## 项目结构

```
dzmm/
├── backend/
│   ├── src/dzmm/
│   │   ├── api/routes_sessions/   每资源路由模块
│   │   ├── db/                    ORM 模型 + 迁移
│   │   ├── service/               游戏循环、状态应用处理器、NPC 主动行为
│   │   ├── prompts/               GM 模板、大纲生成器、摘要器、向导 prompt
│   │   └── parsing/               流式标签解析器
│   └── tests/                     346+ pytest 测试
├── frontend/src/
│   ├── views/                     GameView、SessionsView、WizardView 等
│   ├── components/                MessageList、StatePanel、SpeakerBubble 等
│   ├── composables/               useGameTurn、useTurnStream、useGameState 等
│   ├── api/                       类型化 API 客户端
│   └── stores/                    Pinia 状态
├── packaging/                     构建编排
├── docs/
│   ├── ARCHITECTURE.md
│   └── superpowers/plans/         实现计划
├── CHANGELOG.md
└── README.md
```

---

---

## 学习文档

项目代码里全面添加了面向初学者的中文注释（假设读者只懂 Python 语法，不懂 FastAPI / SQLAlchemy / 系统架构）。配套的学习文档在 [`docs/learning/`](docs/learning/)：

| 文档 | 内容 |
|------|------|
| [**代码阅读路径**](docs/learning/code-reading-path.md) | **推荐入口：** 7 阶段分步学习路线，从启动到多 Agent |
| [Python 后端实现](docs/learning/python-backend.md) | async/await、SQLAlchemy、FastAPI、数据库迁移 |
| [LLM 工程化实现](docs/learning/llm-engineering.md) | Prompt 设计、流式解析、上下文管理、弱模型容错 |
| [Vue3 前端实现](docs/learning/vue-frontend.md) | SSE 消费、Composable、Pinia Store、响应式原理 |
| [Phase A：LangChain RAG](docs/learning/langchain-rag.md) | OllamaEmbedder、ChromaDB、优雅降级 |
| [Phase B：LangGraph 多 Agent](docs/learning/langgraph-multiagent.md) | StateGraph、条件边、闭包注入、多 Agent 编排 |
| [Phase C：自主 Agent 评测](docs/learning/agent-eval.md) | LLM-as-Judge、Player Agent、Judge Agent |
| [TRPG LLM 优化策略](docs/learning/trpg-llm-optimization.md) | RAG/多Agent/铁律/骰子/流式/三级解析的落地方案 |

---

## 后续规划（未实现）

项目在 v0.10.2 暂停前排好了以下方向，留作参考或后续继续：

**Phase C — 自主 Agent 自动评测**
- Player Agent（自动扮演玩家，模拟多种决策风格）
- Judge Agent（LLM-as-Judge，按维度打分：叙事连贯性、状态一致性、骰点公平性）
- 评测 runner：批量跑存档 → 生成质量报告，为 QLoRA 微调准备数据

**Phase D — QLoRA 微调**
- 用 Phase C 收集的「好回合」数据，微调一个 TRPG 专用小模型
- 目标：7B 模型达到 GPT-4o-mini 在 TRPG tag 合规率上的水平
- 硬件：台式 Linux + RX 9070

**v0.11+ 开放世界框架**（骨架已在 v0.10.2 合入，未完全打磨）
- WorldFramework：地点 / 势力 / NPC 模板 / 事件库，替代线性剧本章节
- Director Agent 从「读章节」改为「读附近可用事件 + 主线进度」生成 plot_directive
- 地理 BFS 距离影响事件优先级，比单纯时间线更自然

**v0.14 剧本驱动（更大重构）**
- 开新档时 LLM 一次性生成剧本大纲（章节 / 主要 NPC / 关键事件 / 完结条件）
- GM 每回合围绕大纲发挥，而非凭空创作主线
- 玩家重大决策触发 `<plot_turn>` 标签 → 后端异步重写后续大纲
- 大纲完结后可续写（Season 2），或按 genre 模板（悬疑/英雄/政治/恋爱）生成新存档

---

## 许可

个人爱好项目 — 许可待定。转载前请先联系。

## 鸣谢

与 Claude（Anthropic）协作构建。流式标签解析器、结构化状态应用分发机制和剧本驱动 GM prompt 设计均源于这段合作。

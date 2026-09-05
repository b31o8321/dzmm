# vNext 吸收旧版精华与单线化执行计划

日期：2026-09-05
状态：Accepted（决策点已拍板，见文末"已定决策"）
关联：[ADR-010 单一 DZMM 受控替换](../adr/ADR-010-single-dzmm-cutover.md)、[Active Delivery Index](../ACTIVE_DELIVERY_INDEX.md)
基线：`feature/dzmm-vnext` @ `b0c6398`（main @ `df38037`，vnext 领先 165 commits，旧代码零改动）

## 目标

推进 vNext 成为唯一产品线：先吸收旧版 dzmm 的已验证精华补齐可玩性密度，
再关闭 ADR-010 的 cutover gates，最后按受控替换合入 main。

新增目标（2026-09-05）：与酒馆 AI（SillyTavern）生态的资源互通作为一等公民
能力——角色卡、世界书尽量双向互用；同时以 ruleset 预设保留 D20/DnD 风格规则。

## 非目标

- 不做旧版数据库自动迁移（ADR-010 已定：不迁移 + 玩家主动导出/导入）。
- 不恢复 remote/LAN/mDNS/配对能力（ADR-008/010 已裁决删除，不再回头）。
- 不在 cutover 前动 main（旧版只作为可玩回退与对照基线）。

## 现状快照（2026-09-05 功能对照结论）

vnext 已有且优于旧版：流式 SSE 回合、contract-first 命令引擎（`command_engine`
白名单命令 + capability 门控）、AI 世界草案（生成/校验/修复）、SillyTavern 内容
互通、World 归档/恢复/版本/purge、portable bundle + clone、模型档案完整 CRUD/
probe/run 级热切换/keyring、回合 undo（幂等+revision）、三端共享 Python core
（Android 内嵌离线）、193 个 phase 证据的 eval scorecard。

vnext 缺口（旧版有）：见下方吸收清单。

## 吸收清单（旧版 → vnext）

### Wave 1 — 可玩性密度与资源互通（cutover 前完成）

| 项 | 旧版资产 | 吸收方式（适配 vnext 架构，不照抄） | 验收 |
|---|---|---|---|
| A. 战斗 capability | `backend/src/dzmm/engine/combat.py`（命中/伤害/先攻/击败） | 新增 `combat` capability：command_engine 增加 `attack`/`initiative` 命令，**capability 内置一套默认 d20 公式，ruleset 可覆盖数值**（AC/伤害骰/属性修正等）；Python 结算后结果进 state，GM 只叙述 | ruleset 开启 combat 后 10 回合含战斗的跑团测试 + 结算与叙述一致 + 默认公式与覆盖公式各一组单测 |
| B. D20/DnD 规则预设 | 旧版 d20 规则、DnD 风格 | 基于 A 的 combat + 现有 4 种 ruleset 类型，新增 `d20_trpg` 预设 ruleset（六属性/D20 检定/AC/先攻的默认配置），作为内置模板与 fog_harbor 并列 | d20 预设开局 → 骰子/战斗/结局全链路测试 |
| C. genre 模板库 | `engine/genre_templates.py`（5 canonical genres）+ 旧版向导 9 genre | `ai_world_drafts` 增加 genre 预设参数（而非自由文本猜）；模板进入 `world_templates.py` | 每个 genre 可生成 → validate 通过 → 开局可玩 |
| D. SillyTavern 互通深化 | vnext 已有 `content.py`/`sillytavern.py` 角色卡+世界书导入导出底子 | 先盘点已支持字段 vs ST 角色卡 v2/v3 规范与世界书全字段，补齐高频字段（first_mes/alternate_greetings/character_book 嵌入/creator_notes 等）；双向导入导出 + 实测与酒馆 AI 互换样本文件 | 用真实 ST 导出文件导入 vnext 再导出回 ST 可用；往返不丢关键字段 |

### Wave 2 — cutover 收尾（ADR-010 Action Items 1-5）

1. macOS 安装包可见 WebView GUI 主路径验收（当前缺）。
2. ~~Windows installer 安装后主路径验收~~ **豁免**（用户决定：无 Windows 机器；
   NSIS/sidecar 构建 smoke 已通过作为工程证据，安装后 GUI 验收标记 waived，
   留待未来有设备或社区反馈补齐——记录于 ADR-010 gates）。
3. Android 真机验收降级为可选：**模拟器验收即为通过标准**（用户决定；phase157/
   158 已完成，真机证据仅在未来可获得时补充）。
4. 完整 cutover 回滚演练（归档 tag 已建 `dzmm-legacy-v0.16.0-2026-08-30`）。
5. 统一内部命名：`dzmm_vnext`/`DZMM Next`/`~/.dzmm-vnext-v3` → 单一 DZMM。
   **已定**：cutover 时默认数据目录统一回 `~/.dzmm/`，数据库文件用新名与旧
   `dzmm.db` 区分；旧库文件原样保留、不读不写，应用内提供"旧版数据不自动迁移"
   提示与导出/导入入口（与 ADR-010 迁移策略一致）。
6. 玩家评分从 78 → ≥85，更新 Index。

### Wave 3 — cutover 后吸收（单线上做，避免双轨期膨胀）

| 项 | 旧版资产 | 建议处置 |
|---|---|---|
| 多 Agent GM | `service/agents/`（Director/Scene/per-NPC，LangGraph） | **设计议题，需新 ADR**：vnext 是单 GM 调用 + story beat 投影 + NPC initiative 调度，已解决部分旧版多 Agent 想解决的问题。建议先吸收"Director 长线节奏"作为叙事上下文注入（轻量），per-NPC 编排等单 GM 短板实测出现再引入 |
| 世界 RAG | `service/world_rag.py`（ChromaDB） | vnext 有关键词 lorebook 注入。RAG 仅在大世界书时收益明显，且 Android 内嵌 core 加载向量库成本高——建议做成桌面端可选 capability，不进默认链路 |
| TTS/BGM | `tts/{edge,kokoro,cosyvoice}`、useAudio | 桌面端独立模块，portable 可后补；Android 暂缓 |
| per-agent debug | `routes_debug_agents` | vnext `/diagnostics` 基础上按需扩展 |
| MD 导出 | 导出管线 | 低成本补齐到 portable 管线 |

### 明确不吸收

- LAN/remote/配对（ADR 已裁）、旧 schema v2 与 `service/game.py` 聚合路径、
  旧版 openai/lm_studio 之外的协议适配（vnext 已覆盖同三协议）。

## 已定决策（2026-09-05，产品维护者拍板）

1. **战斗**：capability 内置默认 d20 公式，ruleset 可覆盖数值（简化版 B 方案）。
2. **数据目录**：cutover 时统一回 `~/.dzmm/`（新 db 文件名区分，旧库原样保留）。
3. **多 Agent**：cutover 后立即开 ADR，先只做 Director 叙事节奏注入。
4. **验收范围**：macOS + Android（模拟器）；Windows 安装后 GUI 验收豁免（无设备），
   以构建 smoke 为工程证据。

## 排序与里程碑

```
M1  Wave1-A/B 战斗 capability + d20 预设        （先做，规则基础）
M1' Wave1-C/D genre 模板 + SillyTavern 互通深化  （可并行）
M2  Wave2 macOS/Android 验收 + 回滚演练          （gate 关闭，Windows 豁免）
M3  Wave2 命名/数据目录统一 ADR + cutover 分支
M4  cutover 合入 main，归档旧版，vnext 单线
M5  Wave3 Director 注入 ADR + 按需吸收 RAG/TTS
```

## 本轮已核实的事实

- vnext backend 146 tests passed（Index 记录，候选 `de1a2f8`）；桌面 Vitest 36、
  Flutter 25。
- 旧版归档 tag 已存在：`dzmm-legacy-v0.16.0-2026-08-30`。
- 两个 worktree 工作区均干净（dzmm-vnext 仅 `vnext/desktop/src/style.css` 一处
  未提交改动，非本轮产生，保留）。

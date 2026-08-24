# DZMM vNext：全平台 Local Host 规格与实施计划

**状态：** Architecture frozen；Android runtime spike 与 portable backend slice 已验证，完整垂直切片待完成
**日期：** 2026-08-19  
**关联：** ADR-008；取代 ADR-006 / ADR-007 的移动端范围

## 1. 产品规格

### 问题与目标

玩家不应为了在手机上创作或游玩而先打开电脑、启动服务、连接局域网并维持配对。DZMM 在任一
设备上都必须是可独立使用的互动叙事终端：该设备保存世界和 Run、Python 裁判状态、直接请求模型。

P0 目标：

1. Android 不连接 PC/Mac 也能从 AI 草案到可恢复的三回合、结局和回滚（当前仍为未完成 P0 gate）。
2. 同一 schema v3、受限命令、关系账本、结局判定与审计在 Mac、Windows、Android 产出一致事实。
3. 模型档案以完整协议保存并由当前设备直接 Probe；HTTP 200 error body 与空内容必须失败。
4. 每端能明确导出/导入内容或克隆 Run；不产生隐式双写和同步冲突。
5. Mac/Windows/Android 都是单一默认本地模式，用户不需要选择“启动 Host”或“连接 Host”。

### 非目标

- P0 不做 PC ↔ 手机自动同步、后台复制、冲突合并、云账户、中继、NAT 穿透、LAN pairing 或 mDNS。
- P0 不把 Flutter/Dart 变成规则裁判，不接受 LLM 任意 Python、脚本、正则或 command。
- P0 不将本地大模型权重打进 Android APK；后续可支持可下载的手机模型 runtime。
- 不迁移远程模式数据库、token、配对或旧 API；clean-slate 直接替换。

## 2. 运行时与数据设计

### 2.1 Local Host contract

每个安装都有一个固定 `LocalHostDescriptor`：

```json
{
  "host_instance_id": "uuid",
  "platform": "android|macos|windows",
  "storage_scope": "local_only",
  "api_mode": "in_process",
  "schema_version": 3
}
```

这不是网络服务发现协议。它只进入本机 audit、诊断和 portable export provenance，不含用户路径、
密钥、模型 URL 或设备标识。

`World`、`WorldVersion`、`Hero`、`Run`、`RunState`、`Turn` 均放在当前设备 SQLite；新 Run 在
创建时记录 immutable `execution_owner = local:<host_instance_id>`。所有 writes 继续经过 Python
`WorldComposer`、`TurnCoordinator`、`LifecycleService` 与 command allowlist，并使用 request ID 和
expected revision/base version。

### 2.2 Android runtime

Android 采用 Flutter UI + Kotlin bridge + embedded CPython：

```text
Flutter screen
  → typed Pigeon/MethodChannel request
  → Kotlin lifecycle / Android Keystore / file access
  → embedded CPython LocalHost core
  → app-private SQLite + direct ModelProvider stream
  → typed state/event projection to Flutter
```

首个 spike 不运行 FastAPI、Uvicorn、mDNS 或任意 loopback HTTP server。共享 core 不能 import
`fastapi`、`uvicorn`、`zeroconf`、pairing 或 remote router；这些只保留在 desktop adapter，随后删除
remote adapter。

### 2.3 模型与密钥

`ModelProfile` 在每个 Local Host 本地保存 `{type, base_url, model_name, credential_ref}`；profile
切换是完整 profile ID 替换，不能只写模型名。

- `ollama` 直连 `<base_url>/api/chat`。
- `lm_studio` / `openai_compat` 直连 `<base_url>/chat/completions`，其中 base URL 必须是 `/v1` 根。
- 密钥只由 Android Keystore 的 write-only ref 提供给 provider adapter；UI 与诊断只显示已配置状态。
- Android 允许用户配置的 HTTP provider（例如本机 Ollama/LM Studio）使用 cleartext；这只用于模型
  endpoint，不开放 DZMM Host、发现或配对服务。HTTPS provider 仍按 HTTPS 使用。
- 直接模型 stream 无内容、协议错误、取消或超时，在 commit 前失败，Run revision 和 Turn 数不变。

### 2.4 跨端携带，不做同步

`PortableBundle v1` 分为两类：

| Bundle | 包含 | 导入效果 |
| --- | --- | --- |
| `content_bundle` | WorldDefinition、lorebook、character_cards、资产 provenance | 在目标端创建新 WorldVersion。 |
| `run_clone_bundle` | content bundle、Hero、RunState、Turn audit、source revision | 在目标端创建新的 World/Run ID，标记为 cloned。 |

导入永远不会覆盖本地 World/Run。导入时做 schema v3、内容安全与 checksum 校验；失败时零写入。

## 3. 用户体验

| 入口 | Android / Mac / Windows 的共同含义 | P0 行为 |
| --- | --- | --- |
| 世界 | 本机世界、版本、归档、导出/导入 | 空态可创建或导入；删除采用本机确认。 |
| 创作 | 模板、世界书、角色卡、AI 草案审阅 | 模型只产草案；字段级校验与恢复后才明确 compose。 |
| 游玩 | 叙事、choice、关系原因、章节、结局、回滚 | UI 只提交受限意图，显示 core materialized projection。 |
| 模型 | 本机完整 profile、Probe、选择 Run 模型 | 直接调用 provider，清晰显示协议/空内容/超时恢复。 |
| 设置 | 本机数据、主题、诊断、导出 | 无 Host 地址、配对、scope、LAN 或启动模式。 |

桌面启动后直接进入世界中心；Android 首次启动直接进入“创建世界 / 导入内容 / 配置模型”空态，
不能首先出现连接或配对表单。

## 4. 分阶段 Plan

| 阶段 | 交付 | 退出证据 |
| --- | --- | --- |
| 0. 架构替换 | ADR-008、core/adapter map、新矩阵；ADR-006/007 标为 superseded | remote 假设不再出现在 P0 UI/API/验收。 |
| 1. Android Local Host spike | embedded CPython、SQLite、schema v3 雾港、Flutter bridge | 模拟器和 Redmi：本机 compose → 3 choice → ending → rollback → force-stop/reopen；SQLite/截图回读。 |
| 2. Direct model + authoring | local profile/probe/stream、AI draft 结构化审阅、WorldInfo/V3 card 本机导入导出 | 真实模型成功、空输出/200-error/取消失败；草案无效/恢复/重复确认零脏写。 |
| 3. Desktop simplification | Mac/Windows 无启动模式；移除 LAN/pairing/remote UI，desktop 使用 shared core | 打包 Mac、Windows 完成相同本机旅程；无 remote endpoint/设置残留。 |
| 4. Portable bundles | content export/import 与 Run clone | Android → desktop、desktop → Android 两方向；原 Run 不变、导入零覆盖。 |
| 5. RC | 签名包、无障碍、长局与恢复 | 每项 P0 >=85、总分 >=85、无开放 P0。 |

## 5. 成熟度矩阵（新口径）

历史 remote 成熟度不可转移。下表的基线是设计审计，不是旧 scorecard 的通过结果；当前增量证据记录在
`vnext/eval/evidence/phase58-android-local-host-vertical-slice.json`，仍未达到 P0 发布门槛。

| 维度 | 权重 | 当前可归属基线 | 85 分验收证据 |
| --- | ---: | ---: | --- |
| Python state truth、command、rollback | 20 | 75 | 三端使用同一 core 的 replay/rollback；LLM/client 越权零提交。 |
| Android Local Host 与本机恢复（P0） | 25 | 0 | 真机/模拟器 direct provider 全旅程、force-stop/reopen、SQLite 读回与截图。 |
| Direct model protocol 与流健壮性（P0） | 15 | 55 | Android 真实 provider：profile 切换、200-error、空输出、超时/取消均可恢复且无半回合。 |
| 内容与 AI 创作（P0） | 15 | 65 | Android/Mac/Windows 的结构化草案校验恢复、显式 compose、World Info/V3 card round-trip。 |
| 桌面本机 UX / 打包 | 10 | 70 | 打包 Mac+Windows 无模式选择，完整旅程和无障碍/失败重入截图。 |
| Portable bundle、隐私与本机安全（P0） | 10 | 25 | 双向 export/import/clone、无覆盖、无密钥泄漏、损坏包零写入。 |
| 工程与发布 | 5 | 35 | 三端签名 RC、fresh install/upgrade、诊断与发布门禁。 |
| **总计** | **100** | **43.75** | **加权 >=85，且每个 P0 >=85** |

## 6. P0 验收清单

1. Android 断开所有 DZMM PC 服务后，仍能用自己的 SQLite 与 direct model profile 完成 AI 草案 →
   无效编辑 → 字段级错误/恢复 → 明确 compose → 三 choice → ending → rollback → 重启恢复。
2. 同一场景在 Mac、Windows、Android 的 core replay 产出相同 state revision、flag、relationship reason
   和 ending；不同设备不会写同一个 Run。
3. Android 模型配置把 `type/base_url/model_name` 作为整体保存；LM Studio 误用 Ollama `/api/chat` 的
   HTTP 200 error body 被明确拒绝。
4. Android 直接访问 provider 的断网、超时、取消和空输出均不产生半 Turn，用户可 retry/reopen。
5. 各端启动页面没有模式选择、Host 地址、配对、QR、scope 或 LAN 开关；远程服务不再是运行依赖。
6. Portable bundle 在 Android ↔ desktop 的两个方向完成导入；每次产生新 ID，旧 World/Run 与 audit 不变。

## 7. 开放技术门槛

- **工程（阻塞 Stage 1）：** 已选定 Chaquopy 17.0 并验证 Android ABI、Python 3.11 与 SQLite marker；仍需实际验证 Android ABI、SQLite、SQLAlchemy、
  jsonschema、流式 HTTP 与取消；不能假设 desktop wheels 可直接复用。
- **产品（非阻塞）：** Android 本地模型 runtime 的 provider UI、模型下载、存储配额和后台生命周期留到
  P2；P0 使用 direct cloud 或用户可达的 LAN provider。
- **交付（阻塞 RC）：** 所有 remote/pairing API、LAN 权限、桌面手机联动页面与远程安全文档必须删除或
  明确历史化，不可与 Local Host 产品面同时发布。

## 8. 跨端前端适配（ADR-009）

Vue/Tauri 和 Flutter 不共享渲染组件，但必须共享 Experience Contract、LocalHostPort、中文文案/错误
key、a11y key 与设计 tokens。四个 P0 流程（世界中心、模型、AI 草案、游玩）以同一 fixture 在
390×844、768×1024、1440×900 验收；desktop 保持高密度/键盘路径，mobile 保持单列/底部导航/触控
可达。功能或构建“看起来都有”不构成 parity，必须覆盖加载、空态、schema 修复、provider 失败、
rollback 和重启恢复。

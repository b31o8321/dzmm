# ADR-008：每个平台都是本地 Host，Android 直接调用模型

**状态：** Accepted  
**日期：** 2026-08-19  
**决策人：** DZMM 产品负责人、工程负责人

## Context

用户需要把 Android 当作完整的 DZMM 终端：手机创建和保存世界、运行 Python 规则、直接调用自己
选择的模型，而不是连接一台必须常驻的 Mac/Windows Host。已配对远程客户端会把手机依赖、局域网
发现、授权、Host 可用性与跨端恢复放进每一次体验，不能满足这个目标。

“手机直接请求 LLM”不能等同于“Flutter 自行改状态”。若模型输出直接改变关系、Flag、章节、结局或
库存，DZMM 的 Python-first 不变量就会消失。因此改变的是 Host 的位置，不是状态裁判原则。

## Decision

### 1. 每个安装实例固定为一个 Local Host

macOS、Windows 和 Android 都运行各自的本地 Host。每个 Host 拥有自己的 SQLite、模型档案、Python
领域内核、审计记录和 `World → WorldVersion → Run → RunState → Turn[]` 聚合；不存在“启动为
Host / 远程客户端”的选择。

- **macOS / Windows：** Tauri 启动时自动启动其仅限本机的 Python sidecar；UI 不显示 LAN、配对、
  device scope 或启动模式选择。
- **Android：** Flutter 通过一个 Android runtime bridge 调用嵌入的 CPython 领域内核和本机 SQLite；
  不向本机或局域网暴露 FastAPI listener。
- **模型：** Local Host 直接调用完整 `ModelProfile`。`ollama`、`lm_studio` 和 `openai_compat`
  仍是完整协议配置，绝不只切换模型名。云模型、同一网络中用户指定的 Ollama/LM Studio endpoint
  与未来手机端模型运行时都是 provider，不构成 DZMM PC 中转。

### 2. 共用 Python core，不复制规则系统

将 `dzmm_vnext` 拆为三个边界：

```text
contracts + dzmm_vnext.core
  WorldDefinition / RunState / command allowlist / composer /
  turn coordinator / lifecycle / content / model protocol validation
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
desktop sidecar      Android runtime     test harness
SQLite + loopback    bridge + SQLite     temporary SQLite
```

`FastAPI`、mDNS、pairing、remote route 和 Tauri IPC 属于 adapter，不进入 `core`。Android bridge
只接受版本化用户意图（compose、choice、rollback、archive 等）并返回 projection/event；LLM 的
候选输出仍须经 core 的受限解析、command 白名单、事务和审计后才成为状态。

### 3. 本地数据、密钥与跨设备边界

- Android 数据库只存在应用私有目录；模型密钥只存在 Android Keystore 加密的 write-only storage。
  API、日志、诊断与导出一律不得读回密钥。
- `host_instance_id` 与 `execution_owner` 是本地审计元数据，而非网络身份。每个 World/Run 在创建后
  固定归属当前 Local Host；不允许两台设备对同一 Run 并发写入。
- 跨设备能力采用显式、用户确认的 **export / import / clone**：可导出世界书、角色卡、WorldVersion
  和可选的只读 Run 历史；导入为目标设备上的新 aggregate/Run ID。P0 不做自动同步、冲突合并、
  后台复制、LAN 发现或云账户。

### 4. 产品信息架构不再包含远程控制面

Android 固定为 **世界、创作、游玩、模型、设置** 五入口。其设置解释“本机保存、本机执行”，不再
出现 Host 地址、QR、配对、scope、设备授权或 LAN 开关。Mac/Windows 的设置保留模型、数据、诊断
与主题，但移除“手机联动”和“局域网玩法”。

## Options considered

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 每端 Local Host + 共享 Python core | 采用 | 手机真正独立，同时保留 Python 为唯一状态裁判。 |
| 保留 PC Host，手机只直连 PC 的模型 endpoint | 拒绝 | 手机仍依赖 PC 的 DB/规则/可用性，不是独立终端。 |
| Flutter/Dart 直接调用 LLM 并在客户端修改状态 | 拒绝 | 规则与状态会分叉，无法复用既有 Python 审计、回滚与 command 约束。 |
| Android 另写一套 Dart 规则引擎 | 拒绝 | 两套状态机必然漂移，无法证明跨端规则一致性。 |
| 手机上的本地大模型作为首个 P0 | 后置 | 先解决正确的本地 Host 与 provider 直连；模型资产、热管理、设备兼容与后台存活是独立工程问题。 |

## Consequences

- ADR-006（发现/配对）和 ADR-007（已配对完整远程客户端）被本 ADR 取代，不再是 vNext 实施或成熟度
  依据。remote API、pairing、mDNS、QR、scope 与 LAN 代码已从 vNext 正式代码、测试、配置和发布脚本删除。
- 现有 Mac 打包本地 sidecar、schema v3、compose、受限 choice、rollback 和 AI 草案的核心证据可继续
  作为 desktop/core 边界的输入；Android remote/emulator/Redmi 证据不能证明 Android Local Host。
- Android 打包必须先完成嵌入 CPython、SQLite、关键纯 Python 依赖和模型流式取消的实体 spike；在该
  spike 通过前，不承诺任意 Python wheel 都能在 Android 上运行。
- Mac/Windows 始终本地启动，不新增模式开关；在本次 clean-slate 范围中直接删除远程模式 UI/API，
  不维护旧数据或网络客户端兼容。

## Action items

1. [~] 已建立 `dzmm_vnext.core` façade，并将 `TurnCommand` 应用引擎移入共享 core；仍需将存储/回合编排真正移出 FastAPI adapter，并补 core replay 测试。
2. [~] 已完成 Chaquopy/Python 3.11、共享 core、本机 SQLite 聚合和 Flutter bridge build spike；仍需 compose 雾港、三 choice、rollback、
   force-stop/reopen，全部通过 Flutter UI 取证。
3. [~] Android ModelProfile/Probe/AI draft/turn 操作已接入 runtime bridge；仍需在设备上实测 direct provider
   空输出、HTTP 200 error body、超时/取消和不落半回合恢复。
4. [~] Android Local Host UI 已实现结构化审阅与本机原子 compose；仍需设备上的三 choice、结局、rollback
   和 force-stop/reopen 证据。
5. [~] 已完成 desktop/backend/Android 的 v1 world export/import 与 Run clone slice；仍需 Android 损坏包零写入和跨端 round-trip 证据。
6. [ ] 按新的 Local Host 成熟度矩阵重新取证；旧 remote 分数不转移。

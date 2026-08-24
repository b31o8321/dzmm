# ADR-009：共享跨端体验契约，保留平台原生前端

**状态：** Accepted  
**日期：** 2026-08-19  
**决策人：** DZMM 产品负责人、工程负责人

## Context

当前 desktop 是 Vue/Tauri 的单体 `App.vue`，Android 是 Flutter 的单体 `main.dart`。两端不但布局不同，
还分别拥有 Host/Remote 投影、错误文案、状态编排和页面入口。功能每增加一次，两个产品会产生不同的
“创建—模型—游玩—恢复”语义。

ADR-008 将所有平台改为 Local Host 后，Android 不再需要配对、Host、scope 与 LAN 页面；继续在现有
两个单体上增量叠加，只会把已过时的远程控制面和新本地终端混在一起。

## Decision

### 1. 一份体验契约，两个原生 renderer

不将 Vue 组件编译给 Flutter，也不把 Flutter 页面嵌进 Tauri。两端保留适合平台的渲染和交互模型，
但共享版本化的 **Experience Contract**：信息架构、页面状态、可见动作、错误恢复、文案 key、
accessibility label 与验收旅程。

```text
contracts/
  WorldDefinition / RunState / TurnCommand       ← 领域事实
  LocalHostPort                                  ← 受限前端动作
  Experience Contract                            ← 页面、状态、恢复、a11y key
  Design Tokens                                  ← theme/spacing/type/motion tokens
                  │
          ┌───────┴────────┐
          │                │
Vue / Tauri shell     Flutter / Material shell
desktop-adaptive       mobile-adaptive
```

UI 只调用 `LocalHostPort`。desktop adapter 通过本机 sidecar IPC/loopback 调用 Python core；Android
adapter 通过 runtime bridge 调用嵌入 Python core。页面不得知道 FastAPI、remote bearer、pairing、scope
或 provider secret。

### 2. 固定的产品导航和可适配布局

所有平台均有同一语义入口：**世界、创作、游玩、模型、设置**。`Host`、连接、扫码、配对、scope、
LAN 与启动方式从正式产品 UI 中移除。

| 体验契约 | 桌面 ≥ 960px | 手机 ≤ 600dp | 共同结果 |
| --- | --- | --- | --- |
| 世界 | 左侧世界列表 + 右侧详情 | 列表 → 全屏详情 | 查看版本/Run/资产、导入/导出/归档。 |
| 创作 | 分栏 brief / 草案审阅 | 逐步卡片与底部确认条 | 编辑后必须重新校验；确认前零写入。 |
| 游玩 | 状态栏 + 叙事记录 + choice 区 | 沉浸全屏 + 可收起状态抽屉 | choice、关系原因、ending、rollback 语义一致。 |
| 模型 | 档案表格与 inline probe | 档案卡片与底部编辑 sheet | `type/base_url/model_name` 作为完整档案，直接 Probe。 |
| 设置 | 数据、诊断、主题、导出 | 本机数据、主题、导出 | 只显示当前设备的本地事实。 |

桌面可用键盘快捷键、分栏和信息密度；手机采用底部导航、单列卡片、底部 sheet 和拇指可达操作。
“适配”要求相同任务与恢复能力，而非像素级复制。

### 3. 共享状态、错误与可访问性语义

Experience Contract 为每个 use case 固化 `loading / empty / success / validation_error / provider_error /
conflict / cancelled / restored` 等状态，以及 action/result 文案 key。`422` 必须映射到字段与修复建议；
provider 的空输出、HTTP 200 error body、超时和取消必须说明“未提交状态”；rollback/reopen 必须从
Local Host snapshot 重新 materialize。

每项 UI action 同时定义 stable test ID、中文 a11y label、键盘路径（desktop）和 TalkBack 顺序（Android）。
视觉主题延续 `fog`、`paper`、`amber` 三个相同 ID，但由同一语义 token 文件生成 CSS variables 与
Flutter `ColorScheme`，不以硬编码颜色复制主题。

### 4. 模块化迁移，而非重写视觉后再接功能

先从每端单体中抽出 shell、route/screen、view-model/controller、`LocalHostPort` adapter 和
design-token adapter。领域 schema、Python core 与 user journey 不随 UI 层重写。每迁移一个入口，
用同一 Experience Contract 的 fixture、截图和恢复测试证明 parity；未迁移的 remote 页面不与新
Local Host 页面混排。

## Options considered

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 共享体验契约 + token + 平台原生 Vue/Flutter | 采用 | 共享产品语义且保留桌面效率、触控可用性与原生无障碍。 |
| 用响应式 Vue WebView 替代 Flutter | 拒绝 | 可短期复用组件，但牺牲 Android 系统输入、文件、Keystore、性能和原生可访问性。 |
| 继续两个独立页面/接口模型 | 拒绝 | Local Host 迁移后会持续产生行为、错误和验收漂移。 |
| 抽一套跨平台 UI 组件库 | 拒绝 | Vue 与 Flutter 不能有低成本共享的渲染组件；会把“共享”误解成视觉最低公分母。 |

## Consequences

- 现有 `App.vue` 与 `main.dart` 是过渡入口，不再新增跨页面业务编排；新能力先进入 shared
  Experience Contract/LocalHostPort，再由两端各自渲染。当前两端已删除 remote view model，Android
  的 runtime adapter 仍等待 shared core 嵌入。
- `RemoteWorld*`、Host discovery、pairing、scope 与 remote API 类型不进入新的 UI domain model；
  它们已随 ADR-008 的 remote 删除阶段清理。
- “主题一致”由 token 及截图验证；不把已存在的三主题名称当作跨端视觉一致的证据。
- 成熟度矩阵新增跨端体验一致性验收；构建成功或组件复用率本身不计分。

## Action items

1. [~] 已发布 `experience_contract.json`、`design_tokens.json` 和 typed operation façade；仍需 fixture/codegen。
2. [~] 已定义 `LocalHostPort` 的 typed operations 和 desktop/Android adapters；Android 已接入 embedded core，仍需设备证据。
3. [ ] 先迁移世界中心、模型 profile/probe、结构化 AI 草案、沉浸游玩四个 P0 流程。
4. [ ] 以 390×844、768×1024、1440×900 截图和 TalkBack/keyboard 实测验证同一 journey。
5. [~] 旧 Host/配对页面、remote view model 和相关测试已删除；仍需三端截图与恢复证据重建矩阵。

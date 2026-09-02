# DZMM Cutover Release Handoff

当前候选：`feature/dzmm-vnext@837ae85`（GitHub Draft PR #2）

## 已完成

- Android API 36 本地 release：新世界、10 回合、正式结局、同世界新 Run、强制停止恢复。
- macOS sidecar/API、本地 sidecar 与前端/Tauri 构建。
- 旧版归档 tag：`dzmm-legacy-v0.16.0-2026-08-30`，指向 `main@df38037`。
- 临时运行时数据库备份/恢复演练。
- 首个替换版本“不自动迁移旧版数据库”策略及玩家提示。

## 授权后已执行

1. 已将 feature 分支推送到 `origin`，并创建 [Draft PR #2](https://github.com/b31o8321/dzmm/pull/2)。
2. 已从候选 head 运行 release workflow `33314492033`；macOS arm64 与 Windows x64 构建和 artifact smoke 成功。
3. PR backend-ci 与 E2E smoke 均通过；E2E 的 Linux Tauri 构建依赖已固定在 workflow 中。
4. PC LM Studio `huihui-ai_qwen3-14b-abliterated` 已完成真实 Probe 与隔离库 AI 草案验证；
   弱模型 JSON 格式兼容、角色卡与额外 NPC 的审阅去重、地点引用一致性校验已纳入当前候选；
   本机 `qwen2.5:7b` 也已在打包 macOS 应用完成 Probe 与草案审阅复测。
5. 最新 release workflow `33526060462`（head `da4e87d`）已通过 macOS arm64 与 Windows x64 的
   测试、sidecar/Tauri 打包及 artifact smoke；Windows SQLite 文件句柄锁定问题已通过隔离恢复目录修复。
6. 在重建的 macOS 包中，PC Qwen3 14B 通过结构化 `json_schema` 约束完成 20.7 秒草案审阅，
   确认前未写入存档；证据见 `vnext/eval/evidence/phase179-pc-qwen-structured-draft.json`。
7. 最新提交 `97f04cd` 的 release workflow `33641453572` 已全绿，macOS arm64 与 Windows x64
   的测试、sidecar/Tauri 打包、artifact smoke 和 Windows sidecar 健康检查均通过。

## 尚未完成的验收

1. 在 Windows 原生环境安装 NSIS 包，完成模型配置、创建世界、游玩、结局和新 Run。
2. 在 macOS 获得 Computer Use 权限后，完成同一套安装包可见流程；当前只能证明窗口可见，不能证明完整点击旅程。
3. 保存两端安装后截图/日志，更新 ADR-010 gates；完成前保持 Draft，不合并、不删除旧版。

## 最终 cutover

只有上面两端 GUI gate 都通过后，才可以：

- 从当前候选创建干净 cutover 分支；
- 统一 `DZMM Next`、`dzmm_vnext`、sidecar、默认目录和包标识；
- 运行全量测试与新用户目录回归；
- 合入 `main`；
- 将旧版保留为归档 tag，不再进入默认构建；确认删除清单后再移除旧版实现。

## 当前禁止

- 未经授权不要 push 或触发远端 release workflow。
- 不要在 GUI gate 未通过前合并 `main` 或删除旧版。
- 不要把“进程存在”“sidecar health”当作玩家 GUI 验收。

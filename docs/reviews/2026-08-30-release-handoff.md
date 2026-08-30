# DZMM Cutover Release Handoff

当前候选：`feature/dzmm-vnext@606f6b3`

## 已完成

- Android API 36 本地 release：新世界、10 回合、正式结局、同世界新 Run、强制停止恢复。
- macOS sidecar/API、本地 sidecar 与前端/Tauri 构建。
- 旧版归档 tag：`dzmm-legacy-v0.16.0-2026-08-30`，指向 `main@df38037`。
- 临时运行时数据库备份/恢复演练。
- 首个替换版本“不自动迁移旧版数据库”策略及玩家提示。

## 授权后执行

1. 将当前 feature 分支推送到 `origin`。
2. 等待并检查当前 head 的 release workflow；不得复用 `7a25ec8` 的旧产物。
3. 在 Windows 原生环境安装 NSIS 包，完成模型配置、创建世界、游玩、结局和新 Run。
4. 在 macOS 授权 GUI 自动化后，完成同一套安装包可见流程。
5. 保存两端截图/日志和 workflow URL，更新 ADR-010 gates。

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


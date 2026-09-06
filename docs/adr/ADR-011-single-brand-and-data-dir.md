# ADR-011: 单一产品命名与数据目录统一（cutover 前置）

**Status:** Accepted
**Date:** 2026-09-05
**Deciders:** 产品与维护者
**关联:** [ADR-010 单一 DZMM 受控替换](ADR-010-single-dzmm-cutover.md)、[执行计划 M3](../superpowers/plans/2026-09-05-vnext-absorb-and-cutover.md)

## Context

vNext 分支内部仍使用预览命名：Python 包 `dzmm_vnext`、发行名 `dzmm-next-backend`、
健康标识 `app=dzmm-next`、默认数据目录 `~/.dzmm-vnext-v3/`（后端裸跑与 Android 内嵌
核心）与 `app_data_dir()/v3`（Tauri 桌面）、环境变量 `DZMM_NEXT_*`、桌面持久化键
`dzmm-next:*`、Android 应用 ID `local.dzmm.dzmm_next_mobile`。旧版 `main` 的产品
目录是 `~/.dzmm/dzmm.db`。两条命名线并存会让 cutover 后的包、路径和文档继续分叉。

## Decision

产品统一为 **DZMM**，代码与数据边界按下表切换：

| 维度 | 旧（预览） | 新（统一） |
|---|---|---|
| Python 包 / 模块 | `dzmm_vnext` | `dzmm` |
| 后端发行名 / 二进制 | `dzmm-next-backend` | `dzmm-backend` |
| /health 应用标识 | `app=dzmm-next` | `app=dzmm` |
| 默认数据目录（后端裸跑 / Android 内嵌） | `~/.dzmm-vnext-v3/` | `~/.dzmm/` |
| 数据库文件 | `dzmm-next.db` | `dzmm-v3.db` |
| 环境变量 | `DZMM_NEXT_DATA_DIR` / `DZMM_NEXT_PORT` / `DZMM_NEXT_BACKEND_PATH` | `DZMM_DATA_DIR` / `DZMM_PORT` / `DZMM_BACKEND_PATH` |
| Tauri 标识 / 桌面数据目录 | `local.dzmm.next` + `app_data_dir()/v3` | `local.dzmm` + `app_data_dir()/data` |
| 桌面持久化键 | `dzmm-next:*` | `dzmm:*` |
| Android 应用 ID / Gradle 包 | `local.dzmm.dzmm_next_mobile` | `local.dzmm.mobile` |
| 品牌串 | “DZMM vNext”/“DZMM Next”/“Next 数据” | “DZMM” |

### 为什么数据库文件叫 `dzmm-v3.db`

旧版占用 `~/.dzmm/dzmm.db`；目录统一后两者必然同目录，文件名必须区分以免任何
代码路径误开旧库。`dzmm-v3.db` 明确表达“schema v3 这一代”的存档，与
`run_state.schema_version = 3` 对齐；未来 schema v4 若提供官方迁移工具，可连同
迁移一起重命名，属另一个 ADR。

### 迁移边界（不自动迁移）

- 切换后**不复制、不合并、不改写**任何既有数据：旧版 `~/.dzmm/dzmm.db`、预览期
  `~/.dzmm-vnext-v3/dzmm-next.db`、桌面 `app_data_dir()/v3` 全部原样保留。
- 首次以新命名启动时在默认位置创建全新 `dzmm-v3.db`；旧预览存档需要带入时，只能
  走既有的世界包 / 旅程快照导出导入。
- 应用内“旧版 DZMM 存档不会自动迁移”的边界提示保留并更新措辞。

### 已知影响

- 本机预览期的桌面持久化键与数据目录将“看起来清空”（数据仍在旧目录，未删除）。
- Android 需以新 applicationId 重新安装（旧 app 图标保留旧数据，可手动卸载）。
- 历史证据 JSON（`eval/evidence/phase*.json`）保留原命名，作为历史记录不改写。

## Options Considered

| 方案 | 评估 | 结论 |
|---|---|---|
| A. 保留 `dzmm-next` 命名直到 cutover 后再改 | 双命名线继续污染文档与包名，cutover PR 更大 | 否决 |
| B. 现在统一（本 ADR） | 一次性完成 ADR-010 第 3 步的命名部分，cutover 合入只剩删旧版 | **采用** |
| C. 数据库沿用 `dzmm-next.db` 文件名 | 同目录下与旧库只差品牌后缀，误读风险与 grep 噪音大 | 否决 |

## Consequences

- cutover（ADR-010 第 5 步）剩余动作收敛为：删旧版 `backend/`+`frontend/`、归档
  tag 复核、合入 main——均需人工确认。
- 构建脚本必须隔离继承的 `PYTHONPATH`（本仓库同时存在旧版 `backend/src/dzmm` 与
  新 `vnext/backend/src/dzmm`，同名包不可让旧路径抢先解析）。

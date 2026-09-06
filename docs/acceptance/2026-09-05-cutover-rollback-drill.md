# Cutover 回滚演练：从归档 tag 恢复旧版 DZMM

日期：2026-09-05
执行分支：`feature/dzmm-vnext`（工作树 `.worktrees/dzmm-vnext`）
归档 tag：`dzmm-legacy-v0.16.0-2026-08-30`（指向 `df38037`，与 main 当前 HEAD 一致）
结论：**PASS**——旧版可从归档 tag 完整恢复并启动，健康检查返回 v0.16.0，全程未触碰真实用户数据。

## 演练步骤（可复现）

1. 从归档 tag 建立一次性 detached 工作树（不占用任何日常分支）：

   ```bash
   cd /Users/norman/development/dzmm
   git worktree add --detach .worktrees/legacy-rollback-drill dzmm-legacy-v0.16.0-2026-08-30
   ```

2. 以隔离的 `HOME` 启动旧版后端。旧版 `dzmm/config.py` 将数据目录硬编码为
   `Path.home() / ".dzmm"`，因此覆盖 `HOME` 即可获得全新数据目录，**绝不指向真实
   `~/.dzmm/dzmm.db`**；依赖复用主检出已装好的 `backend/.venv`：

   ```bash
   DRILL_HOME=$(mktemp -d /tmp/legacy-rollback-drill.XXXXXX)
   cd .worktrees/legacy-rollback-drill/backend
   HOME="$DRILL_HOME" PYTHONPATH="$PWD/src" DZMM_PORT=8799 \
     /Users/norman/development/dzmm/backend/.venv/bin/python scripts/run_dev.py
   ```

3. 健康检查：

   ```bash
   curl -s http://127.0.0.1:8799/health
   # {"ok":true,"status":"ok","version":"0.16.0"}
   ```

4. 确认隔离生效：`$DRILL_HOME/.dzmm/` 下生成了全新 `dzmm.db`、`assets/`、
   `chroma_npc/`、`dzmm.log`；真实 `~/.dzmm/dzmm.db`（mtime 2026-07-31）与
   `~/.dzmm-vnext-v3/dzmm-next.db`（mtime 2026-08-30）均未被修改。

5. 清理：终止演练进程，`git worktree remove .worktrees/legacy-rollback-drill`。

## 回滚语义（与 ADR-010 一致）

- 旧版代码始终可从 `dzmm-legacy-v0.16.0-2026-08-30` tag 恢复，不依赖任何工作树存活。
- 旧版与 vNext 数据目录互不覆盖：旧版 `~/.dzmm/dzmm.db`、vNext
  `~/.dzmm-vnext-v3/dzmm-next.db`，cutover 后 vNext 统一回 `~/.dzmm/` 时旧库文件
  按既定决策原样保留、不读不写。
- 本演练只验证"恢复 + 启动 + 健康检查"；旧版玩家数据继续游玩不属于 cutover 回滚
  范围（ADR-010 已定不自动迁移，玩家可经导出/导入带内容）。

## 已知边界

- 演练仅启动了后端 sidecar 等价物（uvicorn app），未启动 Tauri 桌面壳；旧版桌面
  壳如需完整回滚，仍按 v0.16.0 tag 的打包流程重打（Phase 165 源码恢复演练已覆盖）。

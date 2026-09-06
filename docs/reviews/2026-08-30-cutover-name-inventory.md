# DZMM 单一产品命名与数据边界清单（2026-08-30）

## 结论

当前 vNext 可以作为替换候选，但还不能直接把所有内部标识改成 `DZMM`：
`dzmm-next` 仍承担 sidecar 健康检查和数据库 app 标识，`dzmm_vnext` 是 Python
导入包名，`.dzmm-vnext-v3` 是隔离数据目录。它们在 cutover 前必须先完成迁移/回滚
设计，否则会把旧数据、升级数据和全新安装混在一起。

## 当前引用分类

| 类别 | 当前标识 | 位置/用途 | cutover 处理 | 门槛 |
|---|---|---|---|---|
| 用户可见名称 | `DZMM` | Tauri `productName`、应用标题 | 保持并覆盖所有首屏/文案 | 已基本完成 |
| 健康协议 | `dzmm-next` | `/health` 的 `app` 字段、Host 探测 | 迁移期同时接受旧值，最终统一为 `dzmm` | macOS/Windows GUI 通过后 |
| Python 包 | `dzmm_vnext` | backend、Android embedded、评估脚本 | 最后一次性改包名并保留兼容导入层 | cutover 分支 |
| 数据目录 | `~/.dzmm-vnext-v3` | vNext 默认 SQLite 数据 | 先实现显式迁移/不迁移提示，再切换到 `~/.dzmm` | 迁移方案确认 |
| 数据库文件 | `dzmm-next.db` | vNext SQLite | 迁移工具负责复制/转换；禁止静默覆盖旧库 | 迁移测试 |
| sidecar 文件名 | `dzmm-next-backend` | Tauri 打包资源与启动器 | 与最终产品名统一，旧文件只留归档产物 | Windows/macOS 包验收 |
| 包标识 | `local.dzmm.next`、`@dzmm-next/desktop` | Tauri/Cargo/npm | 设计稳定升级标识后再改，避免系统把它当新应用 | 发布决策 |
| 本地存储键 | `dzmm-next-*` | active/pending/theme | 增加一次性 key 迁移或明确清理策略 | 数据边界测试 |
| 诊断/测试文本 | `dzmm-next`、`dzmm_vnext` | diagnostics、测试断言、评估脚本 | 用户可见输出统一；内部测试可在重命名提交中同步 | 命名收敛提交 |

## 建议顺序

1. 先完成 macOS 可见 GUI 和 Windows 安装后 GUI 验收，冻结发布标识。
2. 编写迁移探测：检测 `~/.dzmm/dzmm.db`、`~/.dzmm-vnext-v3/dzmm-next.db`，只读展示
   可迁移数量和风险；用户确认后才复制，失败保留源库不改写。
3. 建立旧版归档 tag 和回滚说明，再在独立 cutover 分支统一包名、sidecar、健康协议、
   Python 包和默认目录。
4. 用全新用户目录完成创建→游玩→结局→新 Run，并用迁移用户目录完成只读回读；两者
   都通过后才合入 `main` 并删除旧版默认构建路径。

## 当前禁止事项

- 不在 `main` 上直接删除旧版代码。
- 不把 `~/.dzmm` 静默改写为 vNext 数据库。
- 不仅改显示名称而忽略 `/health`、sidecar 文件名、包标识和存储键。


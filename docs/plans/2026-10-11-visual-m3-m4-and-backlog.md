# v1.11.0 后续计划：视觉层 M3/M4 + 积压路线图

日期：2026-10-11 ｜ 状态：M1+M2 已完成（见
`2026-10-09-comfyui-visual-plan.md` 第七节里程碑状态）｜ 本文档 = 下一步执行序

## 当前位置

- 视觉层后端闭环已合入 main 并推送：M1 `269396d`、M2 `2ec0d81`、文档 `374e84b`；
  backend 270 测试全绿（含 10 个视觉 API 测试，ComfyUI HTTP 边界 mock）。
- API 面已就绪：`/api/v2/visual/settings|status|generate|tasks/{id}|media`、
  `/api/v2/runs/{id}/turns/{seq}:illustration`、`/api/v2/media/{world_id}/{file}`。
- 失败标记策略：`visual_media` 注册表状态即真相（主体无 done 行 = 可生成/重摇），
  不回写 world definition。

## M3 UI 挂载（约 1-1.5 迭代日）← 下一步

桌面 Vue 与手机 Flutter 同源交互（方案第五节）：

| 挂载点 | 行为 |
|---|---|
| 设置页「视觉」分区 | 地址/开关/风格前缀/负面词/工作流覆盖/并发/自动范围 + 测试连接（读 /visual/status） |
| 角色卡/地点卡 | 有图显图；无图或 failed 显示「生成 / 重摇 🎲」（generate 重复调用即重摇） |
| 游玩页叙事卡 | 顶部 16:9 插画横幅；生成中占位骨架；点击放大；失败静默不显示 |
| 世界列表 | 封面缩略图（kind=cover 的最新 done 行） |
| 创建页草案审阅 | 「生成立绘」开关（默认开；视觉关闭时隐藏） |

验证标准：`npm test && npm run build`、`flutter test`；双端从用户入口走查
生成→展示→重摇→失败→恢复→刷新重进（媒体 URL 直连）。

## M4 真机联调（约 0.5 迭代日）

1. PC ComfyUI 以 `--listen 0.0.0.0` 暴露局域网
2. 手机视觉设置填 PC 局域网 IP → 测试连接
3. 真机端到端：创建世界 → 批量立绘 → 回合插画 → 重摇；观察 ComfyUI 与
   Ollama 的 GPU 争抢（并发 1 + 回合结算后错峰已缓解）
4. 前置输入（用户提供，可选）：ComfyUI 导出的 API 格式工作流 JSON +
   checkpoint 名；不提供则先用内置 SDXL txt2img/img2img 模板直跑

## 积压清单（视觉层之外，按优先级）

- **P1 世界书/人物卡导入**：SillyTavern 格式 preview/import API 已有
  （`/api/v2/content/sillytavern:*`），缺手机入口与「导入→交给 LLM 生成世界」
  的玩法闭环。
- **P1 桌面端补齐回合操作入口**：use_item / skill_check / 任务面板，与手机对齐
  （v1.10.0 手机侧已落地，桌面缺入口）。
- **P2 隧道配对**：外网远程玩 PC 后端，复用 android-remote-client 分支配对协议。
- **P2 种子可编辑**：随机脑洞生成的种子可改后再生。
- **P2 流式叙事**：手机独立模式端上逐段显示；跨 HTTP/嵌入两层改造，改动面大。
- **P3 IPAdapter FaceID**：角色一致性增强，需 ComfyUI 装节点，基准图链稳定后评估。
- **P3 LLM 外貌卡**：portrait appearance 中文卡由 LLM 产出（当前降级用
  npc description / heroes profile 拼接）。
- **暂缓 图生视频**：明确不做，待图链稳定后重新评估切入点。

## 风险与依赖

- M3 的前端契约以 `GET /api/v2/visual/media?world_id=` 为唯一发现入口，
  媒体文件直连 `/api/v2/media/{world_id}/{file}`。
- M4 GPU 争抢：生图时 Ollama 排队属预期；极端场景用户可关「场景插画」。
- 磁盘：PNG 1-2MB/张；`~/.dzmm/media/<world_id>/` 整目录可删可导出（M3 可加入口）。

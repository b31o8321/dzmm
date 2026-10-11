# DZMM 活跃交付索引

## 2026-10-03 手机 App 六小时对抗成熟度冲刺（终态）

- 分支 main @ 1009530（已推送）；flutter 38 绿 / analyze 清洁 / backend 254 绿
- T0 对照矩阵：eval/mobile-maturity/gap-matrix.{json,md}——手机唯一落后项=战斗入口；use_item/技能/任务两端共缺
- T1 敌意轮：adversarial-r1-report.json——4 场景新回归测试（ADV1-4）全过；真机项受阻降级 widget 覆盖
- T2 走查：usability-walkthrough.md——模板路径不可见（P1）、模拟器地址噪音（P2）
- T3 修复：1009530——游玩页新增战斗卡/任务面板/检定与物品面板/反馈行/maxLength；
  后端 run snapshot 保留 outcomes + presentation 下发 skills/quests/resource_effects（d678db6）
- T4 复测：adversarial-r2-report.json——T1 场景 5 过 1 受阻（无真机）；T0 四缺口全闭
- 未修遗留：流式叙事（P2）、选项匹配提示（P2）、创作草案进程级持久化（P1 独立工程）、
  模板路径文案（P1）、真机装机复测（APK 就绪：adb install -r -t mobile/build/app/outputs/flutter-apk/app-release.apk）

## 2026-10-11 ComfyUI 视觉层 v1.11.0 — M1+M2 后端闭环（进行中）

- 决策已定（29a9941）：ComfyUI 独立项目，DZMM 仅作 API 消费者；视频不做；风格可设置
- M1 管线+设置 ✅ 269396d：VisualSettings JSON 持久化 + VisualService（并发1队列/to_thread）
  + visual_media 表（alembic 0016）+ 六端点（settings/status/generate/tasks/media 服务）
  + 路径穿越防护；backend 277 全绿
- M2 触发闭环 ✅ 2ec0d81：after_compose 批量（封面+主角+≤4立绘+≤3场景，auto_* 门控）
  + scene_for_turn（在场 NPC 基准立绘→img2img 基准图链）+ 手动插画端点
  + turns/choices/stream 三入口挂接（幂等门控）+ heroes 主角降级 + media 列表 API
  - 失败标记策略：registry 状态即真相（无 done 行=可重摇），不回写 definition
- 待办 M3：UI 挂载（桌面 Vue + 手机 Flutter：角色卡图/游玩页插画横幅/列表封面/设置页视觉分区）
- 待办 M4：真机联调——需用户 ComfyUI --listen + 工作流 JSON 或先用内置 SDXL 模板
- 未验证范围：真实 ComfyUI 端到端生图（mock HTTP 边界验证）；回合自动触发的在线联调

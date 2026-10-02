# T0 桌面-移动功能对照矩阵（2026-10-03，main @ e19f8e3）

证据源：desktop/src/components/PlayScene.vue（234 行全文）+ desktop/src/App.vue
（回合命令构成 1370/1446 行、attackTarget 1348 行）；mobile/lib/pages/play_page.dart
（全文）+ main.dart。逐项核对，无「未知」项。

## 结论速览

- **手机唯一落后桌面的交互能力：战斗攻击入口（P0）**——本轮 v1.9 引擎 P0 的
  攻击在手机完全无 UI，玩家无法触发战斗。
- **use_item / skill_check / 任务列表是两端共同的缺口**：引擎能力已上线，
  桌面同样没有入口。本轮在手机侧补齐（补入口的成本低、收益直接），桌面侧
  记为后续项。
- 其余（选项/输入/移动/回滚/取消/重试/结局回顾/物品/关系/循环 HUD）两端对齐，
  手机 LoopHud（倒计时条）反而更完整。
- 体验弱化（非缺失）：手机回合为阻塞式（无流式叙事增量），已有操作状态卡兜底。

## 优先级队列（进 T3 修复轮）

| 优先级 | 项 | 动作 |
|---|---|---|
| P0 | 手机战斗攻击入口 + 战斗反馈卡 | play_page 增加 combat deck（目标/HP/倒下态/空目标提示），attack 命令走既有 playTurn 通道，d20 结果以卡/条呈现 |
| P1 | 任务列表/进度 | 游玩页侧栏或 HUD 区显示 quests 状态（active/pending/completed/expired）+ 完成时反馈 |
| P1 | use_item 入口 | 物品栏条目带「使用」按钮（仅 on_use 资源），结果走 outcomes 反馈 |
| P1 | skill_check 入口 | 技能下拉（payload.skills.available）+ DC 输入 + 掷骰按钮 |
| P1 | 创作草案进程级持久化 | 草稿/表单字段写 session_store，启动时恢复 |
| P2 | 流式叙事、选项匹配提示 | 记录，时间允许再做 |

## 桌面侧欠账（本轮不修，记录）

- use_item / skill_check / 任务列表入口（桌面同样没有）

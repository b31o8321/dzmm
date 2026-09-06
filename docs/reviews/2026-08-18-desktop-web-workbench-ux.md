# DZMM vNext 桌面 / Web 工作台 UX 评审

## 结论

原界面把本机诊断、模型档案和主题混在叙事主线中；模型档案又只在 AI 创作表单内临时出现。用户在“创建世界”或“继续游玩”时被运行时管理控件打断，也无法在开始创作前确认模型是否真正可用。

重构把这些能力收敛为独立的 **设置** 工作台。世界中心、创作和游玩保持叙事主线；设置只处理本机服务、模型、主题和显式导入导出。

## 信息架构

```text
DZMM Next
├── 世界
│   ├── 世界中心
│   ├── 手动 / AI 创作
│   └── 确认 / 游玩
└── 设置
    ├── 本机服务：SQLite 状态、无隐私诊断、恢复
    ├── 本地模型：完整档案、直接 Probe、协议失败提示
    ├── 数据携带：世界包导出、Run 快照导出、导入/克隆
    └── 外观：雾夜、纸页、琥珀
```

## 设计原则

- **先给下一步，后给术语。** “本机运行中”先解释当前事实；版本、aggregate 等术语只在需要恢复或携带时出现。
- **模型档案是一个整体。** 只允许协议、Base URL、模型名作为同一档案保存；每个档案可由 Host 真实 Probe，HTTP 200 但协议/内容不合法也显示未通过。
- **携带能力不打断创作。** 导入、导出和 Run 克隆只在设置或世界中心的明确动作中出现，不自动同步。
- **主题是气氛，不是状态。** 三主题仅保存在当前设备展示层，不改 World、WorldVersion、Run 或 RunState。

## 本轮实现与证据

- 顶部只有“世界 / 设置”与本机就绪状态；不再固定显示连接、配对或网络控制。
- 设置页在 1600×900 和 390×844 下无横向溢出。
- 当前隔离 Host 上，桌面模型页已真实 Probe `OllamaUX2 / qwen2.5:7b`，结果为 `protocol response contains content`。
- `npm run build` 和 `CI=true npm run tauri:build -- --debug` 都通过；debug `.app` 与 DMG 已生成。
- 图片见 `vnext/eval/evidence/screens/phase50-desktop-settings-ux/`；结构化记录见 `phase50-desktop-settings-workbench-interim.json`。

这只是 source Web 预览与隔离 Host 证据，尚未替代打包 Mac `.app` 的 WebView、无障碍或 Windows 验收。AI 草案的结构化审阅与字段级修复仍是独立 P0，不因本次设置重构而关闭。

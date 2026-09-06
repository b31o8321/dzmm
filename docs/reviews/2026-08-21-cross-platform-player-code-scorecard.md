# DZMM vNext 三端玩家能力与代码质量评分

日期：2026-08-21  
状态：实现后暂定 / 发布门槛未通过  
评分原则：功能分只采信该平台当前可获得的玩家入口证据；代码分独立评价干净、通用、复用、低耦合，不能与功能分互相补偿。

## 结论

| 平台 | 玩家功能 | 代码质量 | 证据强度 | 发布判断 |
| --- | ---: | ---: | --- | --- |
| macOS | 82/100 | 85/100 | 新鲜隔离数据完成创建 World、首局开场、返回 World、已有/新 Run 真实浏览器回归；`.app` 包内 Host 完成 30 回合退出/重启恢复；桌面导入/复制旅程已持久化 active Run；自由行动和故事选择均消费 SSE；通知 live-region 回归已补回 | 未通过：当前 macOS 26.3.1 从 DMG 启动时 Host 正常但是 0 个 WindowServer 窗口，安装包玩家入口为 P0 fail |
| Windows | 66/100 | 85/100 | 与 macOS 共享 Vue/Tauri/FastAPI；release workflow 有 Windows job；720px 响应式回归通过 | 未通过：没有 Windows 原生构建、安装和 WebView 玩家旅程证据 |
| Android | 77/100 | 85/100 | 23 个 Flutter tests、analyze、debug APK；嵌入 Python/runtime 自动化，模型操作和模型 Probe 已移出 UI 线程，并显示阶段/耗时；本地 API 36 模拟器通过 Qwen 7B 从零创建世界、完成 3 回合正式结局并开始新 Run；草案确认前展示地点/NPC/势力/事件摘要，叙事上下文不再暴露内部 ID | 未通过：没有物理设备 A-F、TalkBack 和安装包 30 回合恢复证据 |

当前产品玩家可玩性仍按跨端门槛计 **87/100**，不是三端分数的算术平均。缺失平台证据本身就是产品风险，
不能用共享代码或另一平台的成功替代。phase126 的新世界验收证据见
`vnext/eval/evidence/phase127-next-goal-draft-review-and-context-grounding.json`。

## 玩家功能矩阵

| 玩家任务 | macOS | Windows | Android | 当前判断 |
| --- | --- | --- | --- | --- |
| 首次模型设置 | CRUD、Probe、默认、编辑态真实回归；首次空状态直接展开中性配置；API Key 进入系统密钥链 | 共享实现，未安装验证 | CRUD/default/provider preset/安全凭据 adapter 覆盖，未真机 | 实现完成，三端 3 分钟安装验收不足 |
| 世界 / 旅程 | 世界详情、继续、新旅程、归档/恢复真实回归 | 共享实现，未安装验证 | 世界点击、继续/新旅程、归档/恢复 widget/core 覆盖 | 实现完成，重启和安装包旅程待验证 |
| 开场与沉浸 | opening、人物对话、目标、引导、状态反馈真实回归；revision/内部 ID 已退出玩家界面 | 共享实现，未安装验证 | opening/story beat widget 覆盖；多地点自由行动现在提交与桌面一致的 `move` 命令，地点选项来自当前 World presentation；World 入口不显示 revision | 实现完成，长局和大字体待验证 |
| LLM Loading | 阶段、耗时、自由行动/故事选择叙事增量、慢模型、取消、重试、零写入真实回归；10/120 秒超时有可执行恢复提示 | 共享实现，未安装验证 | 已显示准备/连接/生成/写入，超时与连接错误不暴露 Python/urllib 异常名 | Android 真机慢模型及流式回调仍缺证据 |
| 正式结局 | 结局叙事、路线/物品/关系/关键行动回顾、回 World、同世界新 Run 真实回归 | 共享实现，未安装验证 | 相同 ending recap/new Run widget 覆盖 | 三端安装包旅程未闭环 |
| 退出与恢复 | `.app` 包内 Host 已完成 30 回合、退出、重启和 30/30 回读；当前 DMG WebView 窗口 gate 失败 | 未运行 | 自动化/历史模拟器证据 | macOS 需先恢复可见窗口；Windows/Android 当前包和三次恢复仍缺 |

## 代码质量拆分

| 维度 | 分数 | 已做到 | 仍需改进 |
| --- | ---: | --- | --- |
| 干净与可读 | 81 | Android 根文件已显著拆分；desktop 玩家组件独立；模型请求/schema/修复不再内联；玩家主路径不再暴露 revision/aggregate ID/Host；模型档案列表已从根页面移出 | desktop `App.vue` 仍约 1500 行；runtime 的 World/Run/Turn/portable 编排仍集中 |
| 通用边界 | 85 | World/Run、ModelProfile、story beat、operation cancellation、provider protocol、embedded model request 与 generated-world repair 均有明确契约；Experience Contract 现在锁定两端 operation stage、可取消和终态边界 | operation 的阶段事件仍不是完整跨端流式协议，阶段常量尚未由契约自动生成 |
| 复用 | 86 | 桌面与 Android 复用 Python command engine、story beat、Run player presentation、provider protocol、叙事提示/预算/清洗/截断判定、模型超时/连接恢复契约、模型请求/修复、自由行动 move+narrate 命令边界和 Experience Contract | desktop FastAPI service 与 Android runtime 仍有部分持久化编排重复 |
| 低耦合 | 85 | LocalHostPort 隔离 UI/传输；桌面玩家组件和模型 composable 独立；embedded 模型 HTTP、schema、repair 和 repository 均脱离 runtime | `App.vue` 仍编排世界创作、portable、生命周期和 AI 草案；runtime 仍直接编排多类 SQLite 聚合 |
| 可测试性 | 90 | 后端 112 tests、Flutter 21 tests、desktop 32 个组件/组合式/API/纯函数测试、冻结 sidecar `/health` smoke；模型请求、超时/连接错误映射、模型 Probe Loading/阶段显示、模型列表事件边界、动态地点 presentation/move parity、单地点 action parity、跨 Run retry boundary、Android 异常名隔离、凭据 Authorization、AI 草案取消零写入与取消传输失败恢复、Run pending-operation 恢复、导入/复制旅程 active Run 恢复、SSE 跨 chunk 解析与 choice stream、portable content 合并边界、release package extra gate、归档世界 view-only 边界、叙事清洗/截断、安全修复、stage parity、ending key redaction、player-surface ID redaction、离线/键盘边界、profile validation/provider preset、Android 后台线程、World 归档 parity、action mode、回滚语义、sidecar 父进程退出和干净打包迁移边界有纯边界测试 | Windows/Android package E2E 未成为可执行门禁；desktop AI 草案仍缺组件测试 |
| **代码质量** | **85** | **源代码质量门槛暂时达到；共享边界、关键组件和 embedded 模型链路均有自动化保护；跨 Run 重试边界已统一并有纯函数测试** | **85 不是发布完成：大编排器和三端 package E2E 仍需继续治理** |

## 保持并突破 85 的具体条件

1. desktop 已拆出玩家游玩、Loading、World/Run 入口、模型编辑器和模型列表并建立组件测试；下一步拆 AI 草案、portable 和 lifecycle 编排。
2. embedded 模型请求、schema、修复和 ModelProfile repository 已拆出；下一步把 `core_runtime.py` 的 World/Run、Turn、portable repository/service 拆分，FastAPI 与 Android 只保留 adapter。
3. 将当前桌面/Android 的 operation stage 常量继续提升为由 Experience Contract 生成的类型；当前 parity test 已禁止阶段集合漂移，且可取消/终态边界已统一。
4. Windows 原生安装包、macOS 当前安装包和 Android 真机分别完整执行 A-F、30 回合、慢模型、失败、取消和三次重启恢复。
5. 将上述玩家旅程固化为 release gate；任何平台缺 P0 证据时，不允许只凭构建成功提高到 85。

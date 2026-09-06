# DZMM vNext 跨端剧情主题 UX 评审

## 结论

Mac 源码已经有雾夜、纸页、琥珀三套主题；此前 Android 只有浅色 `ThemeData`，并在首页保留了硬编码深青色卡片，因此用户实际感知为“手机只有白色”，两端也没有统一的主题选择体验。

本次把三套主题收敛为跨端共享的语义令牌：Android 的 Material `ColorScheme` 和 Mac 的 CSS 变量使用相同主题 ID。主题是本地展示偏好，不进入 World、WorldVersion、Run、RunState 或 Host API。

## 主题定位

| 主题 | 视觉语义 | 适合场景 |
|---|---|---|
| 雾夜 `fog` | 深海绿、雾白、旧金色 | 夜间剧情、关系叙事、沉浸游玩 |
| 纸页 `paper` | 暖白、松绿、低对比阴影 | 世界创作、世界书阅读、设置管理 |
| 琥珀 `amber` | 深棕、铜线、琥珀高光 | 悬疑、遗迹、资源紧张的冒险 |

主题选择必须改变整个界面的背景、surface、导航栏、输入框、卡片和主按钮；不应只换一个 accent。游玩页仍需在后续评审中确认长文本、结局告警和大字体对比度。

## 交互

- Mac：顶部“主题”选择器，保存在 `localStorage` 的 `dzmm-next-theme`。
- Android：AppBar 调色板入口打开底部选择器，说明“只改变界面氛围，不会修改世界或 Run 状态”；选择保存在本机安全存储，不上传 Host。
- 未配对、断线、模型失败和结局锁定的语义颜色继续由 `danger/success/primary` 令牌提供，不能因剧情主题而失去可辨识度。

## 验收边界

`flutter analyze`、24 项 Flutter 测试和 debug APK 构建已通过；当前 shell 没有 Android SDK/AVD，也没有安装当前 worktree 构建的 Mac app，因此尚未取得三主题截图、TalkBack、大字体或 packaged WebView 证据。证据见 [`phase49-cross-platform-themes-interim.json`](../../vnext/eval/evidence/phase49-cross-platform-themes-interim.json)。在截图验收前不调整成熟度分数。

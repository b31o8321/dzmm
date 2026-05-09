# Open World Framework Design

> **Status:** Approved  
> **Date:** 2026-05-10  
> **Scope:** Full architecture redesign — fresh start, no backwards compatibility with existing sessions

---

## Overview

Replace the current linear Screenplay + Chapters structure with a three-layer sandbox open-world framework. The core shift: the world exists independently of any single story; players explore, grow stronger through exploration, and optionally pursue a phase-based main plot layered on top.

---

## Section 1: Data Architecture

### Three-Layer Model

```
WorldFramework (immutable template — shared across sessions)
  └── WorldLocation[]       地点节点，含方位连接
  └── WorldFaction[]        势力，含紧张度规则
  └── WorldNPCTemplate[]    NPC 模板
  └── WorldEvent[]          事件库
  └── Campaign? (optional)  主线剧情框架

Session (runtime state)
  └── session_location_states   地点被摧毁/受损覆盖
  └── session_npc_states        NPC 当前位置/好感/旅伴状态
  └── session_event_states      已触发/完成事件
  └── session_faction_states    势力当前紧张度/关系
  └── session_campaign_state?   主线进度（若有 Campaign）
```

**WorldFramework 是只读模板；Session 在其上叠加运行时状态覆盖层。**

### WorldLocation

```python
class WorldLocation(Base):
    id: int
    framework_id: int
    name: str
    description_md: str
    location_type: str          # city / dungeon / wilderness / landmark
    connections_json: str       # [{target_id, direction, distance, travel_turns}]
    controlling_faction_id: int | None
    initial_state: str          # normal / damaged / destroyed
```

- `connections_json` 描述双向通路：方向（北/东/地下…）+ 距离（0=同地，1=相邻，2=近邻，3+=远方）
- `distance` 用于 Director 的事件投递衰减计算

### WorldFaction

```python
class WorldFaction(Base):
    id: int
    framework_id: int
    name: str
    description_md: str
    rival_factions_json: str    # [faction_id, ...]
    ally_factions_json: str
    tension_rules_json: str     # 紧张度自动累积规则
```

Session 层：`session_faction_states(session_id, faction_id, tension: int, pc_reputation: int)`

紧张度超过阈值时自动触发关联 WorldEvent（类型 = `faction_conflict`）。

### WorldNPCTemplate

```python
class WorldNPCTemplate(Base):
    id: int
    framework_id: int
    name: str
    gender: str
    role: str
    description_md: str
    motivation: str
    home_location_id: int
    faction_id: int | None
    avatar_asset_id: int | None
```

Session NPC 状态：`session_npc_states(session_id, npc_template_id, current_location_id, favor: int, is_companion: bool, is_revealed: bool, last_contact_turn: int | None)`

### WorldEvent

```python
class WorldEvent(Base):
    id: int
    framework_id: int
    name: str
    summary_md: str
    scope_type: str             # location / faction / global
    scope_ref: str              # location_id 或 faction_id
    importance: int             # 1-5，影响 Director 优先级和传闻门槛
    trigger_conditions_json: str
    # AND 逻辑条件列表：
    # [{type: "location", value: loc_id},
    #  {type: "event_done", value: event_id},
    #  {type: "faction_rep", faction_id, op: "gte", value: N},
    #  {type: "npc_met", value: npc_template_id},
    #  {type: "stat_gte", stat: "strength", value: N}]
    is_repeatable: bool
    cooldown_turns: int
```

Session 事件状态：`session_event_states(session_id, event_id, status: pending/triggered/completed, triggered_turn: int, summary_override: str | None)`

### Campaign（可选主线）

```python
class Campaign(Base):
    id: int
    framework_id: int
    name: str
    phases_json: str
    # [{phase_id, name, description, prerequisite_phase_ids,
    #   key_event_ids, required_count}]
```

- `required_count`：触发 `key_event_ids` 中 N of M 个即可进入下一 Phase
- Session 层：`session_campaign_state(session_id, current_phase_id, triggered_key_events: [event_id])`

---

## Section 2: Director Agent 改造

Director 不再读章节，改为读「附近可用事件 + 主线进度」来生成 `plot_directive`。

### 事件评分公式

```
score = importance × distance_factor + companion_bonus + faction_bonus

distance_factor:
  dist 0 (PC 所在地)  → 1.0
  dist 1              → 0.8
  dist 2              → 0.5
  dist 3+             → 0  (不进入候选，改走传闻通道)

companion_bonus: +0.3 若事件关联一个旅伴 NPC
faction_bonus:   +0.2 若关联势力与 PC 有高声望/宿仇
```

候选事件 = 所有 `status=pending` 且满足 `trigger_conditions` 的 WorldEvent，排除 `dist 3+`（除非 importance≥3 且传闻冷却已过）。

Director prompt 上下文：

```
当前地点: {location.name} — {location.description}
PC 角色概要: {character_md}
旅伴: {companion_npcs}
附近 NPC（dist 0-2）: {nearby_npcs}
候选事件（按 score 排序，top 5）: {events}
主线进度: {campaign_phase} / {triggered_key_events}  （若有）
势力紧张度摘要: {faction_tensions}
```

### 传闻通道

- 条件：`dist 3+`，`importance ≥ 3`，距上次传闻 ≥ 5 turns，每局每地点每事件最多传闻 1 次
- 形式：GM 在叙述中插入"有旅人提到，{远方地点} 据说…"
- Session 层记录传闻已投递状态，避免重复

### NPC 主动联系

条件（AND）：

1. `npc.favor ≥ threshold`（默认 70/100）
2. `npc.current_location ≠ pc_location`（距离 ≥ 1）
3. 距上次联系 ≥ `cooldown_turns`（默认 10 turns）
4. 存在与该 NPC 关联且 `importance ≥ 2` 的待触发事件（可选加分项）

联系形式由 NPC 性格决定：信件、传心术、信使 NPC 等，GM 负责叙述方式。Director prompt 中注明"建议本回合通过叙事引入 {npc.name} 的主动联系"。

---

## Section 3: Wizard 生成流程（8 步）

| 步骤 | 生成内容 | 支持逐条再生成 |
|------|----------|--------------|
| 1 | 世界基调（类型/主题/时代背景） | 否 |
| 2 | 地点网络（6-10 个地点 + 连接关系） | 是（逐地点） |
| 3 | 势力（3-5 个 + 初始紧张度） | 是（逐势力） |
| 4 | NPC 模板（8-12 个） | 是（逐 NPC） |
| 5 | 事件库（15-25 个） | 是（逐事件） |
| 6 | 主角设定 | 否 |
| 7 | （可选）Campaign 主线框架 | 是（逐 Phase） |
| 8 | 确认 + 生成 WorldFramework | 否 |

### 再生成 UX（所有步骤统一）

每步右上角：
- **整步再生成**：`[引导词输入框] [再生成整步 ↻]`
- **逐条再生成**（列表步骤）：每行末尾 `[小输入框] [↻]`

引导词可选填；为空时按原参数重新生成。整步再生成会覆盖当前结果并提示用户确认（若已手动编辑过）。

### 步骤 2：地点网络编辑器

- 可视化拖拽：节点 = 地点，连线 = 通路
- 点击节点编辑名称/类型/描述
- 点击连线编辑方向/距离
- LLM 生成后自动布局；用户可手动调整

---

## Section 4: 世界状态变异

Session 运行过程中，WorldFramework 的初始状态可被覆盖：

- **地点变异**：事件结果可将地点标记为 `damaged / destroyed`；destroyed 地点的关联事件不再触发（除非有"遗址"类事件）
- **NPC 死亡/离开**：`is_alive = false` 后从候选 NPC 池中移除；旅伴死亡触发专属剧情事件
- **势力灭亡**：`tension ≥ max` 触发决战事件，结果可能导致势力 `is_active = false`
- **Campaign Phase 推进**：满足 required_count 后 Phase 自动 complete，下一 Phase 激活

所有变异只写入 Session 层，WorldFramework 保持不变（同一 WorldFramework 可开多局存档）。

---

## Section 5: 前端变化

### 5.1 新增组件

**WorldMapPanel**（替换 ScreenplayPanel）
- 网格地图，每节点为一个 `WorldLocation`
- 颜色编码：正常（绿）/ 受损（橙）/ 毁灭（红）/ 未探索（灰）
- PC 当前位置高亮；连接线显示通路方向
- 点击**已探索地点** → LocationDetailPopup：
  - 名称 + 状态标签 + 控制势力
  - **NPC 列表**：`session_npc_states.current_location` 匹配此地的 NPC（头像+名字+好感+旅伴标识）
  - **已触发事件**：`session_event_states` 中 `scope_ref` 匹配此地且 `status = triggered/completed` 的事件（名称+摘要+状态徽章）
  - 可通往出口列表
- 点击**未探索地点** → 仅显示"未知区域" + 传闻摘要（若有）

**CampaignProgressPanel**（可选主线模式）
- 各 Phase：已完成 ✓ / 当前激活 → / 锁定 🔒
- 已触发 KeyEvent 列表（可展开查看摘要）
- 当前 Phase 进度：`M / N 关键事件已触发`

### 5.2 修改组件

**StatePanel**
- NPC 列表追加旅伴标识（旗帜图标）和 `current_location` 小灰字
- 移除 PlotThread 相关字段

**GameView**
- 顶部导航新增"世界地图"标签页（与"状态"/"对话"/"档案"并列）

### 5.3 Wizard 流程 UI

- 每步右上角统一再生成按钮区（整步 + 逐条）
- 步骤 2 新增地点网络可视化拖拽编辑器
- 步骤 7 为可选步骤（用户可跳过进入纯沙盒模式）

---

## 迁移策略

**无需迁移**：本次为全新架构，不兼容旧存档。旧 Session 继续使用旧代码路径直到被废弃；新 Session 仅在选择"新建存档"时使用新框架。

新建存档时，Wizard 检测 `framework_id` 字段：若为 null 则走旧流程（过渡期），若有值则走新流程。

---

## 关键决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 框架层级 | 三层（World / WorldFramework / Session） | 同一世界模板支持多存档 |
| 主线模式 | Phase-based（可选） | 沙盒+主线两不误 |
| 事件触发 | 骨架 + 动态组合 | 避免纯程序生成无聊感 |
| 兼容性 | 不兼容旧存档，全新开始 | 避免兼容代码堆积 |
| 距离模型 | 图距离（跳数），非欧氏距离 | 符合奇幻地理直觉 |
| NPC 主动联系 | 好感阈值 + 冷却 + 关联事件 | 世界"活"起来的核心机制 |

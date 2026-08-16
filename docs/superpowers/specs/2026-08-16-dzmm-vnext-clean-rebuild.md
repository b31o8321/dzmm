# DZMM vNext Clean Rebuild：规格、Plan 与成熟度矩阵

## Product thesis

DZMM vNext 是一个本地优先的单人 AI TRPG：玩家在 Mac 建立可审阅的世界与角色，在桌面或 Android 继续同一局；Python 是规则和状态的唯一裁判，模型只负责叙事与意图。它消费酒馆生态的内容，但不成为酒馆式通用 prompt 工作台。

## Scope and constraints

- **Clean slate：** 不迁移、读取或修改 v0.x 的数据，不兼容旧 API/schema/UI。开发与 RC 数据目录固定为 `~/.dzmm-vnext/`。
- **保留：** 本地优先、FastAPI/Python engine、SQLite、SSE、Tauri desktop host、Flutter Android gameplay client 的技术方向。
- **重做：** 数据库、route、domain service、frontend route、mobile API contract、打包 identifier。
- **不做：** 云同步、多人桌、群聊 bot、任意脚本/regex、iOS、公共网络直连。

## P0 product requirements

1. **一个世界，一次提交。** 向导产生草稿；确认后使用一个幂等 command 原子创建 World、WorldVersion、Hero、Run 与初始 RunState。
2. **一个运行态。** 一局 Run 只读取固定 WorldVersion，所有可变地点/NPC/事件/物品/角色状态存于 versioned RunState。
3. **一个回合真相。** Turn command 被 Python 验证和应用；模型流式叙事无法直接改状态；失败、断线、重试都最多提交一次。
4. **一个内容边界。** Lorebook 可以通过关键词/常驻/优先级参与上下文，原始 ST 字段可保留；只有确认提升才成为结构实体。
5. **一个主机。** Mac 保存模型、世界和 Run；Android 配对后仅能游玩、恢复和查看允许状态。
6. **一个退出路径。** World 可归档或永久删除；删除影响由 manifest 预览，SQL、文件和索引无孤儿。

## Canonical architecture

```text
World
  └─ WorldVersion (immutable WorldDefinition JSON)
       ├─ lore[]              context-only
       ├─ map / factions / NPC definitions / event definitions
       └─ ruleset descriptor

Run (world_version_id, hero, model profile)
  ├─ RunState (revisioned JSON: all mutable gameplay facts)
  └─ Turn[] (input, narrative, validated commands, before/after revisions, diagnostics)

Mac host
  ├─ ModelProfile (protocol + probe)
  ├─ Python engine + TurnCoordinator
  └─ API v2 / pairing / SSE resume
       ├─ Vue/Tauri: authoring and host control
       └─ Flutter: gameplay only
```

### Content contract

`WorldDefinition` uses JSON Schema and versioning. It keeps all references inside one definition, so a world cannot partially own locations, events or NPCs in different tables. `RunState` uses a separate JSON Schema and an integer revision. Python commands operate on typed IDs from that definition; invalid IDs, invalid state transitions and arbitrary LLM attributes fail closed.

The MVP deliberately uses JSON documents rather than an ORM table per world entity. A local single-player app needs atomic authoring, safe lifecycle and snapshot restoration more than cross-world SQL joins. Analytics/search can be added as derived indexes only after the aggregate is stable.

## Maturity matrix — the only scoring system

All vNext dimensions start at **0**. No legacy score, old CI result, mock, source copy or prior playtest earns a vNext point. Score only against committed code on `feature/dzmm-vnext` and recorded evidence.

| Dimension | Weight | P0 threshold | 85-point evidence |
|---|---:|---:|---|
| Domain & lifecycle integrity | 15 | 80 | Atomic compose/retry/failure tests; archive/purge manifest; SQL/file/index orphan scan is zero. |
| Game loop & rule truth | 20 | 80 | Python commands, state revision, rollback, choices/dice/events and 30-turn real-model run pass. |
| Creation & content interoperability | 15 | 80 | One wizard journey; ST V3 card + World Info import report; Lore promotion and export round-trip pass. |
| Model & stream robustness | 10 | 80 | Ollama, LM Studio and OpenAI-compatible probes; malformed 200, empty stream, 429 and cancellation handled. |
| Desktop UX & accessibility | 10 | 80 | Create/play/archive/recover on packaged desktop; keyboard and screen-reader primary flow reviewed. |
| Mac host & Android recovery | 10 | 80 | QR/PIN/manual pair, revoke, SSE resume, Wi-Fi/Mac restart and concurrent submission on physical devices. |
| Long-play performance | 10 | 80 | 50-turn run, 500-message reopen and target-device streaming budgets measured; no state corruption. |
| Engineering & release readiness | 10 | 80 | Fresh-db migrations, contract/e2e suite, signed RC artifacts, diagnostics export and release checklist pass. |
| **Total** | **100** | **all P0 >=80** | **weighted score >=85, no open P0 defect** |

### Score evidence rules

- 0–39: code/design only, or an untested capability.
- 40–64: deterministic unit/contract coverage, no full user journey.
- 65–79: local integration/E2E with temporary DB and deterministic/fake provider.
- 80–84: packaged app plus real provider or real device evidence for the dimension.
- 85+: repeated target environment evidence, recovery/failure coverage, no unresolved P0 defect.

Each gate records command output, environment, artifact/commit, score delta and remaining gap in `docs/ACTIVE_DELIVERY_INDEX.md`. A dimension never receives a higher score by inference from another dimension.

## Delivery Plan

### Phase 0 — contracts and score harness

**Outcome:** a blank vNext product root can boot against a fresh isolated database and report zero-score baseline.

- Create `vnext/` root, application identifier and `~/.dzmm-vnext/` config/data path.
- Define JSON Schemas for WorldDefinition, RunState, TurnCommand and protocol event envelopes.
- Create Alembic baseline and enforce SQLite foreign keys on every connection.
- Build `eval/scorecard` that reads evidence files and produces the matrix; start each dimension at 0.

**Gate:** API health, schema validation and a fresh DB smoke pass. Total may remain below 20; no legacy imports.

### Phase 1 — playable vertical slice

**Outcome:** user can compose a two-location world, one hero and one run through a single command, then play three recoverable turns on desktop.

- Implement World/WorldVersion/Run/Turn persistence and atomic idempotent compose.
- Implement Python command validation for narrative, choices, dice and basic state change.
- Implement model profiles/probe and SSE turn stream with request id.
- Deliver a minimal Vue desktop flow: Create → Confirm → Play → Refresh/recover.

**Gate:** 20 failure injections yield either 0 or 1 complete aggregate; 3/3 turns recover after refresh. Matrix target: **>=45**, Domain and Game Loop >=40.

### Phase 2 — lifecycle, real rules and long play

**Outcome:** vNext is a trustworthy local game, even before content imports or Android.

- Add archive/purge and manifest impact preview; include asset/index cleanup and integrity scan.
- Expand RunState and engine for inventory, combat, NPC/event state, location travel and rollback.
- Add director context builder that only consumes WorldVersion + RunState; remove screenplay concept entirely.
- Package the desktop host and run a real model 30-turn journey.

**Gate:** purge scan reports zero orphans; rollback and 30-turn real-model run pass. Matrix target: **>=65**, Domain/Game Loop/Model >=65.

### Phase 3 — content ecosystem and authoring quality

**Outcome:** existing RP content becomes useful without turning the product into a prompt editor.

- Implement LoreEntry selection, context budget diagnostics and explicit promotion workflow.
- Import/export ST V3 character cards, PNG metadata and World Info with supported/preserved/ignored report.
- Add World Center: draft, playable and archived state; edit creates new WorldVersion and never mutates active runs.
- Add Do / Say / Story input modes, per-turn edit/retry/rollback and player-visible world state.

**Gate:** 10 mixed World Info entries round-trip unknown fields; create/import/archive/recover E2E passes. Matrix target: **>=75**, Content and UX >=70.

### Phase 4 — mobile host and release candidate

**Outcome:** Android is a reliable remote play surface, not a web wrapper.

- Rebuild remote control plane on API v2: capability discovery, mDNS/subnet/manual, QR/PIN approval, token revoke and allowlist.
- Implement Flutter session/run hydration, state/choice view, stream/reconnect/gap recovery and accessibility semantics.
- Perform physical Android + two-router + mDNS-blocked + DHCP-change matrix.
- Produce signed Android RC and packaged Mac host; run real-model 30-turn Android journey and physical 100-turn disconnect soak.

**Gate:** Matrix **>=85**, every P0 >=80, no P0 defect. This is the only release gate.

## Expected experience impact

| User outcome | Current v0.x concern | vNext target |
|---|---|---|
| “我创建的到底是什么？” | World/Framework/Screenplay overlap | One confirmed WorldVersion and one Run. |
| “失败后留下了什么？” | Four sequential writes | One atomic request and visible draft state. |
| “删了是否干净？” | Hand-maintained cascades | Archive first; purge manifest plus zero-orphan scan. |
| “酒馆内容能否用？” | Manual copy/paste | Import report, safe Lore activation and explicit entity promotion. |
| “手机是否能顺畅玩？” | Current RC has unrun physical gate | New versioned host contract validated on real LAN/device. |

## Explicit non-goals and risk controls

- 不把 v0.x 的成熟度、测试或真实用户库当成 vNext 的验收替代品。
- 不删除或改写现有 `~/.dzmm` 数据；vNext 数据目录、bundle id、端口/instance identity 独立。
- 不因“重做”扩大成多人、云、插件市场或任意 prompt scripting。
- 如果模型质量影响叙事，记录为模型维度问题；不能借由放宽 Python 状态校验来掩盖。

## First implementation decision

开始代码前只需确认两项：

1. vNext 的用户可见名称是否仍为 **DZMM**，还是先以 **DZMM Next / vNext Preview** 发布？建议 Preview，避免覆盖已安装应用。
2. Phase 1 的真实模型基准是否固定为 `huihui-ai_qwen3-14b-abliterated`，并用本地 Qwen 7B 做快速工程测试？建议是。

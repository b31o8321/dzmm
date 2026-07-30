# dzmm Android Remote Client Implementation Plan

> **Status:** Proposed  
> **Date:** 2026-07-30  
> **Spec:** [`../specs/2026-07-30-android-remote-client-design.md`](../specs/2026-07-30-android-remote-client-design.md)  
> **Branch:** `feature/android-remote-client`  
> **Target:** Locally smooth Android gameplay, maturity score ≥85

## Goal

Add an authenticated Flutter Android gameplay client while keeping Mac/Tauri/Vue as the host and full management UI. The Mac app starts local-only, can opt into LAN access from Settings, and controls pairing/devices. Remote play must preserve the existing engine and data model while adding a secure route boundary, idempotent single-writer turns, and reconnect recovery.

## Delivery rules

- Keep each phase independently testable and do not scaffold later UI before its backend contract is passing.
- Preserve current Vue behavior throughout; new remote APIs are additive until Vue deliberately migrates.
- Never use the real `~/.dzmm/dzmm.db` in automated tests.
- All public pairing inputs are rate-limited and all remote routes are covered by an authorization matrix test.
- Do not call Android v1 complete until the real Mac + real Android acceptance matrix passes.
- Keep Android v1 focused on gameplay. Model, world, framework, wizard, debug, update, and destructive management stay Mac-only.

## Estimated effort

| Phase | Estimate | Exit condition |
|---|---:|---|
| 0. Contracts and test harness | 3–4 days | API/security contracts executable in tests |
| 1. Remote identity, auth, pairing | 7–9 days | Unpaired/paired/admin route matrix passes |
| 2. Mac remote-access control plane | 5–7 days | Enable/pair/revoke/disable works in packaged Mac app |
| 3. Mobile-safe turn runs | 7–9 days | Duplicate/disconnect/concurrency tests pass |
| 4. Flutter connection foundation | 5–7 days | Scan/manual/reconnect host on physical Android |
| 5. Android pairing | 4–6 days | Approval/QR/PIN all pass |
| 6. Android gameplay v1 | 8–10 days | Three-turn real-device journey passes |
| 7. Resilience, polish, release | 7–10 days | Maturity score ≥85 and signed RC produced |
| **Total** | **8–11 person-weeks** | Release candidate accepted |

For one developer, allow calendar slack for router/OEM testing and signing setup rather than treating the sum as an uninterrupted coding schedule.

## Target repository shape

```text
dzmm/
├── backend/
│   ├── src/dzmm/
│   │   ├── api/routes_remote.py
│   │   ├── remote/
│   │   │   ├── auth.py
│   │   │   ├── discovery.py
│   │   │   ├── pairing.py
│   │   │   └── turn_runs.py
│   │   └── service/session_turn_coordinator.py
│   └── tests/
│       ├── test_remote_auth.py
│       ├── test_remote_pairing.py
│       ├── test_remote_discovery.py
│       └── test_turn_runs.py
├── frontend/
│   ├── src/api/remote.ts
│   ├── src/components/RemoteAccessCard.vue
│   └── src-tauri/src/lib.rs
├── mobile/                         # Flutter project; Android shipped first
│   ├── lib/
│   │   ├── api/
│   │   ├── connection/
│   │   ├── features/pairing/
│   │   ├── features/sessions/
│   │   └── features/game/
│   ├── test/
│   └── integration_test/
└── docs/superpowers/
```

Names may be adjusted to match code discovered during implementation, but responsibilities must remain separated: HTTP policy in `api/remote`, pairing/identity in `remote`, and game rules in the existing service/engine layers.

## Phase 0 — Freeze contracts and build the test harness

### Task 0.1: Record protocol constants and route policy

**Files:**

- Modify: `backend/src/dzmm/__init__.py` only if an API protocol version belongs there
- Create: `backend/src/dzmm/remote/__init__.py`
- Create: `backend/src/dzmm/remote/auth.py`
- Create: `backend/tests/test_remote_auth.py`

- [ ] Define `REMOTE_API_VERSION = 1` and capability names.
- [ ] Encode route classes as an explicit allowlist: public pairing, paired gameplay, loopback-only, denied.
- [ ] Test every registered route against its expected class; fail when a new route is accidentally remotely exposed.
- [ ] Test that socket peer identity—not `X-Forwarded-For`—controls loopback classification.

**Verify:**

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_remote_auth.py
.venv/bin/python -m ruff check src/dzmm/remote tests/test_remote_auth.py
```

### Task 0.2: Add remote test fixtures

**Files:**

- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/remote_helpers.py`

- [ ] Add a temporary SQLite fixture with remote identity/device rows.
- [ ] Add helpers for loopback, unpaired LAN, paired LAN, revoked token, and malformed token requests.
- [ ] Ensure secrets and tokens are redacted from captured logs and assertion output.

**Gate 0:** contract tests demonstrate the intended boundary before any LAN listener is considered safe.

## Phase 1 — Remote identity, authorization, pairing, and discovery

### Task 1.1: Persist server identity and paired devices

**Files:**

- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/src/dzmm/db/base.py`
- Create: `backend/src/dzmm/remote/pairing.py`
- Create: `backend/tests/test_remote_pairing.py`

- [ ] Add a singleton remote server state with stable UUIDv4 `server_id`.
- [ ] Add paired-device rows: `device_id`, name, token hash, paired/last-seen/revoked timestamps.
- [ ] Add pending pair requests and durable metadata only where restart behavior requires it; keep PIN and QR claim secrets in memory.
- [ ] Generate at least 256-bit device tokens and persist only SHA-256 hashes.
- [ ] Re-pairing one `device_id` rotates the token atomically.
- [ ] Add backwards-compatible, idempotent startup migration tests.

**Verify:** new DB, upgraded DB, repeated startup, token rotation, and no plaintext-token persistence.

### Task 1.2: Add request authentication and narrow CORS

**Files:**

- Modify: `backend/src/dzmm/main.py`
- Create/modify: `backend/src/dzmm/remote/auth.py`
- Modify: `backend/tests/test_remote_auth.py`

- [ ] Add middleware/dependency that classifies loopback, public pairing, paired gameplay, and forbidden remote requests.
- [ ] Compare token hashes in constant time and reject revoked devices.
- [ ] Update last-seen without blocking every request on a DB write; coalesce persistence.
- [ ] Replace wildcard CORS with Tauri plus local Vite origins.
- [ ] Return stable JSON error codes for 401/403/409 responses.
- [ ] Prove that model, wizard, debug, asset mutation, TTS admin, update, and remote-admin routes are inaccessible from LAN.

### Task 1.3: Implement pairing APIs

**Files:**

- Create: `backend/src/dzmm/api/routes_remote.py`
- Create/modify: `backend/src/dzmm/remote/pairing.py`
- Modify: `backend/src/dzmm/main.py`
- Modify: `backend/tests/test_remote_pairing.py`

- [ ] Implement 60-second phone requests and request-specific long polling.
- [ ] Implement loopback-only list/approve/deny endpoints.
- [ ] Implement five-minute, one-time QR claims; never embed admin/device tokens.
- [ ] Implement five-minute PIN windows, five-failure cooldown, and one-success close.
- [ ] Cap global pending requests and per-IP request frequency.
- [ ] Implement device list/revoke and ensure revocation affects the next request.
- [ ] Ensure all timers and poll waiters clean up on expiry/shutdown.

### Task 1.4: Add discovery identity and mDNS

**Files:**

- Modify: `backend/src/dzmm/api/routes_system.py`
- Create: `backend/src/dzmm/remote/discovery.py`
- Modify: `backend/src/dzmm/main.py`
- Modify: `backend/src/dzmm/main_entry.py`
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/test_remote_discovery.py`

- [ ] Extend `/health` with `server_id`, `api_version`, `remote_access`, and capabilities.
- [ ] Advertise `_dzmm._tcp.local` only when remote mode is enabled.
- [ ] Stop advertisement reliably on shutdown and tolerate mDNS failure without crashing gameplay.
- [ ] Avoid logging tokens, PINs, or claim values.

**Gate 1 verification:**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_remote_auth.py \
  tests/test_remote_pairing.py \
  tests/test_remote_discovery.py
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests
```

Do not proceed to Android gameplay until the remote authorization matrix is green.

## Phase 2 — Mac app remote-access control plane

### Task 2.1: Make local-only startup automatic

**Files:**

- Modify: `frontend/src/components/BootGate.vue`
- Modify: `frontend/src/stores/app.ts`
- Modify: `frontend/src-tauri/src/lib.rs`
- Modify: `frontend/tests/api.test.ts` or add a focused component test

- [ ] Remove the startup local/LAN choice and start `lan_mode=false` automatically in Tauri.
- [ ] Track backend mode and transition state explicitly rather than with only `lanMode: bool`.
- [ ] Extend Tauri commands to report backend state and restart local/remote predictably.
- [ ] Pass an explicit remote-mode environment flag so FastAPI knows whether to advertise and enforce the remote control plane.
- [ ] Preserve close-window sidecar cleanup.

### Task 2.2: Build the Settings remote-access card

**Files:**

- Create: `frontend/src/api/remote.ts`
- Create: `frontend/src/components/RemoteAccessCard.vue`
- Modify: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/stores/app.ts`
- Add focused Vitest coverage

- [ ] Show local/remote/restarting/error status and current LAN addresses.
- [ ] Enable only after trusted-network confirmation and backend health probe.
- [ ] Disable by returning to loopback; retain paired devices.
- [ ] Show pending phone requests with approve/deny actions.
- [ ] Generate/expire QR and PIN pairing windows.
- [ ] List paired devices with paired/last-seen timestamps and revoke action.
- [ ] Poll only while the card is visible or a pairing window is active.
- [ ] Cover loading, empty, failure, recovery, and refresh/re-entry states.
- [ ] Keep Windows desktop builds green; do not claim Windows remote-host support until it has its own acceptance matrix.

### Task 2.3: Package-level LAN acceptance

- [ ] Build/install the Mac app, not only Vite dev mode.
- [ ] Verify `127.0.0.1` listener at startup.
- [ ] Enable remote and verify `0.0.0.0:8765` plus mDNS.
- [ ] Disable and verify LAN denial plus local Vue health.
- [ ] Verify the macOS firewall prompt/help text if it appears.

**Gate 2:** packaged Mac app can control remote exposure and pairing without a browser or menu-bar utility.

## Phase 3 — Single-writer, idempotent, reconnectable turns

### Task 3.1: Add the shared session turn coordinator

**Files:**

- Create: `backend/src/dzmm/service/session_turn_coordinator.py`
- Modify: `backend/src/dzmm/api/routes_sessions/turn.py`
- Modify: `backend/src/dzmm/api/routes_sessions/npc_tick.py`
- Create: `backend/tests/test_session_turn_coordinator.py`

- [ ] Enforce one active mutating turn per session in this backend process.
- [ ] Make `/turn`, `/npc_tick`, and new turn runs share the coordinator.
- [ ] Return active-run metadata for `session_busy` rather than waiting indefinitely.
- [ ] Release locks on success, model error, cancellation, and shutdown.
- [ ] Prove different sessions may still generate concurrently.

### Task 3.2: Persist idempotent run metadata

**Files:**

- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/src/dzmm/db/base.py`
- Create: `backend/src/dzmm/remote/turn_runs.py`
- Create: `backend/tests/test_turn_runs.py`

- [ ] Add `TurnRun` with unique `(session_id, request_id)`, action, status, timestamps, error code, and assistant message ID.
- [ ] Mark stale running records interrupted at backend startup.
- [ ] Repeated create with the same request ID returns the existing run.
- [ ] Never create a second user/assistant message pair for one request ID.

### Task 3.3: Add detached producer and replayable SSE

**Files:**

- Modify: `backend/src/dzmm/api/routes_sessions/turn.py` or add `turn_runs.py` under the route package
- Modify: `backend/src/dzmm/remote/turn_runs.py`
- Modify: `backend/tests/test_turn_runs.py`

- [ ] Add `POST /turn-runs`, `GET /turn-runs/{id}`, and `GET /events`.
- [ ] Run the existing `run_turn()` in a supervised background task.
- [ ] Assign monotonically increasing SSE IDs and retain a bounded replay buffer.
- [ ] Support `Last-Event-ID`, multiple reconnects, and explicit event-gap responses.
- [ ] Continue generation after an SSE consumer disconnects.
- [ ] Persist normal messages/state only through the existing game service transaction rules.
- [ ] Test model error, client disconnect, gap, backend restart, repeated submit, and simultaneous Mac/Android submit.

### Task 3.4: Migrate Vue to the shared transport when stable

**Files:**

- Modify: `frontend/src/api/sessions.ts`
- Modify: `frontend/src/composables/useGameTurn.ts`
- Modify: `frontend/e2e/test-server.ts`
- Modify: `frontend/e2e/mock_backend.py`
- Modify: `frontend/e2e/smoke.spec.ts`

- [ ] Generate one `request_id` per user send and retain it across transport retry.
- [ ] Create then consume a run; recover via message/state hydration on an event gap.
- [ ] Preserve all current narrative/tag/error/done behavior.
- [ ] Verify refresh/re-entry and failure recovery in Playwright.

**Gate 3 verification:**

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_session_turn_coordinator.py tests/test_turn_runs.py
.venv/bin/python -m pytest -q

cd ../frontend
npm test
npm run build
npx playwright test
```

Run a disconnect test proving one user message and one assistant message are committed.

## Phase 4 — Flutter foundation and connection lifecycle

### Task 4.1: Scaffold the Android-first Flutter project

**Files:**

- Create: `mobile/pubspec.yaml`
- Create: `mobile/lib/main.dart`
- Create: `mobile/lib/app.dart`
- Create: `mobile/analysis_options.yaml`
- Create: `mobile/android/...`
- Create: `mobile/test/...`

- [ ] Use Flutter stable and Riverpod.
- [ ] Add HTTP, secure storage, shared preferences, UUID, connectivity, mDNS, permission, QR scanner, Markdown, and package-info dependencies only when used.
- [ ] Define dev and release configuration without hardcoded production hosts or tokens.
- [ ] Add a basic theme and navigation shell; do not build gameplay placeholders beyond testable navigation.
- [ ] Confirm application ID, minimum SDK, network security policy, and release signing boundary.

### Task 4.2: Implement server metadata and secure credentials

**Files:**

- Create: `mobile/lib/connection/paired_server.dart`
- Create: `mobile/lib/connection/connection_store.dart`
- Create tests under `mobile/test/connection/`

- [ ] Persist non-secret server ID/name/recent hosts in preferences.
- [ ] Persist device tokens only through Android-backed secure storage.
- [ ] Support token rotation, forget, revoke response, and corrupted-storage recovery.
- [ ] Never include tokens in `toString`, logs, analytics, or route URLs.

### Task 4.3: Implement API and connection state

**Files:**

- Create: `mobile/lib/api/dzmm_api.dart`
- Create: `mobile/lib/api/api_error.dart`
- Create: `mobile/lib/connection/connection_controller.dart`
- Add fake-server unit tests

- [ ] Add authenticated JSON requests, timeout policy, structured errors, and cancellation.
- [ ] Model `offline`, `scanning`, `pairing`, `connected`, `reconnecting`, `revoked`, and `incompatible` states.
- [ ] Validate `server_id`, API version, and capabilities before using stored credentials.

### Task 4.4: Implement LAN scanner and sticky reconnect

**Files:**

- Create: `mobile/lib/connection/lan_scanner.dart`
- Create: `mobile/lib/connection/reconnect_service.dart`
- Add unit and physical-device tests

- [ ] Browse `_dzmm._tcp`, sweep `/24` with bounded concurrency, probe recent hosts, and allow manual entry.
- [ ] Emit incremental deduplicated results by `server_id`.
- [ ] Debounce network-change scans and update recent hosts after a successful identity match.
- [ ] Explain and handle denied nearby-network permissions.
- [ ] Validate at least two home-router configurations and one mDNS-blocking configuration.

**Gate 4:** a physical Android device rediscovers the same Mac after a DHCP address change without re-pairing.

## Phase 5 — Android pairing journeys

### Task 5.1: Build scan and manual-connect UI

**Files:**

- Create: `mobile/lib/features/pairing/connection_onboarding_page.dart`
- Create: `mobile/lib/features/pairing/lan_scan_sheet.dart`
- Create: `mobile/lib/features/pairing/manual_address_sheet.dart`
- Add widget tests

- [ ] Show instructions, scan progress, discovered hosts, compatibility, and paired status.
- [ ] Provide permission denial guidance and manual fallback.
- [ ] Do not treat HTTP 200 alone as compatible; validate the dzmm health schema.

### Task 5.2: Implement Mac-approval pairing

**Files:**

- Create: `mobile/lib/features/pairing/pairing_controller.dart`
- Create: `mobile/lib/features/pairing/approval_wait_page.dart`
- Add fake-server tests

- [ ] Create device UUID/name, submit request, and long-poll by request-specific secret.
- [ ] Handle approve, deny, expire, rate-limit, host-offline, and user-cancel.
- [ ] Save token and server identity atomically on approval.

### Task 5.3: Add QR and PIN fallback

**Files:**

- Create: `mobile/lib/features/pairing/qr_scan_page.dart`
- Create: `mobile/lib/features/pairing/pin_pair_sheet.dart`
- Add parsing/widget tests

- [ ] Parse only the dzmm pairing URI schema and validate expiry/server identity.
- [ ] Exchange a claim once; show a clear expired/used message.
- [ ] Use a six-digit OTP input and map bad/closed/rate-limited errors.
- [ ] Re-pairing replaces the old token for the same server/device.

**Gate 5:** approval, QR, and PIN each pair a fresh install; deny, expiry, QR replay, and PIN rate limiting all fail safely.

## Phase 6 — Android gameplay v1

### Task 6.1: Session home and hydration models

**Files:**

- Create: `mobile/lib/features/sessions/session_models.dart`
- Create: `mobile/lib/features/sessions/session_repository.dart`
- Create: `mobile/lib/features/sessions/session_list_page.dart`
- Add unit/widget tests

- [ ] List saves and enter one without exposing authoring actions.
- [ ] Show loading, empty, offline, revoked, incompatible, and retry states.
- [ ] Parse messages/state defensively for optional backward-compatible fields.

### Task 6.2: Reconnectable turn client

**Files:**

- Create: `mobile/lib/api/sse_client.dart`
- Create: `mobile/lib/features/game/turn_run_client.dart`
- Add parser/reconnect tests

- [ ] Parse multiline SSE data, IDs, comments/heartbeats, structured event types, and UTF-8 chunk boundaries.
- [ ] Create one request UUID per action and preserve it across retries.
- [ ] Reconnect with `Last-Event-ID` and exponential backoff capped at 30 seconds.
- [ ] On event gap, rehydrate messages/state rather than resubmit.
- [ ] On app resume, query active run status before enabling a new send.

### Task 6.3: Build the core game screen

**Files:**

- Create: `mobile/lib/features/game/game_page.dart`
- Create focused widgets under `mobile/lib/features/game/widgets/`
- Add widget and integration tests

- [ ] Render persisted user/assistant history and a streaming current turn.
- [ ] Render safe Markdown, dialogue/speaker sections, dice, choices, and diagnostics appropriate for players.
- [ ] Add multiline action composer, optional suggestion chips, send state, and session-busy recovery.
- [ ] Add compact vitals/inventory/NPC/goals/location access without copying desktop debug panels.
- [ ] Preserve scroll position while streaming and provide an explicit jump-to-latest action.
- [ ] Rehydrate on refresh/re-entry and after transport recovery.

### Task 6.4: Real-model playtest

- [ ] Use the desktop LM Studio `magnum-v4-22b` configuration through the Mac backend.
- [ ] Complete at least 30 turns on Android without directly calling LM Studio from Android.
- [ ] Verify narration/guide consistency, state changes, choices, errors, and recovery.
- [ ] Record model failures separately from remote transport failures.

**Gate 6:** fresh-pair-to-three-turn journey passes on a packaged Mac app and physical Android device.

## Phase 7 — Resilience, security review, and release

### Task 7.1: Recovery and lifecycle hardening

- [ ] Wi-Fi off/on during scan, pair, active SSE, and idle game.
- [ ] Android background/foreground during a long turn.
- [ ] Mac IP change, sidecar restart, remote disable, app close, and app reopen.
- [ ] Device revoke while connected and while offline.
- [ ] Duplicate tap, same request retry, and two-client simultaneous send.
- [ ] Decide from measured behavior whether a foreground-service notification is required for v1 or moves to P1.

### Task 7.2: Security review

- [ ] Route-policy test covers every FastAPI route.
- [ ] Inspect DB, logs, Android preferences, crash output, QR payload, and URLs for secret leakage.
- [ ] Verify PIN/QR/request expiration and rate limits under concurrent attempts.
- [ ] Verify public/non-private manual hosts are rejected by default.
- [ ] Document trusted-LAN HTTP limitations in Mac and Android UI/help.
- [ ] Review dependency licenses and known vulnerabilities.

### Task 7.3: Performance and soak testing

- [ ] Measure scan-first-result and full-sweep time on at least three routers.
- [ ] Test a save with 500 messages and decide whether pagination is needed before release.
- [ ] Run 100 turns with injected disconnect/reconnect events and assert no duplicate commits.
- [ ] Confirm memory stays bounded for turn event buffers and expired pairing requests.

### Task 7.4: CI and Android release path

**Files:**

- Create: `.github/workflows/android.yml`
- Modify: release documentation and `CHANGELOG.md` only when the feature is accepted

- [ ] CI runs `flutter analyze`, unit/widget tests, and release APK/AAB build.
- [ ] Keep signing secrets out of the repository and document local/internal signing setup.
- [ ] Upload an installable internal artifact with checksum.
- [ ] Keep desktop release workflow green after backend/Tauri changes.
- [ ] Decide Play distribution only after internal RC acceptance; it is not required for the first local install.

### Task 7.5: Final maturity review

- [ ] Score all eight dimensions from the spec with links to evidence.
- [ ] Require total ≥85 and every P0 dimension ≥80.
- [ ] Close all P0 defects or explicitly stop release.
- [ ] Produce the final Mac build, Android artifact, acceptance report, and known-limitations list.

## End-to-end acceptance matrix

| Journey | Expected result | Evidence |
|---|---|---|
| Mac opens on unknown Wi-Fi | Loopback only | Listener inspection + Settings screenshot |
| Enable remote | LAN health and mDNS available | Physical phone probe |
| Scan + Mac approve | Token stored securely, host connected | Android integration run |
| QR and PIN fallback | Each succeeds once; replay/rate limit denied | API + device tests |
| Enter existing save | History/state match Vue | Cross-client comparison |
| Complete turn | One persisted user/assistant pair and matching state | DB/API assertion |
| Wi-Fi drop mid-turn | Resume or hydrate; no duplicate | Injected disconnect test |
| DHCP address change | Same `server_id`, no re-pair | Router/device test |
| Simultaneous Mac/Android send | One accepted, one `session_busy` | Concurrency test |
| Revoke device | Next protected request denied | API/device test |
| Disable remote | LAN closed, local Vue healthy | Listener + browser test |
| Close Mac | Android shows offline and retains pairing | Physical-device test |

## Recommended commit boundaries

1. `test(remote): define route authorization contract`
2. `feat(remote): add server identity and paired devices`
3. `feat(remote): add pairing and discovery APIs`
4. `feat(desktop): add remote access control panel`
5. `feat(turns): add idempotent reconnectable turn runs`
6. `feat(mobile): add Flutter connection and pairing`
7. `feat(mobile): add Android gameplay client`
8. `test(mobile): add resilience and release acceptance`

Each commit must keep its relevant test set green. Do not combine security foundations, turn semantics, and the full Android UI into one unreviewable commit.

## Definition of done

- [ ] Spec P0 requirements implemented with no unapproved scope expansion.
- [ ] Backend full pytest and Ruff pass.
- [ ] Vue Vitest, production build, and Playwright pass.
- [ ] Flutter analyze, unit/widget/integration tests, and release build pass.
- [ ] Packaged Mac + physical Android acceptance matrix passes.
- [ ] Remote security route matrix passes with no plaintext-token evidence.
- [ ] 100-turn disconnect soak shows zero duplicate committed turns.
- [ ] Maturity score is at least 85 with no P0 dimension below 80.
- [ ] Release artifacts, checksums, limitations, and installation steps are recorded.

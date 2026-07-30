# dzmm Android Remote Client Design

> **Status:** Proposed  
> **Date:** 2026-07-30  
> **Branch:** `feature/android-remote-client`  
> **Target:** Android v1 + Mac remote-access control plane  
> **Reference:** PawTerm zero-config onboarding, LAN discovery, pairing, reconnect, and SSE patterns

## 1. Executive assessment

The feature is feasible without replacing the existing Vue interface or moving the game engine to Android. The Mac app remains the product's host: Tauri owns the FastAPI sidecar, SQLite data, model connections, and full Vue management UI. Android is an additional authenticated gameplay client on the same LAN.

The current code already has a useful foundation: Tauri can bind the backend to `127.0.0.1` or `0.0.0.0`, the API exposes session hydration and SSE turns, and the frontend API derives the backend host dynamically. It is not ready to expose safely, however: CORS is open, remote requests have no authentication or route restrictions, the boot-time LAN choice is not a persistent control plane, and the current POST-SSE turn is coupled to one network connection.

### Current readiness

| Dimension | Current | Evidence / gap | v1 target |
|---|---:|---|---:|
| Backend gameplay reuse | 82 | Sessions, messages, state, suggestions, and SSE already exist | 90 |
| Mac host lifecycle | 55 | `start_backend(lan_mode)` exists; no in-app runtime toggle/status | 88 |
| Remote security | 15 | Wildcard CORS, no device auth, no remote route allowlist | 90 |
| Discovery and pairing | 5 | Only manual LAN URL display exists | 85 |
| Mobile-safe turn transport | 32 | Streaming works; no request id, session lock, or reconnectable run | 88 |
| Android gameplay UX | 0 | No Android project | 85 |
| Reconnect and recovery | 18 | Reload can hydrate history; no server identity or network recovery | 85 |
| Build, release, and acceptance | 20 | Desktop CI exists; no Android CI/signing/device matrix | 85 |
| **Weighted overall** | **31** | Strong engine, incomplete remote product boundary | **86** |

The target is not achieved by UI work alone. Security, pairing, concurrency, reconnect, and release evidence are part of the product.

## 2. Problem statement

Today a player must remain at the Mac to use dzmm even though the game engine and model access can remain on that machine. The desired experience is to start dzmm on the Mac, explicitly enable LAN access, and play the same local save from an Android phone without duplicating models, worlds, or game state.

Simply binding FastAPI to `0.0.0.0` would expose model, authoring, debug, and destructive APIs to every device on the LAN and would still lose an in-flight turn when Wi-Fi changes. The feature therefore needs a controlled host mode, device pairing, a narrow remote capability boundary, and a mobile-safe turn protocol.

## 3. Goals

1. A new user can discover and pair an Android phone with a running Mac in no more than 90 seconds, without typing an IP in the normal path.
2. A paired phone can list saves, enter a game, restore history/state, submit actions, and receive streaming narration with the same persisted outcome as Vue.
3. Network interruption does not duplicate a turn. Reopening the app or reconnecting either resumes the active run or rehydrates its committed result.
4. LAN mode is opt-in, visible, reversible, and controlled entirely from the Mac Vue settings page.
5. Unpaired LAN clients cannot read saves or invoke gameplay/model/admin APIs; paired devices cannot access Mac-only management and debug APIs.
6. Android v1 reaches at least 85/100 on the maturity gate in section 16 before being called locally smooth.

## 4. Non-goals

- **No replacement of Vue.** Vue remains the complete local UI and management surface.
- **No model/world/framework/wizard management on Android v1.** Those workflows are complex, infrequent, and safer on Mac.
- **No cloud relay or internet access.** v1 supports trusted local networks only.
- **No independent Android backend or on-device model.** Closing the Mac app stops the host and Android becomes offline.
- **No iOS release in v1.** The Flutter structure may preserve portability, but only Android is tested and shipped.
- **No Windows remote host commitment in v1.** Existing Windows desktop builds must remain healthy, but the supported remote host and acceptance matrix are Mac-first.
- **No Web Admin or menu-bar-only controller.** Remote control lives inside the existing Mac app.
- **No full media parity in v1.** TTS, BGM/SFX, asset management, and portrait editing are follow-ups unless required for the core game screen.

## 5. Personas and user stories

### Host player

- As a player at my Mac, I want dzmm to start in local-only mode so that opening the app does not expose my data to the LAN.
- As a player, I want to enable remote access from Settings and see its status, address, and paired devices so that I remain in control.
- As a player, I want to approve, deny, or revoke a phone so that possession of the Wi-Fi password is not enough to access my saves.
- As a player, I want QR and PIN fallback options so that pairing still works when automatic approval or mDNS does not.

### Android player

- As a player on Android, I want to scan for my Mac and pair once so that later sessions reconnect without configuration.
- As a paired player, I want to select a save and continue from the latest committed history and state.
- As a player, I want narration to stream progressively and recover after a short Wi-Fi interruption.
- As a player, I want clear offline, host-closed, unauthorized, incompatible-version, generating, and retry states.
- As a player, I want duplicate taps or reconnect retries to produce at most one persisted game turn.

## 6. Scope by priority

### P0 — required for Android v1

- Mac starts the backend automatically on loopback; no startup mode chooser.
- Settings remote-access card with enable/disable, host status, LAN addresses, QR/PIN, pending requests, paired devices, and revoke.
- Stable `server_id`, API protocol version, capability discovery, mDNS, subnet-scan fallback, and manual address fallback.
- Phone-initiated approval, one-time QR claim, and six-digit PIN pairing.
- Per-device bearer token, hashed token storage on Mac, Android Keystore-backed secret storage, expiry/revocation behavior, and rate limiting.
- Loopback/admin/paired/public authorization classes with a strict remote gameplay allowlist.
- Session list, game entry, message/state hydration, action suggestions, action submission, streaming narration, structured dice/choice display, and refresh.
- Per-session single-writer coordination and client-generated `request_id` idempotency.
- Reconnectable turn runs with ordered SSE event IDs and explicit gap recovery.
- Network-change rediscovery by `server_id`, recent-host fallback, and user-visible connection state.
- Android CI for analyze/test/build plus signed internal-release artifact instructions.
- Real Mac + real Android acceptance on trusted Wi-Fi.

### P1 — fast follow

- Background/foreground notification while a long turn is running.
- Retry/edit-last-turn parity, NPC proactive-turn controls, goals/NPC/location detail panels, and richer state sheets.
- TTS playback using Mac-generated audio where practical.
- Tablet/landscape optimization and accessibility polish.
- Export/share current session from Android.
- Device rename and last-seen audit details.

### P2 — future

- TLS or an encrypted application transport for hostile LANs.
- Tailscale/custom network support with explicit public-address opt-in.
- iOS client, cloud relay, push notifications, and wake-on-LAN.
- Mobile authoring and model management.

## 7. Architecture decision

**Decision:** use a Flutter Android client, keep FastAPI as the single source of truth, and add a narrow remote-access control plane inside the existing Mac/Tauri/Vue application.

### Options considered

| Option | Delivery | PawTerm reuse | Native integration | Cross-platform path | Decision |
|---|---|---|---|---|---|
| Flutter + Riverpod | Fast | High | Sufficient | Strong | **Selected** |
| Kotlin + Compose | Medium | Low | Best | Android only | Rejected for v1 |
| Responsive Vue/PWA | Fastest initially | Low | Weak discovery/secure storage/background behavior | Web | Rejected as product boundary |
| Tauri mobile | Medium/high risk | Low | Immature for required discovery/reconnect flow | Possible | Rejected for v1 |

Flutter is selected because the highest-risk work is connection lifecycle rather than platform-specific UI. PawTerm already demonstrates the required Dart patterns for mDNS + subnet scanning, QR/PIN entry, stable server identity, reconnect, SSE parsing, and Android lifecycle handling. dzmm will reuse the patterns, not copy PawTerm's product-specific terminal or admin architecture.

## 8. System context

```text
┌──────────────────────────── Mac dzmm.app ─────────────────────────────┐
│ Tauri process                                                         │
│  ├─ starts/stops FastAPI sidecar                                      │
│  └─ defaults to 127.0.0.1; Settings may restart it on 0.0.0.0        │
│                                                                       │
│ Vue local client ── loopback ──► FastAPI ──► SQLite / models / engine │
│   Settings remote card             │                                  │
│   admin operations are local-only  └─ mDNS while remote access is on  │
└──────────────────────────────────────┬────────────────────────────────┘
                                       │ trusted LAN + device token
                                       ▼
┌──────────────────────── Android Flutter app ──────────────────────────┐
│ Discovery/pairing → secure connection store → session/game UI         │
│                           ↕ reconnectable HTTP + SSE                  │
└───────────────────────────────────────────────────────────────────────┘
```

Mac remains authoritative. Android never writes SQLite directly and never calls the model server directly.

## 9. Host lifecycle

### State model

```text
Mac app closed
  └─ open → local_starting → local_ready (127.0.0.1)
                         └─ enable remote → restarting → remote_ready (0.0.0.0 + mDNS)
remote_ready
  ├─ disable remote → restarting → local_ready
  └─ close Mac app → backend stopped
```

- The Mac app always starts in local-only mode, even if remote access was enabled during a previous run. This avoids silently exposing the backend on a new network.
- Paired-device records survive disabling remote access and app restarts.
- Enabling/disabling restarts only the sidecar, not the desktop UI. The Settings card shows progress and re-probes `/health` before declaring success.
- Disabling remote access while a turn is active must show a confirmation. The first implementation may reject the transition until active runs finish rather than kill a turn.
- mDNS starts only after the LAN listener is healthy and stops with the sidecar.

## 10. Identity, discovery, and pairing

### Server identity

- A random UUIDv4 `server_id` is generated once and persisted with app data.
- `/health` returns `version`, `api_version`, `server_id`, `remote_access`, and capability flags.
- `_dzmm._tcp.local` advertises `server_id`, app version, API version, and pairing availability only while remote access is enabled.
- Android deduplicates discoveries by `server_id`, never by IP.

### Discovery order

1. mDNS browse for `_dzmm._tcp.local`.
2. Concurrent `/24` subnet sweep of port `8765`, bounded concurrency and one-second probes.
3. Probe recent known hosts for the selected `server_id`.
4. Manual IP/hostname entry as a visible fallback.

Scanning must emit incremental results and may not block the UI. Android requests only the minimum nearby-network permissions required by its target SDK and explains why before the system dialog.

### Pairing methods

All methods issue the same long-lived device credential and bind it to `device_id`, `device_name`, and `server_id`.

1. **Mac approval (normal path):** Android submits a 60-second request. The Mac card shows device name and source IP; approve returns a token through a request-specific long poll. Deny and expiry are explicit.
2. **QR claim:** Mac creates a random, single-use, five-minute claim. The QR contains host candidates, port, server ID, API version, and claim—never an admin token or device token. Android exchanges it once.
3. **PIN fallback:** Mac opens a five-minute six-digit PIN window. Five failed attempts from one IP cause a 60-second cooldown; success closes the window.

Device tokens are at least 256 bits of randomness. The Mac stores only a SHA-256 token hash plus metadata; Android stores the plaintext token in platform secure storage. Re-pairing the same `device_id` rotates its token.

## 11. Authorization boundary

The backend classifies requests from the socket peer address. It does not trust `X-Forwarded-For` in v1.

| Request class | Credential | Allowed surface |
|---|---|---|
| Loopback local client | None | Existing Vue API + local remote-admin API |
| Unpaired LAN client | None | `/health` and bounded `/remote/pair/*` only |
| Paired Android device | Bearer device token | Explicit gameplay allowlist only |
| LAN admin attempt | Any | Always denied |

The paired-device allowlist initially contains read-only session hydration and the mobile-safe turn APIs. Model configuration, key references, wizard, world/framework authoring, debug chains, raw prompts, TTS administration, updates, file upload/delete, exports, and `/remote/admin/*` remain loopback-only.

CORS must no longer use wildcard origins. It permits the known Tauri origin and local Vite development origins. Native Android HTTP requests do not require CORS.

## 12. Remote API contract

### Public discovery and pairing

```text
GET    /health
POST   /remote/pair/requests
GET    /remote/pair/requests/{request_id}  (secret in `X-DZMM-Pair-Secret`)
POST   /remote/pair/pin
POST   /remote/pair/qr-claim
```

### Loopback-only administration

```text
GET    /remote/admin/status
POST   /remote/admin/pairing/pin
POST   /remote/admin/pairing/qr
GET    /remote/admin/pair-requests
POST   /remote/admin/pair-requests/{id}/approve
POST   /remote/admin/pair-requests/{id}/deny
GET    /remote/admin/devices
DELETE /remote/admin/devices/{device_id}
```

### Paired gameplay v1

```text
GET    /sessions
GET    /sessions/{id}
GET    /sessions/{id}/messages
GET    /sessions/{id}/state
GET    /sessions/{id}/locations
GET    /sessions/{id}/npcs
GET    /sessions/{id}/goals
POST   /sessions/{id}/suggest_actions
POST   /sessions/{id}/turn-runs
GET    /sessions/{id}/turn-runs/{run_id}
GET    /sessions/{id}/turn-runs/{run_id}/events
```

Every response uses stable machine-readable error codes in addition to a user-facing message. Android handles at least `unauthorized`, `revoked`, `remote_disabled`, `server_incompatible`, `session_busy`, `event_gap`, `run_interrupted`, `model_error`, and `session_not_found`.

## 13. Mobile-safe turn protocol

The existing `POST /sessions/{id}/turn` binds generation to one streaming request. Android v1 adds a transport that separates run creation from event consumption while preserving the same `run_turn()` engine and persisted messages/state.

### Create or recover a run

```json
POST /sessions/42/turn-runs
{
  "request_id": "client-generated-uuid",
  "action": "我检查门后的声音"
}
```

The unique key is `(session_id, request_id)`:

- First request creates a background run and returns `202 {run_id, status}`.
- Repeating the same request returns the same run and never creates another turn.
- A different request while the session is generating returns `409 session_busy` with the active `run_id`.
- Legacy Vue `/turn` and `/npc_tick` must use the same per-session coordinator until Vue migrates to `turn-runs`.

### Consume events

`GET /events` is SSE with monotonically increasing event IDs. The server keeps a bounded in-memory replay buffer for active/recent runs. Android reconnects with `Last-Event-ID` and exponential backoff.

- If the requested ID is available, replay missed events then continue live.
- If the buffer gap cannot be filled, return `409 event_gap`; Android reloads messages and state.
- The producer continues when an SSE consumer disconnects.
- Completion persists the normal assistant message/state and records `assistant_msg_id` on the run.
- On backend restart, previously running records become `interrupted`. Android shows recovery guidance and rehydrates committed history; it never silently resubmits with a new request ID.

This is transport hardening, not a second game engine.

## 14. Android information architecture

### Connection onboarding

1. Explain that the Mac app must be open and Remote Access enabled.
2. Request nearby-network permission when Scan is tapped.
3. Show incremental discovered hosts, version compatibility, and paired state.
4. Normal pairing waits for Mac approval; QR, PIN, and manual address remain available.
5. Store server metadata separately from the secure device token.

### Home

- Current Mac name and connection state.
- Save list ordered consistently with the backend.
- Empty, host-offline, token-revoked, and incompatible-server states.
- Connection management entry for rescan, re-pair, or forget.

### Game

- Virtualized chronological message list with Markdown-safe narrative rendering.
- Streaming current narration, speaker/dialogue segments, dice and choices.
- Multiline action composer with send disabled while this session has an active run.
- Suggested actions as optional chips, never blocking manual input.
- Compact state access for vitals, inventory, NPCs, goals, and location.
- Clear generating, reconnecting, recovered, failed, and refresh states.

Android does not reproduce every Vue debug or authoring panel.

## 15. Non-functional requirements

### Security

- Remote access off by default on every Mac app launch.
- No plaintext token in Mac DB/logs, Android preferences, QR, crash reports, or URLs.
- Constant-time token-hash comparison, rate-limited public pairing endpoints, bounded pending requests, and expiring claims.
- Private/link-local addresses only by default. Manual public addresses require a future explicit advanced mode.
- Threat model clearly states that v1 HTTP assumes trusted Wi-Fi and does not protect against an active LAN sniffer.

### Reliability

- At most one active mutating turn per session across Vue and Android.
- A client retry with the same `request_id` is idempotent.
- Network changes rediscover by `server_id`; IP changes do not create duplicate hosts.
- UI can always recover by reloading server-persisted messages and state.

### Performance

- Discovery shows the first host within three seconds on a normal home LAN.
- Pairing APIs respond within one second excluding user approval time.
- Narrative chunks render within 250 ms of arrival under normal conditions.
- A 500-message save can enter the game screen without a visible multi-second main-thread freeze. Pagination may be introduced if measurement shows it is needed.

### Compatibility

- `/health` exposes an integer `api_version` and capability set.
- Android blocks unsupported API versions before pairing/gameplay and explains the required desktop version.
- Existing loopback Vue workflows continue to pass their current tests.

## 16. Maturity gate

The Android feature is considered locally smooth only when the weighted score is at least 85 and no P0 dimension is below 80.

| Dimension | Weight | 85-point evidence |
|---|---:|---|
| Core gameplay completeness | 20% | Session entry, hydration, streaming turn, choices/dice/state all pass real-device journey |
| Connection and onboarding | 15% | Scan + approval + QR + PIN + manual fallback verified |
| Security and privacy | 15% | Route matrix tests, token storage review, revoke/rate-limit tests, no secret leakage |
| Reliability and recovery | 15% | Disconnect/reconnect, IP change, host restart, duplicate tap, event-gap recovery |
| UX clarity and accessibility | 10% | Loading/error/empty/re-entry states, readable touch targets, screen-reader basics |
| Mac host control | 10% | Default-local, enable/disable, status, device approval/revoke, active-turn guard |
| Performance | 5% | Discovery, render, and streaming budgets measured on target devices |
| Test/release readiness | 10% | Backend/frontend/mobile CI plus signed internal build and acceptance matrix |

### Release-blocking acceptance journeys

1. Fresh install: Mac local start → enable remote → Android scan → Mac approve → enter save → complete three turns.
2. QR fallback and PIN fallback each pair a fresh device; QR reuse and wrong-PIN rate limit fail safely.
3. Revoke the active Android device on Mac; its next protected request fails and gameplay data is not returned.
4. Disconnect Wi-Fi mid-turn, reconnect, and observe one committed turn with no duplicated player action.
5. Change Mac DHCP address, rescan by `server_id`, and reconnect without re-pairing.
6. Open the same save on Mac and Android; simultaneous sends produce one accepted run and one visible `session_busy`, not interleaved state.
7. Disable remote access, verify LAN is unreachable, and verify local Vue still works after loopback restart.
8. Close Mac app, verify Android reports host offline without losing its paired-server record.

## 17. Success metrics

Because dzmm is local-first, v1 does not require remote telemetry. Metrics are collected in acceptance runs and optional local diagnostics.

### Leading indicators

- ≥95% successful first pairing across the supported device/router matrix.
- Median scan-to-pair time ≤90 seconds.
- ≥99% turn-run completion in a 100-turn LAN soak test excluding model-provider failures.
- Zero duplicate committed turns in disconnect and repeated-submit tests.
- 100% unauthorized denial across the route-policy test matrix.

### Lagging indicators

- At least 10 real play sessions of 30+ minutes without a connection-related restart before public release.
- No P0 security or data-integrity defect during the release-candidate observation window.
- User-rated connection clarity and gameplay usability ≥4/5 in local acceptance.

## 18. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| HTTP bearer token can be observed on hostile Wi-Fi | Account/data exposure | Trusted-LAN scope, explicit warning, opt-in each launch, future encrypted transport |
| Android mDNS varies by OEM/router | Pairing failure | Bounded subnet scan, recent hosts, manual IP, QR host candidates |
| Sidecar restart interrupts a turn | Partial user experience | Active-run preflight/guard; persistent run status; explicit recovery |
| Two clients mutate one save | Corrupt/interleaved state | One session coordinator + request idempotency across all turn paths |
| SSE disconnect loses visible chunks | Confusing duplicate/retry | Detached producer, event IDs, replay buffer, hydration fallback |
| Flutter scope expands into desktop parity | Schedule slip | Enforce v1 non-goals and maturity gate on core journey |
| Backend API changes break Vue | Desktop regression | Additive endpoints, shared service layer, migrate incrementally, keep desktop CI green |

## 19. Open questions

These are non-blocking defaults unless the product decision changes:

- **Package/application identity:** use a dzmm-owned Android application ID before signing setup.
- **Minimum Android version:** default to the lowest version supported cleanly by the chosen Flutter/permission stack; validate on one low-end physical device.
- **Trusted-LAN warning frequency:** default to every enable action, with no permanent “never show again” in v1.
- **TTS scope:** keep out of P0 unless real playtesting shows text-only Android materially fails the intended experience.

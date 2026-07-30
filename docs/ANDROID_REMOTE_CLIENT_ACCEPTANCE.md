# Android Remote Client acceptance report

Status: **release blocked — physical acceptance remains open**
Branch: `feature/android-remote-client`
Draft PR: [#1](https://github.com/b31o8321/dzmm/pull/1)
Assessment date: 2026-07-31

## Scope and acceptance model

Android replaces the Vue gameplay surface only while connected to an opt-in
dzmm Mac host. The Mac remains the backend, database, model gateway, and remote
access controller. Android does not call LM Studio directly and does not expose
model, world, framework, wizard, debug, or destructive management.

The real-play acceptance model is
`huihui-ai_qwen3-14b-abliterated`. The running desktop configuration was
verified read-only as `type=lm_studio`,
`base_url=http://192.168.31.169:1234/v1`, and the desktop model check returned
`narrative_ok=true`. This proves provider/protocol availability, not the
required Android 30-turn journey.

## Current maturity score

| Dimension | Weight | Current | Weighted | Evidence and remaining gap |
|---|---:|---:|---:|---|
| Core gameplay completeness | 20% | 75 | 15.00 | Session hydration, streaming, choices, state, lifecycle, and 500-message widget tests pass; packaged-Mac/phone three-turn and 30-turn play are open |
| Connection and onboarding | 15% | 70 | 10.50 | Discovery, manual entry, approval, QR, PIN, secure persistence, and reconnect tests pass; two routers, mDNS-blocked LAN, and DHCP change are open |
| Security and privacy | 15% | 85 | 12.75 | Explicit route matrix, token hashing/redaction/storage tests, concurrent claim tests, OSV and license review pass; physical Android preferences/crash-output inspection is open |
| Reliability and recovery | 15% | 78 | 11.70 | Idempotent runs, event-gap E2E, terminal-lease ordering, 100-run disconnect soak, and app-resume check pass; real Wi-Fi/Mac restart/revoke injection is open |
| UX clarity and accessibility | 10% | 75 | 7.50 | Loading, empty, revoked, incompatible, retry, streaming, state, and jump-to-latest widgets pass; physical touch, screen-reader, rotation, and visual review are open |
| Mac host control | 10% | 80 | 8.00 | Default-local host controls, enable/disable, approval, QR/PIN, device revoke, Vue tests, and packaged-sidecar smoke pass; the packaged Tauri UI transition is open |
| Performance | 5% | 65 | 3.25 | 500-message history is lazy and replay buffers are bounded; packaged LAN startup took about 23 seconds, while target-phone discovery/render/chunk timing is unmeasured |
| Test and release readiness | 10% | 78 | 7.80 | Backend, Vue, Flutter, latest E2E/Android CI, downloaded checksummed artifacts, and sealed ad-hoc Mac bundle evidence exist; Developer ID/notarized Mac and signed Android RC plus physical acceptance are open |
| **Total** | **100%** |  | **76.50** | **Below 85; Core, Connection, and Reliability P0 evidence is below 80** |

The score is intentionally evidence-limited. Automated tests cannot award the
missing physical-network, target-device, signed-RC, or real-play points.

## Verified evidence

- Backend: 926 tests pass with one unrelated skip; Ruff passes.
- Vue: 9 Vitest tests and production build pass.
- Playwright: local SSE run/reload/event-gap recovery journey and
  [CI run 30575604869](https://github.com/b31o8321/dzmm/actions/runs/30575604869)
  pass.
- Flutter: analyze and 44 unit/widget tests pass.
- Android local builds: debug APK, unsigned release APK, and unsigned release
  AAB pass.
- Android CI: [run 30575604848](https://github.com/b31o8321/dzmm/actions/runs/30575604848)
  passed analyze, tests, all three builds, SHA-256 generation, and artifact
  upload.
- The latest CI artifact was downloaded locally; its installable debug APK,
  unsigned release APK, and unsigned AAB all match the included
  `SHA256SUMS`. The debug APK verifies with one Android Debug v2 signer;
  the release APK and AAB are confirmed unsigned.
- A fresh branch build produced `dzmm.app` and
  `dzmm_0.16.0_aarch64.dmg`; the DMG checksum is
  `febb68a7a516c47b3e09db899195e755952ac7ff1604a0eb995698ef21fc43c5`
  and `hdiutil verify` passes. Its complete ad-hoc signature seals 1,856
  resources and passes strict `codesign` verification, while Gatekeeper
  correctly rejects the non-Developer-ID build. The packaged sidecar starts
  against an isolated database in loopback mode and in LAN mode; LAN
  readiness took about 23 seconds.
- Transport soak: 100 runs each disconnect after the first event, resume from
  the cursor, and retry the same request ID; exactly 100 completed records and
  100 producer calls remain.
- Security: concurrent QR and PIN exchange each have exactly one winner; every
  hosted Pub package has a license file; OSV returned no known issue for the
  resolved Pub dependency graph.

## Release-blocking acceptance matrix

| Journey | Current evidence | Status |
|---|---|---|
| Mac opens on unknown Wi-Fi in loopback-only mode | Packaged sidecar listens only on loopback; Tauri launch transition is not clicked through | Blocked on packaged Tauri UI |
| Enable LAN remote access and advertise mDNS | Packaged sidecar listens on all interfaces and serves Vue; mDNS and UI control remain unverified | Blocked on packaged Tauri UI + phone |
| Scan and approve a fresh Android install | Fake-server/widget tests | Blocked on phone |
| QR and PIN fresh-install fallback | API/parser/widget tests | Blocked on phone |
| Enter an existing save and compare with Vue | Hydration/widget tests | Blocked on phone |
| Complete three turns without duplicate commits | API/E2E/soak tests | Blocked on packaged app + phone |
| Wi-Fi drop and app background during a turn | Replay/lifecycle tests | Blocked on physical injection |
| DHCP address change without re-pair | Stable-ID reconnect tests | Blocked on router/device |
| Simultaneous Vue and Android send | Coordinator tests | Blocked on cross-client journey |
| Revoke device and disable remote access | Backend/Vue tests | Blocked on packaged app + phone |
| Close/reopen Mac while retaining pairing | Persistence tests | Blocked on packaged app + phone |
| 30 turns with the selected LM Studio model | Model check only | Blocked on phone journey |

## Required path to 85

1. Complete the packaged Tauri UI transition, Developer-ID sign/notarize the
   Mac bundle, and produce a signed internal Android RC; record installation
   results.
2. Run approval, QR, PIN, deny, expiry, replay, revoke, disable, and app-restart
   journeys on a physical Android device.
3. Validate two home routers plus one mDNS-blocked path, including DHCP address
   change and manual fallback; record discovery timings.
4. Run Wi-Fi off/on, Android background/foreground, backend restart, duplicate
   tap, and simultaneous Vue/Android send while asserting persisted message
   counts.
5. Complete 30 Android turns with
   `huihui-ai_qwen3-14b-abliterated`, then the 100-turn physical disconnect
   soak; separate model-quality defects from transport defects.
6. Perform TalkBack/touch/rotation review and inspect Android preferences,
   crash output, URLs, Mac logs, and the temporary acceptance database for
   plaintext secrets.
7. Re-score all dimensions. Release only at total >=85 with every P0 dimension
   >=80 and no open P0 defect.

## Known limitations before RC

- Trusted-LAN HTTP is not safe for public, shared, or hostile networks.
- The current Mac test bundle is not distribution-ready: its complete ad-hoc
  signature passes strict `codesign`, but it has no Developer ID or
  notarization, so Gatekeeper assessment fails.
- Release APK/AAB builds are unsigned until an ignored internal keystore is
  supplied; the CI debug APK is for internal installation only.
- Flutter reports a future Built-in Kotlin migration warning for
  `mobile_scanner` and `nsd_android`; current Flutter 3.44 builds pass.
- Play distribution is intentionally undecided until internal RC acceptance.

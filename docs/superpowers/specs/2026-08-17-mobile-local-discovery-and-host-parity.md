# DZMM vNext mobile local discovery and Host parity

## Problem

The desktop Host can already approve a gameplay-only phone, but the current
phone flow depends on typing a LAN address. Local narrative play should open
the saved game after the player starts DZMM on their Mac or Windows computer,
without reconfiguring the phone.

## Goals

- Discover a LAN-enabled DZMM Host without entering an address in the normal
  first-pairing path.
- Persist an approved phone's Host identity, bearer credential and last Run in
  secure storage; after first pairing, select the most recently active gameplay
  Run without asking the player to copy a Run ID.
- Keep one identical Host contract for macOS and Windows.
- Preserve the vNext authority model: Android submits only current gameplay
  choices; Python remains the only state judge.

## Non-goals

- No cloud relay, sign-in, public Internet access or second Run/store model.
- No mobile World, lorebook, character-card, model, archive, purge or approval
  controls.
- No weakening of LAN allowlisting: only `/api/v2/mobile/*` is reachable from a
  non-loopback source.
- Bounded subnet sweeping remains a follow-up; QR and manual private-address
  entry are the implemented recovery paths in this phase.

## P0 user journey

1. On Mac or Windows the player opens DZMM, chooses **局域网玩法**, and the
   sidecar is healthy before it begins advertising.
2. Android asks for nearby-Wi-Fi discovery permission once, finds `_dzmm._tcp`,
   and shows only private IPv4 candidates.
3. The player selects a Host and requests pairing; the desktop user approves it
   locally. Android exchanges the one-time approval code for a bearer token,
   reads the limited active-Run picker and opens the most recent game. It then
   secure-saves Host URL, stable Host ID and selected Run.
4. A later Android launch first hydrates that stored Run. If the IP changed,
   mDNS finds the same Host ID, refreshes its address and retries. If the
   credential was revoked, the app clears it and presents a re-pair path.
5. If mDNS is denied or blocked, the player scans the desktop QR handoff or
   enters a private LAN address manually. The QR carries no credential and the
   Host retains its desktop-only controls.

## Acceptance criteria

- [ ] LAN enable starts exactly one `_dzmm._tcp.local.` advertisement after
  the sidecar listener is ready; disable/shutdown unregisters it.
- [ ] TXT metadata contains no token, approval code, model URL, world, Run or
  narrative data.
- [ ] Android discovery deduplicates endpoint candidates and rejects public,
  loopback and link-local addresses.
- [ ] The desktop QR handoff contains only a private Host URL and Host ID;
  Android rejects malformed/public payloads and still requires host approval.
- [ ] A successful approved pairing persists Host URL, Host ID, token and Run
  ID in secure storage; app restart restores the saved Run without retyping.
- [ ] The paired-only active-Run picker contains only run ID, world name, hero
  name, revision and update time; it never returns WorldDefinition, lorebook,
  character-card payload, model data or lifecycle controls. With one or more
  active Runs, first pairing opens the latest one without a manually copied ID.
- [ ] A DHCP/IP change restores only through the previously paired Host ID;
  discovered unpaired Hosts require explicit user selection and approval.
- [ ] Revocation yields 401, clears Android secure storage and never silently
  creates a replacement credential.
- [ ] macOS and Windows Host runs pass the same pairing, remote-allowlist and
  restart acceptance tests. Windows build uses a Windows-built PyInstaller
  sidecar and NSIS installer.

## Metrics and evidence

| Measure | Release target | Evidence |
| --- | --- | --- |
| First discovery | first Host in <= 3 s on normal home LAN | Android screen recording + timestamps |
| Returning player | saved Run hydrates with no address entry | Android restart recording |
| Recovery | DHCP change / Host restart recovers or explains fallback | Mac and Windows physical matrix |
| Security | remote management/model/world endpoints remain 403 | integration tests + packet/API log review |

## Follow-up

P1 adds a bounded subnet sweep for mDNS-blocked networks. It reuses the same
pairing endpoints and secure-session record and never adds mobile management
capabilities.

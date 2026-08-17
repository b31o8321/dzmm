# ADR-006: Local Host discovery and paired mobile recovery

**Status:** Accepted  
**Date:** 2026-08-17  
**Deciders:** DZMM product owner

## Context

DZMM vNext remains local-first: Mac or Windows Desktop owns the only v2 Host,
world authoring, model setup, Run lifecycle and mobile approval. Android is a
gameplay-only companion. Requiring a player to retype an IP address on every
launch is not a viable local-play experience, particularly after DHCP changes.

The solution must not create a cloud relay, second storage model, mobile
management surface, or a broad LAN API. A discovered endpoint is not trusted
merely because it is visible on the local network.

## Decision

When the desktop user explicitly enables **局域网玩法**, the sidecar binds to
`0.0.0.0` and advertises one `_dzmm._tcp.local.` service. Its TXT record is
limited to `host_id`, `api=v2`, `pairing=approval`, and
`capability=gameplay`. The Host identity is a stable, non-secret UUID scoped to
the isolated vNext data directory.

Android uses mDNS first. It presents discovered private IPv4 Hosts for a first
pairing, and can scan a desktop-generated QR handoff when discovery is
unavailable. The QR contains only a private Host URL and `host_id`; it never
contains a token and still requires local desktop approval. Manual address
entry remains the final fallback. On a successful approved pairing Android
stores `host`, `host_id`, bearer token and last Run ID in platform secure
storage. On the next launch it first hydrates the saved Host; if that endpoint
is unavailable, it looks for a matching `host_id`, updates the saved address
and retries hydration. A revoked token is deleted locally and requires a new
approved pairing.

macOS and Windows run the same Tauri lifecycle, sidecar environment, mDNS
record, token rules and remote allowlist. Windows packaging is native-only:
PyInstaller runs on Windows and Tauri emits an NSIS installer there.

## Options considered

| Option | Decision |
| --- | --- |
| mDNS first with saved pairing and manual fallback | Accepted: zero-entry normal path while preserving a reliable recovery path. |
| Fixed IP / manual address only | Rejected: fails after DHCP changes and does not meet companion-app onboarding quality. |
| Cloud relay/account discovery | Rejected: adds remote trust, account and data boundaries contrary to local-first scope. |
| Open LAN management API | Rejected: mobile must never manage World, model, deletion or pairing approval. |

## Consequences

- mDNS is best effort. Router/OEM multicast failures remain recoverable through
  QR or manual address entry; bounded subnet scan remains a follow-up and does
  not require exposing management APIs.
- The mobile client needs Android nearby-Wi-Fi permission for discovery. A
  denial leaves manual entry and existing saved addresses usable.
- `host_id` is an identity hint for reconnect, not a secret or a substitute for
  the approved bearer token. The trusted-LAN assumption remains explicit.
- The next release gate must include physical Mac/Windows Host, Android,
  DHCP-change, mDNS-blocked fallback, revoke and restart recovery evidence.

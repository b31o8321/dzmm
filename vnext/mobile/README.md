# vNext mobile

DZMM Mobile is the Android Local Host. It owns its app-private SQLite and
uses an embedded Python core as the only state judge. The phone calls its chosen
model provider directly and never requires a DZMM Mac/Windows Host, pairing,
QR handoff, LAN listener or remote token.

The remote-client implementation has been removed. The first Local Host slice
is: embedded CPython + local SQLite → schema-v3 compose
→ three constrained choices → ending → rollback → force-stop/reopen. Direct
model profiles retain the complete `type`, `base_url` and `model_name` bundle;
optional provider credentials are kept in Android secure storage and are only
passed to the embedded runtime for the single request that needs them;
the core rejects malformed/empty protocol responses before state commit.

Cross-device continuation is explicit export/import/clone, never automatic DB
sync or concurrent writes to one Run. See ADR-008 and the Local Host spec.

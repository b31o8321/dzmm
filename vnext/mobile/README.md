# vNext mobile

DZMM Next Mobile is the Flutter Android gameplay-only client. It pairs with a
vNext desktop Host and never manages models, worlds or data deletion.

The first playable vertical slice supports local-Host discovery/manual entry,
desktop-side approval, secure token storage, automatic recovery of the most
recent active Run and server-planned story choices. The phone receives only a
minimal active-Run picker (world name, hero name and state revision), not World
definitions, lorebook content or model configuration. It never sends an
arbitrary narrative command: it only submits the current choice ID and expected
revision to the Python Host.

The desktop Host currently uses authenticated HTTP on the local network. Android
therefore explicitly permits cleartext traffic for the user-selected Host. Do
not enter an untrusted network endpoint; a future TLS/QR discovery upgrade may
tighten this boundary without broadening mobile authority.

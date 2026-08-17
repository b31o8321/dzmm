# vNext mobile

DZMM Next Mobile is the Flutter Android gameplay-only client. It pairs with a
vNext Mac Host and never manages models, worlds or data deletion.

The first playable vertical slice supports manual local-Host entry, Mac-side
approval, secure token storage, current Run recovery and server-planned story
choices. The phone never sends an arbitrary narrative command: it only submits
the current choice ID and expected revision to the Python Host.

The Mac Host currently uses authenticated HTTP on the local network. Android
therefore explicitly permits cleartext traffic for the user-selected Host. Do
not enter an untrusted network endpoint; a future TLS/QR discovery upgrade may
tighten this boundary without broadening mobile authority.

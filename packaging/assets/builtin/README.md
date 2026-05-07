# Builtin Assets

Image / audio resources shipped with dzmm and seeded on first run via `seed_builtin_assets()`.

## Layout

```
packaging/assets/builtin/
├─ README.md          (this file)
├─ manifest.json      (registry — what gets seeded)
├─ images/
│  ├─ world_covers/   (5 expected: fantasy/modern/scifi/postapoc/school)
│  ├─ npc_avatars/    (30+ expected, named e.g. warrior_01.jpg)
│  └─ scenes/         (20 expected, named e.g. tavern.jpg)
└─ audio/
   ├─ bgm/            (12 expected, named e.g. tense_01.mp3)
   ├─ ambient/        (10 expected, named e.g. rain.mp3)
   └─ sfx/dice/       (28 expected for v0.9 — see v0.9 plan)
```

## Manifest format

Each entry in `manifest.json`:

```json
{
  "builtin_id": "world_cover_fantasy_01",
  "kind": "image",
  "file": "images/world_covers/fantasy_01.jpg",
  "mime": "image/jpeg",
  "width": 1024,
  "height": 576,
  "duration_ms": 0,
  "title": "中世纪奇幻 · 王城远眺",
  "tag": {"category": "world_cover", "genre": "fantasy"}
}
```

`kind`: `image` | `audio` | `font`
`tag.category`: `world_cover` | `npc_avatar` | `scene` | `bgm` | `ambient` | `sfx`
`tag` may carry additional facets used by frontend filters:
- NPC avatars: `archetype: "warrior" | "rogue" | ...`
- BGM: `mood: "tense" | "calm" | "battle" | ...`
- Ambient: `subtype: "rain" | "fire" | "market" | ...`
- SFX (v0.9): `subtype: "dice"`, `dice_category`, `dice_outcome`

`builtin_id` is the unique key used by `seed_builtin_assets` to detect already-seeded entries; never reuse a `builtin_id` for different content.

## Adding new builtin assets

1. Drop the file into the right `images/` or `audio/` subdir.
2. Append a new entry to `manifest.json` with a fresh `builtin_id`.
3. Restart backend → seeder picks it up. Idempotent — already-seeded entries are skipped.

## License / attribution

This pack is intentionally empty in v0.8.0 — the system works with user-uploaded content alone. A curated CC0 / CC-BY pack will land in a follow-up release once sources + attributions are finalized.

When adding content, prefer:
- **Images**: CC0 (Pexels / Pixabay / Unsplash). Process to ≤1024px wide, JPEG/WebP, ≤200KB each.
- **Audio**: CC0 (Pixabay / freesound.org). Process to mono 96kbps MP3, ≤200KB each.
- **Total pack size goal**: ≤25MB to keep the desktop installer slim.

For each non-CC0 asset, document attribution per file in this README.

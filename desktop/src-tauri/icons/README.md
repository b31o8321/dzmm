# DZMM vNext unified app icon

`icon.svg` is the canonical cross-platform mark. It depicts an open narrative page
whose single story line branches into visible state nodes: DZMM supports interactive
stories, but the Host remains the source of truth for state transitions. It deliberately
does not refer to Fog Harbor, a gate, a particular character, or TRPG alone.

The generated desktop assets are `icon.png`, `icon.icns`, and `icon.ico`. Android uses
the corresponding rendered `ic_launcher.png` files under
`vnext/mobile/android/app/src/main/res/mipmap-*`.

Regenerate all variants from the canonical SVG with:

```bash
cd vnext/desktop
npx tauri icon src-tauri/icons/icon.svg -o /tmp/dzmm-vnext-icon
```

Copy `icon.png`, `icon.icns`, and `icon.ico` into this directory, then copy the rendered
`android/mipmap-*/ic_launcher.png` files into the Flutter Android resource directories.

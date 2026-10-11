# DeckGrade

A [DeckyLoader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the Steam Deck that lets you tune the display's **saturation**, **contrast**, and **vibrance** from the Quick Access menu. More display controls are planned.

## Screenshots

| Before | After |
| :---: | :---: |
| ![Before](screenshots/Off%201.png) | ![After](screenshots/On%201.png) |
| ![Before](screenshots/Off%202.png) | ![After](screenshots/On%202.png) |
| ![Before](screenshots/Home%20Off.png) | ![After](screenshots/Home%20On.png) |

## Features

- **Saturation** (0–200%, 100 = neutral) — boosts or drains color intensity; 0% is full grayscale.
- **Contrast** (0–200%, 100 = neutral) — raises or lowers contrast around the midtones.
- **Shadows** (-100–100%, 0 = neutral) — brightens or deepens dark areas, with little effect on bright ones.
- **Highlights** (-100–100%, 0 = neutral) — brightens or tames bright areas, with little effect on dark ones.
- **Vibrance** (0–100%) — drives the native gamescope color vibrance engine, the same one behind the built-in SteamOS *Color Vibrance* setting.
- **Per-game profiles** — the running game (detected by its Steam AppID) gets its own profile independent of the global one. When a game without a profile starts, the global profile applies as a fallback. Game profiles can be reset to neutral defaults or re-synced to the current global profile with one tap.
- Master enable toggle, one-tap reset of the active profile to defaults.
- Settings persist across reboots and are reapplied automatically; a background watchdog restores them if gamescope restarts or another component overwrites the values.
- Disabling the plugin or uninstalling it restores default display output.

## Usage

1. Open the Decky menu from the Quick Access button (...) in Game Mode.
2. Select **DeckGrade**.
3. Make sure *Enable display tuning* is on, then adjust the sliders — changes apply live.
4. While a game is running, switch to its profile to save a game-specific look: it is remembered by the game and re-applied automatically the next time that game is running.

Notes:

- DeckGrade only works in **Game Mode**, where the gamescope compositor is running. In Desktop Mode the panel shows a notice; settings changed there are saved and applied automatically once you return to Game Mode.
- The Vibrance slider writes the same property as SteamOS's own Color Vibrance setting. While DeckGrade is enabled, its value is kept authoritative; if you want to use the system setting instead, disable DeckGrade first.
- Saturation and contrast currently affect **SDR content only** (HDR/PQ content is left untouched by design).
- Game profiles only work in **Game Mode** (the active-game AppID comes from the gamescope compositor, which is only running there). In Desktop Mode the global profile always applies.

## How it works

SteamOS renders everything through the **gamescope** compositor. Even though the session is Wayland-based, gamescope hosts an XWayland server and reads control values from its X11 root window properties (the same channel Steam itself uses). DeckGrade's Python backend talks to gamescope through those properties via `xprop` — no compiled binaries, no root required.

| Control | Mechanism |
| --- | --- |
| Saturation | Baked into a generated 3D LUT (`.cube`) and loaded by gamescope via the `GAMESCOPE_COLOR_LOOK_G22` "look" property. Applied at scanout time with no latency cost. |
| Contrast | Same generated 3D LUT as saturation. |
| Shadows / Highlights | Same generated 3D LUT (endpoint-preserving tone curves). |
| Vibrance | Native gamescope `GAMESCOPE_COLOR_SDR_GAMUT_WIDENESS` property. |

**Per-game profiles.** The backend reads gamescope's `GAMESCOPE_FOCUSED_APP_GFX` root property — the base-layer AppID of the focused game (base-layer AppIDs are only exposed in Steam Mode, which is fine: that is the only mode DeckGrade applies to). The Steam dashboard itself has the fixed AppID `769`, which DeckGrade treats as "no game", so the global profile stays active on the dashboard. A game's profile is created the first time you edit or reset it, and its values are stored under that AppID in the settings file.

## Requirements

- SteamOS 3.5+ (gamescope ≥ 3.12) and [DeckyLoader](https://decky.xyz/) installed.
- `xprop` (ships with SteamOS).

## Installing

### Method 1 (recommended)

Download the latest release zip and install it through Decky Settings, Developer options, Install Plugin from ZIP File.

### Method 2

Download the latest release zip and install it through Decky Settings, Developer options, Install from URL, or extract it to `/home/deck/homebrew/plugins/` so you end up with `/home/deck/homebrew/plugins/DeckGrade/` and restart the loader:

```bash
sudo systemctl restart plugin_loader
```

Expected zip layout (only needed if packaging by hand):

```
DeckGrade/
├── dist/index.js
├── main.py
├── package.json
├── plugin.json
├── LICENSE
└── README.md
```

## Troubleshooting

- Plugin log: `/home/deck/homebrew/logs/DeckGrade/plugin.log` (detection probes, applied values, xprop errors).
- Loader log: `sudo journalctl -u plugin_loader` (or `journalctl --user -u plugin_loader` for user-service installs).
- Manual check from SSH while in Game Mode — each should list `GAMESCOPE_*` properties on the display gamescope hosts:

  ```bash
  xprop -display :0 -root | grep -m3 GAMESCOPE_
  xprop -display :1 -root | grep -m3 GAMESCOPE_
  ```

## Building

Requirements: Node.js v16.14+ and pnpm v9 (`sudo npm i -g pnpm@9`). On Windows the build runs natively (Node and pnpm on PATH) or under WSL2.

One-stop build from the repo root — installs dependencies, builds the frontend to `dist/index.js`, and packages the distribution zip at `out/DeckGrade-v<version>.zip` (+ `.sha256`), verifying it against the source tree:

```bash
./build.sh        # Linux / macOS / WSL
build.bat         # Windows (cmd)
```

Subcommands (both scripts): `all` (default, build + package), `frontend` (pnpm install + rollup only), `package` (zip only, needs Node), `env` (print the detected toolchain).

The Python backend (`main.py`) needs no build step.

## License

BSD-3-Clause, see [LICENSE](LICENSE). Based on the [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template).

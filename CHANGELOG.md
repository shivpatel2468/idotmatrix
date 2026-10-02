# Changelog

## Unreleased

- **Renamed DotDeck → DeskDot** (`uv run deskdot serve`). `dotdeck.toml`, `DOTDECK_*` and old studio preferences
  still work.
- **System search bars:**
  - `deskdot launcher`: a Spotlight-style window on Ctrl+Alt+Space with a tray icon (Windows; also macOS/Linux).
  - DeskDot Bar: a native macOS menu-bar app with an ⌥Space command bar.
  - A Raycast extension.
  - See docs/LAUNCHERS.md.
- **Fruit fly:**
  - brain tuning (`/api/fly/config`, six personality presets);
  - plays all 21 pilot games through per-game lures (smell cues);
  - a one-click Let the fly play / Take back control on every page, in Play mode, in the command palette and on F;
  - five 3D brain views (connectome cloud, tower, radial wheel, spike raster + scope, neural web);
  - resizable sides;
  - full screen with camera angles, a cinematic camera and a "both" layout.
- **Colour calibration and motion lab:**
  - guided A/B matching with test videos on the panel and screen;
  - display-style presets, Claude presets and advanced options;
  - motion tests with a guided "find my smoothest" and auto-tune.
  - See docs/CALIBRATION.md.
- **Intro/outro themes:** Sunset (default), Circuit, OG (the original LED fly-in) and Off, under Settings → Display.
  The logo now uses warm neon colours.
- **Compatibility:**
  - settings and apps that can't work on the host OS are badged and disabled;
  - Linux now-playing (MPRIS) and active app (X11);
  - fixes for an Android crash, a macOS notifications DB issue and the BlueZ MTU;
  - see docs/COMPATIBILITY.md.
- **Website:** separate pages, a page and a real animated preview for every app, and Netlify config.
- **idotmatrix branding:** a neon LED logo ("i" pink, "dot" amber, "matrix" cyan) that builds, strikes and loops in the
  header, plus sealed 50/50 intro/outro doors.
- **Roaming fly:** a fly on every page; click it and it takes over the current game.
- **Phone controller:** a join flow with character select (name, colour, avatar, team, ready), a live lobby roster
  shown on phones and the panel, better controls, and reconnects that keep your seat.
- **New idotmatrix.com site:**
  - an "AI agent" setup prompt and a step-by-step guide;
  - an apps explorer covering every app and setting, generated from the code by `scripts/build_site_data.py`.
- **Fix:** the calendar timeline hid a meeting in progress just after midnight.
- 🪰 **Fruit-fly brain** (`deskdot.fly`), a real-time model of the fly's visual circuit:
  - the pathway runs from T4/T5 motion detectors, through lobula-plate HS/VS cells and LPLC2 looming detectors to
    the giant fibre and the descending neurons;
  - it sees only the panel's pixels.
  - New **Fly Brain** app.
  - New **"Plays itself with: Fruit-fly brain"** option on every game.
  - Tested against classic fly-vision experiments. See [docs/FLY_BRAIN.md](docs/FLY_BRAIN.md).
- 🪰 **3D Fly view** in the studio:
  - when a fly plays, the side panels slide shut and two live three.js scenes open beside the panel: the fly's
    visual circuit firing, and a 3D fly stomping the keys its neurons press, with a keystroke log;
  - graphics settings: quality presets with Auto adapting to the GPU, fps cap, bloom, particles, shadows, themes,
    cameras, fly and keyboard styles;
  - three.js loads only when the view opens.
  The panel now shows only the game: the Fly Brain app's neuron strip and eye inset moved to the studio. New
  `GET /api/fly`.
- Studio:
  - a full-screen now-playing view, like a music player's;
  - a resizable playback dock that re-flows into grids when tall.
- Device: a Bluetooth connect that hangs (seen after Windows sleep) is abandoned and retried, so the panel no
  longer stays disconnected.

## 3.2.0 — 2026-10-01 (first public release)

**Games & multiplayer**
- 22 games on a shared `GameApp` framework:
  - modes for 1–4 players: versus, co-op, free-for-all and teams;
  - maps and genre themes, chosen from each game's home menu (press **B**);
  - a FIFA-style side-select screen, intro countdown, results screen and a red damage flash.
- Local Wi-Fi multiplayer:
  - the panel shows a QR code and friends' phones become controllers;
  - seven phone layouts (d-pad, analog stick, swipe, tap zones, keyboard, gamepad, tilt), with latency readout,
    vibration and left-handed mode;
  - host-side keyboard (two players can share one) and gamepads in the studio.
- Light Cycles, Dig World, Neon Heat, Street Surge, Leaf Leap, Four Up and X and 0 joined the arcade. Snake became a
  full game with battle, teams and co-op modes.

**Smooth & readable on the real panel**
- Every animated app was reworked for the hardware:
  - seamless loops at even frame rates (≤ 10 fps);
  - sub-pixel motion that glides instead of stepping;
  - no popping;
  - GIFs that fit the 40 KB budget without dropping frames.
  Seamless-loop tests now cover every clip app.
- Clarity pass on every app:
  - hero elements stand out;
  - backgrounds never run through foreground objects;
  - dark tones are lifted above the panel's gamma floor;
  - text keeps its margins.
- Weather, Flight Radar, Player Card and Font Lab are now baked clips instead of high-fps streams.

**Studio**
- Match setup in Play mode (mode, players, map, theme) and a live side-select screen.
- Display popover: Glow / Pixel / LED preview looks plus a sharpness slider.
- Resizable settings panel; the form re-flows into two columns when wide.
- Schema-driven settings grouped into Game, Graphics and Game flow.

**Hosting**
- 🧪 **Android app (beta)**: the whole engine runs on a spare Android phone (Chaquopy + a Kotlin BLE bridge) as an
  always-on foreground service. See [docs/adr/0011](docs/adr/0011-android-host-app.md).
- Hand-off to the panel's built-in clock or a baked loop on exit and on Windows sleep.
- Raspberry Pi installer (`scripts/install-pi.sh`).

**Privacy**
- The panel's MAC moved out of the code into the local, git-ignored `deskdot.toml`.
- Secrets are masked in every API response and snapshot.

## 3.1.0 — 2026-09-27

- Presets: one-tap playlists (all games, all pets, desk dashboard…), plus API and MCP tools.
- 25 new apps from a survey of 1,890 public APIs (quakes, rain radar, air quality, space, trivia, currency…).
- Shared location for every location-aware provider; world-map masks.
- Pet World: rooms and a park with football, baked as smooth clip chunks.
- The panel freeze from frequent GIF uploads is fixed with a cool-down and rate-limited re-bakes.

## 3.0.0 — 2026-09-24 (the rebuild)

- Rebuilt from scratch as a layered engine:
  - async Python engine with a latest-frame-wins BLE scheduler, paced packets and ack flow control;
  - its own protocol encoders, pinned by byte-level tests;
  - schema-driven apps and a React studio;
  - an MCP server for AI agents.
- Every Bluetooth rule verified on hardware ([docs/HARDWARE_PROTOCOL.md](docs/HARDWARE_PROTOCOL.md)).

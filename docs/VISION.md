# Product vision

## One line

**DeskDot makes a $30 32×32 LED panel the most glanceable screen on your desk** — alive with the things you
care about, programmable by you and by your AI agents, and beautiful at 1,024 pixels.

## The problem with the product as shipped

The iDotMatrix panel is sold as a novelty: a phone app pushes one GIF or a clock, and it sits there. The
v2 "Studio Pro" build proved the panel can do far more (lyrics, telemetry, scores), but it was one 1,500-line
file that polled everything every 1.8 s, blocked its own event loop, re-searched lyrics every loop, streamed
frames without backpressure and hand-built UI for each feature. It felt laggy because it *was* laggy.

## Who it is for

| Persona | Wants | Signature moment |
| --- | --- | --- |
| **The builder at a desk** | Ambient status without switching windows | Build finishes; the panel flashes a green banner while they're still reading Slack |
| **The music listener** | Spotify on something physical | Karaoke-synced lyrics landing on the beat |
| **The AI-agent user** (Claude Code, etc.) | To know what the agent is doing without watching the terminal | The Claude mascot switches from *working* to *needs input* and they look up |
| **The pixel artist / tinkerer** | A canvas and an SDK | Draws in the studio, sees each stroke light up instantly; ships a plugin in 30 lines |

## Principles (in priority order)

1. **Instant.** A click in the studio shows on the panel in well under 200 ms. The panel is never more than
   one frame behind the engine (latest-frame-wins, no queues).
2. **Glanceable.** Every screen has one hero element readable from 2 m. Designed at 32×32, never scaled down.
3. **Calm.** Nothing blinks without meaning. No pairing screens, no mode-switch flicker during live content.
4. **Limitless by construction.** Apps are plugins with a schema; the studio and the MCP server discover them.
   New capability = one Python file, zero frontend work.
5. **Agent-native.** Anything a human can do in the studio, an agent can do over MCP, and it can *see* the result.
6. **Local-first.** No accounts, no cloud, no API keys for the built-ins. Works offline except for data feeds.
7. **Beautiful.** The panel and the studio are designed objects. The studio's centrepiece *is* the panel.

## What exists (v3.0)

- **Engine**: async runtime, app scheduler with playlist, focus take-over and relevance skipping,
  notification overlays, transitions (cut/push/fade/wipe), stream / clip / native output routing,
  resilient BLE link with automatic reconnect and state replay, simulator.
- **Apps**: Clock (4 faces) · Weather (animated) · System Monitor · Crypto Ticker (real sparklines) · Live Scores
  (11 leagues, team colours) · Now Playing (art, split, karaoke lyrics, media controls) · Gallery (uploads,
  photo calibration) · Canvas (live painting) · Text (auto-fit, smooth scroll, effects) · Claude Mascot (7 agent
  states) · Ambient (8 generative effects) · Focus Timer (Pomodoro/countdown/stopwatch) · Firmware Modes.
- **Studio**: live LED-accurate preview with bloom, schema-driven inspector, playlist dock with drag & drop,
  command palette, notification composer, drag-and-drop uploads, painting tools, responsive to phone width.
- **MCP**: 15 tools including `panel_snapshot` (the agent sees the panel), pixel art, notifications, agent state.
- **Integrations**: REST for scripts/CI, Claude Code hooks, drop-in plugin folder.

## Added in v3.1 (after the first hardware session)

Hardware-verified link fixes (paced packets, correct PNG header, ack flow control, one-frame pipeline, GIF budget);
guarded power switch; Active App with real icons; Text Studio (direct manipulation on the preview); Visualizer;
Screen and Camera Mirror with full image controls and face tracking; Snake; GitHub Graph; Countdown; Scores
layouts, 16 leagues and goal celebrations; Autopilot; four new ambient effects; MCP `compose` and `autopilot`.

## Added in v3.2

- **Studio**: boot animation with tips, resizable panes (drag the dividers), a library of live animated previews with
  category chips, favourites and a size slider, an "opening" overlay with tips, tabbed Settings (Display Hz & night
  mode, 5-question colour calibration wizard, OS notifications, Autopilot, audio source, location, panel), a link
  switch separate from the eject-guarded display power, Flight Radar click-to-inspect, a magnifier for mirrors.
- **Apps (41)**: Pet (53 original characters × 13–19 animations, scenes, accessories, dances to music) · Pet World
  (lofi scrolling worlds — room, park, beach, space, city, café — with day/night, weather, a buddy and football) ·
  13 self-playing games (Pong, Breakout, Tetris, Flappy, Dino, 2048, Invaders, Maze, Racer, Asteroids, Infinity,
  Mines, Starship) · Stocks (Yahoo, 5 layouts, alerts) · Live Scores rebuilt (27 leagues across 10 sports, scroll or
  focus, standings) · Now Playing rebuilt (word-by-word karaoke, 11 layouts, art palette, macOS backend) · Flight Radar
  · Emotes · Player Card · Font Lab · 8 more clock faces.
- **Engine**: panel colour calibration applied to every frame and clip, OS notifications on the panel, night mode,
  refresh-rate control.

## Added in v3.3 — the public-APIs pass

15 apps built on keyless public APIs (survey and reasoning in [PUBLIC_APIS.md](PUBLIC_APIS.md)): Earthquakes · Rain
Radar · Air Quality · Holidays · Space (launch countdown, live ISS, people in space, news) · Sun & Moon · Daily Dose ·
Trivia · Headlines · Currency · Photo Frame · Pokédex · Pixel Avatar · Chess Puzzle · Game Deals — 56 apps in total.

## Added in v3.4 — research-driven (Tidbyt / AWTRIX / LaMetric / Home Assistant demand)

- **Platform**: hand-off to the panel's firmware (clock or a baked app loop) on exit, sleep and on demand; On-Air
  light (webcam/mic in use by any app); corner status indicators; AWTRIX-compatible custom push apps; ntfy.sh
  phone pushes; Home Assistant bridge; eye-break nudge; secrets redacted from every API; Raspberry Pi installer.
- **Apps (76)**: Day & Night · Progress · Five O'Clock Somewhere · Planets Tonight · What to Wear · Tides & Surf ·
  QR Code · Habits · Calendar (ICS) · Loops (pixel cat, glyph rain, warp, Life, bouncing logo) · CI radiator ·
  Uptime · OBS · 3D printer · Plex/Jellyfin · Anki · HA entity · custom push apps.
- **Smoothness**: Pet World and Pet play as baked native loops (not limited by Bluetooth), streaming only for live
  music sync.

## Where it goes next

See [ROADMAP.md](ROADMAP.md). Headline bets: calendar & focus-aware scheduling, home-automation bridges
(Home Assistant / MQTT), a marketplace-style plugin index, multi-panel walls, audio-reactive visuals
from the PC's output, and an on-device "screensaver" set uploaded as native GIFs for when the PC sleeps.

## Non-goals

- A general-purpose display server for large matrices (we optimise for exactly 32×32 and this panel).
- A cloud service or mobile app. The studio is responsive; use it from a phone on the LAN.
- Pixel-perfect emulation of the vendor app.

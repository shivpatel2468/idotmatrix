# Changelog

## Unreleased

- 📺 **TV view** (docs/TV_VIEW.md): any screen — a smart-TV / Fire TV browser, a tablet, a projector — shows a
  1920 × 1080 broadcast of what DeskDot is playing. Studio: Create → **Show on TV** (QR + code, up to 8 screens);
  `/tv/<code>` on the LAN (LanGate allows `/tv/`), and over the internet in the web app through the WebRTC tunnel.
  Bespoke scenes for all 10 casino tables (full roulette layout with every player's chips, wheels, dice, cards,
  Housie board, slot cabinet) and for every game family (scores per seat, lives, teams, turn, winner banner,
  controls legend, scan-to-join), a beautiful LED panel for everything else.
- 🎯 **TV ↔ panel sync:** the TV gets the drawn outcome only from the lock (bets frozen) as a TV-only `tv.reveal`
  and replays the panel's own motion 1:1 (roulette ball/wheel, Big Six, dice, reels, card deals) on a slewed clock;
  rebuilt for 60 fps on a Fire TV Stick (pre-rendered wheel spun by CSS transforms, static layers). A rubber
  **stamp** marks the winning number/tile. The TV top bar and page follow the table theme.
- ⏱️ **One shared clock on every device:** public `status.clock` anchors (`phase_at`, `lock_at`, `ends_at`,
  `reveal_at`…) and `pong.server_time`; phones, the studio and the TV count down and flip at the same moment.
- 🎨 **Casino theme everywhere:** every colour on the phone page and the studio's casino view (buttons, sheets,
  rules, tour, toasts, the studio's own controls inside `.cz`, the browser bar) derives from the table theme, with
  AA-checked derived tokens; the host's theme change re-colours every device at once.
- 🖱️ **Laptop as a friend:** mouse betting fixed on the phone page (pointer capture stole rack clicks, right-click
  bet on roulette, unthrottled pointermove lagged); one click = one chip, drag works, right-click does nothing.
- 🪙 **Host chip animations** in the studio's Play tab (fly, stack, drag-and-drop, take back, others' chips drop in)
  and **the live panel on every phone** during no-more-bets / spin / result (opt-in binary frames on `/ws/p/`).
- 🪙 **Casino key:** a gold **Casino** key in the top bar on every app and the library's **Casino** category both
  enter casino mode (reopening the last table), with a silver **coin drop** animation; gold "Leave casino".
- ✨ **Animated DeskDot LED logo everywhere** (studio header, every intro, TV, phone pages, join and landing cards),
  two shades ("Desk" rose, "Dot" gold); copies kept identical by `tests/test_logo_copies.py`.
- Fixed: phones joining **Leaf Leap** / **Dig World** crashed the game (an attribute shadowed `GameApp._seat`).
- Table theme swatches are always pickable (built-in list mirrors the engine) and the studio says when the engine is
  too old for themes.

- 🎨 **14 new casino table themes** (Riviera noir, Imperial jade, Gilded deco, Marigold masala, Festival of lights, Cyber grid, Pixel arcade, Sakura night, Glacier, Desert oasis, Ocean abyss, Volcano, Galaxy, Riverboat mahogany): each a whole concept with LED-tuned panel colours, an
  AA-checked screen palette and a **felt motif** — the new `pattern` / `pattern_size` theme tokens (pure CSS
  gradients: clouds, sunburst fans, paisley, rangoli, circuit and pixel grids, petals, frost, tiles, starfield, wood
  grain…). The original seven got motifs too. Phones draw the motif on every felt and behind the join screen; the
  studio on the stage felt and wings. The studio's theme picker is a scrolling swatch grid with the motif in each
  swatch and the theme's one-line description on hover / focus. Themes carry a `description`.
- Andar Bahar: host option **Winning card** — Value (standard, any suit) or Exact card (same value and suit, dealt
  from a second deck; both sides 0.95:1, bands to 52). Phones replay and explain both.
- 🎱 **Housie (Tambola), the 10th casino table.** Players buy 1–N tickets into a pot (host: price, max tickets,
  rake); the caller draws 1–90 at a host-set pace (live − / + in the studio host bar, pausable); phones show 3×9
  tickets with auto-daub (or manual) and a stamp animation, the 1–90 board, traditional call names and claim buttons
  for Early Five, Top / Middle / Bottom Line, Four Corners and Full House (each on/off with its share of the pool).
  The server verifies every claim (bogeys rejected, optional penalty), ties on the same call split, unclaimed prizes
  are shared back. Provably fair: the call order and every ticket come from the sealed round and re-verify on the
  phone. Panel: the ball, the recent calls, n/90, claim flashes in the winner's colour, the buy-in screen and a demo
  preview. Casino games can declare their own host ops (`CasinoGame.host_ops`).
- 🐧 **New game: Penguin Escape** (`penguin`). A sliding-ice puzzle made for the 32 × 32 panel: waddle a penguin out
  of the zoo through 16 handcrafted single-screen levels (8 × 7 tiles of 4 px under a 4-row HUD). Ice slides you
  until something stops you; shove ice blocks (into water to bridge it), grab keys for doors, collect three fish
  per level for stars, and stay out of the keepers' torch beams (they move one step per move of yours). Arrows move,
  A undoes, B restarts and opens the level card (←/→ pick any level you've reached). Stars and progress are saved;
  themes Ice / Night / Aurora; the demo AI plays BFS-solved 3-star solutions and re-plans from wherever you left it.
- 🪙 **New intro theme: Coin Gate** (Settings → Display & colour → Intro & outro). An arcade cabinet: the neon
  idotmatrix sign in a backlit marquee, a coin door with a blinking INSERT COIN display and chase bulbs. A silver coin
  spins in and drops into the slot, CREDIT 0 → 1, then the lock bolts retract and the heavy toothed gate grinds open
  (gears, a little shake, motion blur); the outro slams it shut. Phone-sized, reduced-motion fallback, with sounds.
- Intro: the logo no longer blooms into a huge blurry halo when the doors open (Sunset, Circuit). The unlock flash
  is now a short lift of the tubes' cores; the halo never grows, so the dots stay crisp at every moment. The sun's
  flare and the light through the crack are toned down too.
- 🔊 **Studio sounds** (`web/src/lib/sound.ts`): ~45 effects synthesized live with the Web Audio API — no audio files.
  Soft ticks on keys / tabs / switches, sheet swishes, toast chimes, app switches and playlist skips; the casino table
  voices every player's chips, the betting bell, the last-seconds tick, no more bets, the wheel / reels / dice / cards
  and the result; Play mode game start / over / score; the fruit fly buzzes now and then. Settings → Display & colour →
  **Sound**: on/off, volume, per-category switches (Interface, Casino, Intro & outro, Games & fly), quiet in background
  tabs, Test. Every trigger point, wired and suggested, is listed in docs/STUDIO_UI.md "Sound".
- Casino: the panel shows the join QR only while the table is empty. Once someone sits down it shows the table and
  a row of everyone seated — dim = no chips yet, lit = chips down, capped block = pressed Done.
- Web app play-with-friends: a relay (TURN) fallback for networks that block direct links (mobile carriers, same
  Wi-Fi without loopback) — Cloudflare Realtime TURN credentials minted per live room by `/app/signal`.
- Casino previews (studio library and idotmatrix.com) play a whole demo round — chips, no more bets, the spin /
  deal, the result — instead of a still betting board (`App.preview_patch` / `preview_span`).
- 🧭 **Web app: every app audited for the browser** (docs/WEB_APP.md "App support in the browser"). Fixed glitches:
  ntfy pushes never arrived in a tab (it now polls every 10 s, token as `?auth=`), Uptime marked CORS-less sites
  and TCP targets DOWN (opaque reachability probe; TCP shows "NO TCP IN BROWSER"), Met / Cleveland artwork and
  Outlook / iCloud calendars failed (added to the CORS proxy, which now re-checks every redirect against its
  allowlist), Flight Radar polls every 15 s through the proxy. OBS Status, 3D Printer and Anki (plain-http LAN
  services, new feature `lan`) and System Monitor now say "NOT ON WEB" with the reason; the library badges them
  "Not on Browser". Failed requests explain LAN-over-http / no-CORS instead of a bare error; the browser app hides
  "Find nearby panels" and explains Home Assistant's https + CORS needs. Desktop and Android unchanged.
- 🌍 **Play with friends over the internet in the web app** (idotmatrix.com/app): the lobby QR now points at
  `idotmatrix.com/p/<code>`, and a friend's phone joins from anywhere — it connects straight to the host's tab over
  WebRTC (signalling through the `/app/signal` Netlify Function, STUN only) and runs the usual controller or casino
  page through the tunnel, with a reconnect overlay and clear errors (room closed, host tab gone, network blocks
  direct links — no TURN relay). The desktop's Wi-Fi play is unchanged.
- 📷 **Web app: Camera Mirror, Screen Mirror, Visualizer and dancing pets work in the browser** (idotmatrix.com/app/)
  through the browser's permission prompts: the camera (`getUserMedia`, phones too), a shared screen / window / tab
  (`getDisplayMedia`, desktop browsers) and the mic or a shared tab's sound. The engine asks only while such an app
  is on the panel and releases the device when it leaves; a card under the panel offers Allow / Choose screen /
  Stop sharing / Try again. Desktop and Android unchanged (docs/WEB_APP.md). Pet now opens the sound device only
  while "Dance to music" is on (like Pet World).
- 🎨 **Casino table themes** (`table_theme`, every casino game): Classic, Royal, Crimson, Midnight, Neon strip,
  Emerald, Burgundy — on the panel (LED-safe palettes), the phones and the studio (a swatch picker in House).
- 📖 **How to play & Rulebook** for all 9 casino games and Rock Paper Scissors (`casino/rulebook.py`, the one
  source): a "?" sheet with How to play | Rulebook | Payouts on phones, a first-time card per game, a Guide tab in
  the studio, and `docs/CASINO_RULES.md` generated from it.
- 📱 **Phone studio rebuilt as an app shell** (also idotmatrix.com/app on phones): a slim header with a Quick
  controls sheet, a pill tab bar, one scroll area per tab, a sticky search + 3-up app grid, settings with Show /
  Playlist docked above the tabs, Play mode as a one-screen console with a Match sheet, bottom sheets, dvh /
  safe-area / 16 px inputs. Fixed: the Settings modal overflowing phones, the intro logo cut off on phones, the
  web app's connection pill covering the tab bar.
- CI: the render-time test forgives one outlier frame (a shared runner stalled for 1.2 s).
- 🎰 **Casino mode** (docs/CASINO.md): Roulette, 7 Up 7 Down, Blackjack, Baccarat, Slots, Texas Hold'em, Teen Patti,
  Andar Bahar and the Big Six wheel.
  - **Fairness:** a provably fair commit–reveal RNG, with verification on phones and in the studio.
  - **Credits:** a session bank with escrow (whole credits, never negative) and host-set starting credits.
  - **Bets** are frozen from "no more bets" until settlement.
  - **Phones** get a casino page through the same QR; the panel shows only the table.
  - **Studio casino mode** has its own entrance, house/rules/odds on the left, players/credits/verify/play-from-laptop
    on the right, and the host bar with the join QR.
- ✊ **Rock Paper Scissors:** AI vs AI, you vs AI, 1v1 and 3–8 player tournaments, with pixel-hand pickers on phones.
- **Studio:**
  - "Let the fly play" and the flies-allowed sign sit under the settings panel (in the top bar on narrow screens).
  - The 3D views fall back to a simplified view if a GPU can't run the full one.
  - A page left open across a rebuild reloads itself.
- **Web app at idotmatrix.com/app/:** the real engine runs in the browser (Pyodide in a Web Worker) and drives the
  panel over Web Bluetooth — no install. Same studio, apps and settings (saved in the browser); OS-level features
  are greyed out as "Not on Browser". New `device = "web"` backend (`device/web.py`), `web` platform, build with
  `scripts/build_webapp.py`. See docs/WEB_APP.md and ADR 0012.
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

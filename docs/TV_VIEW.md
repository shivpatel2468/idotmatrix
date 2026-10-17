# TV view — DeskDot on the big screen

Any screen with a browser — a smart TV, Fire TV / Android TV, a Chromecast (cast a tab), a tablet, a second laptop,
a projector — shows a full-screen, read-only **TV view** of whatever DeskDot is playing: the panel as a huge,
realistic LED matrix, and for games and casino tables a bespoke scene (the whole roulette layout with everyone's
chips, the housie board, scores per seat…). Nothing on the panel is controlled from the TV; it only watches — its
remote only picks how this screen draws it (the options menu, §2) — and, at a casino table, the house's dolly and
chip design (two cosmetic settings, §1).

```
studio "Show on TV" ── POST /api/tv ──► {code, url}  ──► QR on the studio sheet
TV browser ── GET /tv/{code} ──► tv.html ── GET /tv/static/tv.js, tv-games.js, tv-casino.js
           ── WS /ws/tv/{code} ◄── hello · state (~5 Hz) · binary frames (3072 B, ≤ 12 fps, latest wins)
```

## 1. Pairing

- **Studio:** the stage's **Create** menu → *Show on TV* (also the command palette, *Show on TV…*) opens a sheet with
  the QR code, the URL to type, the 4-character TV code, the number of TVs watching and *Stop TV link*.
- `POST /api/tv` opens the TV link (or returns the open one — the sheet can be reopened without breaking a TV that
  is already watching). Body `{"renew": true}` replaces the code (every TV on the old code is told `closed`).
  Response `{ok, code, url, lan_ready, viewers}`. `GET /api/tv` → `{tv: {code, url, lan_ready, viewers} | null}`.
  `DELETE /api/tv` closes it. One TV code at a time, separate from (and never equal to) the multiplayer lobby code.
- **Display from the studio:** the sheet's *On every TV* box sets the panel look (Pixel · LED · Glow) and the quality
  (Auto · HQ · Lite) for every TV of the link — `POST /api/tv/settings {look, quality}` (each a value, or `null` =
  *Let each TV choose*; a key left out keeps its value). The engine keeps it on the TV link (`TvLink.display`, with a
  new `rev` per change) and sends it in every `hello` and `state` as `display`, so TVs switch at once (§2).
- The URL is `http://<this computer's LAN IP>:<port>/tv/<code>` on the desktop, or `<public_url>/tv/<code>` in the
  web app (§8). The TV needs the same Wi-Fi as the computer (desktop) — exactly like a phone joining a game.
- **Security:** `LanGate` lets LAN clients reach only `/p/`, `/ws/p/`, `/tv/` and `/ws/tv/` (and never a path with
  `..`). `/tv/{code}` and `/ws/tv/{code}` check the code; `/tv/static/{name}` serves only the TV scripts (public code,
  no data, and the TV's font `tv-sans.woff2`). The TV socket is read-only but for one narrow message: while a casino
  table shows, the options menu may set the house's two *display* settings, the roulette dolly and the chip set
  (`{"type": "house", "dolly": id}` or `{"type": "house", "chip_set": id}`, §3). `tvlink.py` `house_patch` /
  `TvHub._house` take exactly one of those keys with a known value (`casino/session.py` `DOLLIES`; `auto` or a
  `casino/chips.py` `CHIP_SETS` id), only from a socket opened with the valid code (checked again per message), only
  while the app on the panel is a casino table, at most one change per TV per 0.25 s, and apply it as the studio's
  `settings` op with nothing else in it — credits, limits, timers, rules and every other app stay studio-only, and
  LanGate is unchanged (no new HTTP route). Why it's safe: both are cosmetic (no money, odds or fairness proof touches
  them) and anyone with the code is already in the room watching. Everything a TV receives is what a phone in the
  room — or anyone looking at the panel — can already see (§3).

## 2. The page

`src/deskdot/tv.html` (no inline script — the web app's CSP forbids it) loads, in order, `tv.js` (core), then
`tv-games.js` and `tv-casino.js` (scenes) from `/tv/static/` (in the web app from `/app/join/tv/`).

- `#stage` is exactly **1920×1080 CSS px**, scaled uniformly to fit the window (letterboxed on black), so every TV
  shows the same layout. `TV.scale` is the current scale; `TV.pixelRatio = TV.scale × devicePixelRatio` is how many
  device pixels one stage pixel covers (canvases size their backing store with it, so they are crisp on a 4K TV).
- **Top bar** (`#bar`, 96 px): three columns — the app's name and category (a pill) on the left; the DeskDot LED
  logo (`DeskDotLogo` in tv.js, a copy of the studio's `lib/logo.ts`: "Desk" `#ff3f78`, "Dot" `#ffcc33`) on a small
  dark LED sign **in the centre** of the stage (the side columns are equal), a small "TV" beside it; the join QR +
  room code while a multiplayer lobby is open, the clock with the date under it and the connection dot on the right.
  The bar's logo is mounted with `once: true`: it builds in and strikes once on load, then holds fully lit and steady
  (no hum, no power-down loop), so it is never caught half-lit. A static rose → gold hairline (the logo's two colours)
  runs under the bar; at a casino table the bar takes the table's look (the name engraved in a serif, a gilded rule).
- **Type** (`tv.html` `--font`, `--serif`, `--mono`): one self-hosted sans for the UI and the numbers — Bricolage
  Grotesque, the studio's own face (SIL OFL 1.1, `tv/OFL.txt`), its Latin subset with the weight axis
  (`tv/tv-sans.woff2`, 41 KB), loaded by tv.js with `FontFace` from beside the scripts (`/tv/static/`, in the web app
  `/app/join/tv/`), tabular numerals everywhere; a display serif for titles (the app's name, the casino header, the
  veil, the menu title — the system's Didot / Bodoni, Georgia on Windows, Noto Serif on a TV stick); the mono only for
  codes. Labels are the sans in tracked capitals (≥ 15 px in the bar, ≥ 19 px elsewhere), body ≥ 26 px. Canvas scenes
  use the same sans (`tv-casino.js` `FONT`) and redraw once when it has loaded (`scene.restyle`). Nothing loads from
  another site.
- **Scene area** `#scene`: **1920×984**, below the bar. Exactly one scene is mounted in it.
- **Panel look** (`TV.look`): the studio's three looks (`web/src/lib/look.ts`, drawn as `LedPanel.tsx` draws them):
  `pixel` (sharp square pixels), `led` (the default here — a physical LED matrix: rounded LEDs, 13 % inset, 24 %
  corner radius, in a `#060608` grille; unlit LEDs `#15151b`, very dim ones lifted a little so they stay visible, a hot
  white core on bright ones, bloom σ 0.9 LED × 0.55 + σ 2.6 LED × 0.3) and `glow` (sharp pixels with a soft bloom,
  σ 0.8 × 0.28 + σ 2.4 × 0.2). Measured against the studio's own drawing code in Chrome: Pixel is identical, LED and
  Glow differ by under 1/255 on average (p99 ≤ 4/255 — the bloom is a three-box-blur Gaussian, not the canvas filter).
  The studio's colour-calibration preview is not applied on the TV (the TV shows the app's design colours).
- **Quality** (`TV.qualityMode` = `auto` | `hq` | `lite`; `TV.quality` = the tier in effect, `hq` | `lite`, also on
  `html[data-q]`): **both tiers draw the same picture** — same canvas resolution (the real device pixels, capped as
  in §6), the same glows, shadows, particles, animations and cross-fades. Their speed comes from cheap techniques
  used in both (§6). Lite only trims what can't be seen: countdown rings redraw on ~1.5 device px of arc instead of
  every 1°. *Auto* (the default) starts in hq and watches its own frame times while something animates (and for ~8 s
  after every scene change): a window of 120 frames whose median is over 22 ms, or with more than 20 % of frames over
  34 ms, switches it to lite for the rest of the visit (the scene is re-mounted). It never switches back by itself.
- **Who picks** (per choice, `pickDisplay` in tv.js, tested in `tests/js/tv_core.test.mjs`): the studio's choice
  (`display`, §1) wins over what the TV remembers, until someone picks on that TV again — the TV's pick is stored
  (`localStorage` `deskdot.tv.look` / `deskdot.tv.quality`, `{v, rev}`) with the studio revision it overrode, so a
  later change in the studio wins again. Address parameters — `?look=pixel|led|glow`, `?quality=auto|hq|lite` (also
  `?lite=1` / `?hq=1`) — win over the studio's choice that was already set when the page loaded, not a later one.
  Choices apply at once, without a reload (panels redraw; a quality change re-mounts the scene). A change from the
  studio shows a short notice on the TV.
- **Options menu** (for a TV remote, a mouse, a touch screen or a keyboard): OK / select / Enter, the menu key (also
  M, play-pause), or a click / tap anywhere opens a card at the bottom of the screen: *Panel look: Pixel · LED · Glow*,
  *Quality: Auto · HQ · Lite* and *Theme: Dark · Light* — this TV's own (with "now HQ / Lite" under Auto, and "Set from
  the studio" / "Set in the address" when that's where the value came from) — and, while a casino table shows, the
  house's **Dolly** (roulette only: the 8 styles, drawn with the real sprites) and **Chips** (*Match table* + the 7
  sets, three real chips each), which go to the engine (§1, §3) and change every screen; the row says "Saving…" until
  the table's status shows the pick (or 4 s), and an error toasts. The D-pad arrows move a white focus ring (scaled up,
  readable from 3 m; ↑ ↓ keep it above the same place in a longer or shorter row), OK / Enter / Space / the D-pad
  centre (keyCode 23) picks (the chosen option is filled ember with a ✓; a press dips the tile, a pick flashes it),
  Back / Escape or the menu key closes it, and it closes itself after 12 s without input. Back on a TV browser goes
  back in history, so an open menu holds one history entry and Back just pops it; Back with the menu closed is the
  browser's own. Mouse: hover moves the focus, a click picks, a click outside the card closes; touch: a tap picks.
  Clicks are taken on `document` (the stage, the letterbox, and the root while the theme cross-fades — the tile is then
  found by its box). Text is `--ink-1` / `--ink-2` on the card in both themes (AA). `tests/js/tv_menu.test.mjs`
  clicks, taps and keys every tile in a headless Chrome (needs playwright-core and Chrome: `PLAYWRIGHT_DIR`, `CHROME`;
  skipped otherwise).
- **Theme** (`TV.theme` = `dark` | `light`, on `html[data-theme]`): a TV sits in a dark room, so it is dark unless
  the address says `?theme=light|dark` (wins) or someone picked *Light* in the options menu on this TV
  (`localStorage` `deskdot.tv.theme`, raw `light` / `dark`); it ignores the studio's own `deskdot.theme`. Light uses
  the studio's "Gallery" tokens (docs/STUDIO_UI.md: porcelain `#f4f0e8`, ivory `#fbf9f5`, ink `#1c1a22`, rose
  `#b81f4b`, antique gold `#b8892a` / gold text `#8a6412`) under the same token names (`--chassis-*`, `--ink-*`,
  `--ember`, `--gold`, `--gold-text`, …); the panel stays a dark device in its bezel, the LED logo sits on a small
  dark LED sign with a gold rim, and **a casino table becomes a daylight salon** (§7): the whole TV follows the theme. Light mirrors the studio's MATERIALS v2 by name
  (`--m-daylight`, `--m-wash-a/b`, `--m-vignette`, `--m-bevel`, `--m-rule-gold`, `--m-gold-leaf`): daylight, a rose and
  a gold bloom and a vignette on the stage and the veil, a gilded rule under the bar, an engraved gold double rule
  inside cards / stats / the options card, players' rows with a halo in their colour. Same cost as dark: static gradients and shadows
  only (tests: `tests/js/tv_core.test.mjs`). `TV.setTheme(v)` switches with a cross-fade: the View Transitions API
  snapshots the page and fades it into the new theme (0.5 s, one compositor animation; a short stage fade where the
  API is missing; none with reduced motion). Inside it a canvas scene redraws its static layers once (`scene.restyle`).
- States: *Waiting for DeskDot…* (connecting / reconnecting with backoff 0.5 s → 8 s), *This TV link has closed*
  (the studio stopped it or the code is wrong; the page keeps checking every 20 s in case the same code comes back).
- The waiting / closed card stands on a static wall of unlit LEDs (a masked dot-grid gradient) and shows the TV code
  on four big tiles.
- No scrollbars, the cursor hides after 3 s still, the screen never sleeps (Wake Lock API, re-acquired on
  visibility change), the studio's tokens in both themes.

## 3. The socket — `WS /ws/tv/{code}`

Server → TV, but for two messages from the TV: `{"type":"ping","t":…}` (the server answers
`{"type":"pong","t","server_time"}`) and, at a casino table, `{"type":"house","dolly":id}` or
`{"type":"house","chip_set":id}` from the options menu (§1 for the rules; the answer is `{"type":"house_ok",…}` or
`{"type":"house_err","error"}`, and every TV gets the new `status.house` / `status.chip_set` in its next `state`).
Anything else a TV sends is ignored.

| Message | When | Shape |
| --- | --- | --- |
| `hello` (text) | on connect and whenever the app on the panel changes | `{"type":"hello","app":id\|null,"meta":{id,name,category,icon,max_players},"avatars":{id:{name,px}},"display":{…},"server_time":t}` |
| `state` (text) | ~5 Hz when something changed, else a 2 s heartbeat | `{"type":"state","app":id\|null,"status":{…},"lobby":{…}\|null,"tv":{…}\|null,"display":{…},"server_time":t}` |
| frame (binary) | every new panel frame, ≤ 12 fps, latest wins | 32×32×3 RGB bytes, row-major (3072 B) |
| `closed` (text) | the TV link closed or the code is wrong | `{"type":"closed"}` then the socket closes |

- `server_time` is the engine's `time.time()` in **seconds**.
- `display` is the studio's choice for every TV (`POST /api/tv/settings`): `{"look": "pixel"|"led"|"glow"|null,
  "quality": "auto"|"hq"|"lite"|null, "rev": t|null}` — `null` leaves that choice to each TV; a TV applies it whenever
  `rev` changes (§2).
- `status` is **exactly** the app's public `status()` — the same dict phones receive as `status` (casino tables:
  phase, ends_in, spots/totals, spot_bets, players/seats, history, outcome/result, rules, table_theme, deal…; games:
  score, best, player, roster, lives, flow, seats, turn…). `private_status()` (hole cards, a seat's own bets and
  credits detail, seeds before the reveal) is **never** sent to a TV. Countdown fields such as `ends_in` are relative
  to the moment the state was built — combine them with `ctx.stateAt`.
- `lobby` is the multiplayer lobby snapshot while one is open: `{code, app, url, max_players, lan_ready, seats:[{seat,
  name, color, avatar, ready}]}` (no client ids), else `null`.
- `avatars` is the 8×8 avatar art (`gfx/avatars.py`): rows of codes `c` player colour, `d` darker player colour,
  `w` white, `k` black, `y` yellow, `r` red, `.` transparent — draw with `ctx.drawAvatar`.

### TV-only anchors: `tv` and the shared clock

`tv` is the app's `tv_extra()` (TV only — never in `status`, never sent to phones). For the casino tables whose
round has nothing left to decide once bets lock (roulette, big six, 7 up 7 down, baccarat, andar bahar —
`CasinoApp.tv_reveal`), it carries, **from the lock until the next round opens**:

```json
"tv": {"reveal": {"game": "roulette", "round": 12, "outcome": {"pocket": 27, ...}, "since_lock": 3.4012,
                  "at": 1760000000.123, "paused": false, "lock_s": 1.0, "spin_s": 7.5, ...per game},
       "wheel": {"rot": -812.33012, "at": 1760000000.101}}   // roulette: the panel wheel's angle when last drawn
```

- Bets are frozen at the lock, so knowing the outcome then gives nobody an edge; the commit–reveal proof is
  unchanged (the server seed is committed before betting and revealed at the result). Before the lock there is no
  `reveal`. Turn games (blackjack, hold'em, teen patti) and housie never send one.
- Per game: big six adds `end`, `travel`, `stop_s` (its cosmetic spin constants), 7 up 7 down adds `faces` (the
  tumbling faces). Slots send `{"game": "slots", "spin", "stops", "t", "at", "stops_at"}` for the spin on the panel
  (staked and fixed at the pull).
- **The shared clock.** `since_lock` was true at server time `at`, so the lock happened at `at − since_lock` on
  the engine's clock. A client keeps one synced clock — local `performance.now()` plus the offset to `server_time`,
  **slewed** (≤ 30 % of real time, never backwards; a jump > 1 s snaps) — and evaluates every animation as a pure
  function of `T − lock`: the same functions the panel apps use (`casino_roulette.ball` / `wheel_step`,
  `casino_bigsix.wheel_angle`, `casino_sevens.dice_at`, `casino_slots.reel_pos`, `Baccarat.deal_times`,
  `andarbahar.deal_pace`), ported 1:1 in `tv-casino.js` and checked against Python reference values in
  `tests/js/tv_casino.test.mjs`. So the TV's ball lands in its pocket in the same frame as the panel's. The
  roulette wheel is integrated frame by frame on the panel; the TV integrates the same exact step and slews onto
  the reported `wheel` angle.
- Phones and the studio can adopt the same clock (`casino.html` / `web/src/components/casino/sync.ts`).

## 4. Writing a scene — the registry

```js
TV.registerScene({
  id: "roulette",
  match: (app, meta, status) => app === "casino_roulette", // first registered match wins; "generic" is the fallback
  mount(root, ctx) {},   // build DOM / canvases inside root (a 1920×984 div, class "tv-scene")
  update(ctx) {},        // every state message (status / lobby changed)
  frame(ctx) {},         // optional: every panel frame (ctx.panel is the new frame)
  unmount() {},          // optional: stop timers / rAF; root is emptied for you
});
```

Scenes are matched again on every `hello` and `state`, so a scene may depend on `status` (e.g. only the live casino
view). A scene is re-mounted only when the matched scene id changes. Throwing in a scene never breaks the page: the
error is logged and the generic scene takes over for that app.

`ctx` is one long-lived object (read it fresh in each callback):

| Field | What |
| --- | --- |
| `app`, `meta` | app id (or null) and `{id, name, category, icon, max_players}` |
| `status`, `lobby` | the latest public status (`{}` before the first state) and lobby snapshot or null |
| `panel` | the newest frame, `Uint8Array(3072)` RGB, or null; `frameAt` = `ctx.now()` when it arrived |
| `stateAt` | `ctx.now()` when the latest state arrived (deadline = `stateAt + status.ends_in`) |
| `tv` | the latest state's TV-only anchors (`{reveal, wheel}` above) or null |
| `connected` | the socket is up |
| `now()` | local seconds (`performance.now()/1000` based, monotonic) |
| `serverNow()` | the engine's clock in seconds (`time.time()`), estimated from `server_time` |
| `drawPanel(canvas, opts)` | paints the panel big in the TV's look — Pixel, LED or Glow (below) |
| `drawAvatar(canvas, id, color)` | an 8×8 avatar, pixel-crisp, in a player colour |
| `qr(text, canvas, opts)` | draws a QR code (`opts.size` CSS px, `opts.dark`, `opts.light`, `opts.quiet` modules) |
| `fmt(n)` | credits / scores: `12,345` (`fmt(1234567, true)` → `1.2M`) |
| `theme` | the casino table theme's `css` dict (`felt`, `felt2`, `felt3`, `accent`, `accent_hi`, `accent_lo`, `accent_deep`, `accent_rgb`, `ink`, `wing*`, `pattern`, `pattern_size`) or `{}` — `pattern` is the felt's motif: a gradient-only CSS `background-image` (no `url()`), `pattern_size` its `background-size` with one entry per layer; a canvas scene can paint it by drawing the felt through a DOM layer / `CanvasPattern`, or ignore it (see docs/CASINO.md §11) |
| `seatColor(n)` | a lobby seat's colour (the player's pick, else the seat default) |
| `el(tag, className, text)` | tiny DOM helper |
| `esc(s)` | HTML-escapes a string |

`ctx.drawPanel(canvas, {pitch, glow, data, look})`:
- sizes the canvas — `pitch` (stage px per LED) sets its CSS size to `32 × pitch`; otherwise it fills the canvas's
  current CSS size (`clientWidth`) — and its backing store to the device pixels it covers (× `TV.pixelRatio`), rounded
  to a whole number of device px per LED (crisp squares), capped at 1600 px — the same in both tiers;
- `look` `"pixel"` / `"led"` / `"glow"` overrides `TV.look` for this canvas; `glow: 0` (or `false`) turns the bloom off;
  `data` draws another 3072-byte frame instead of `ctx.panel`;
- the bloom is a 64×64 canvas the core inserts right after the panel canvas (same parent, placed over it with
  `mix-blend-mode: plus-lighter`), so the panel canvas's parent must be its positioning box or share it (a
  `.tv-bezel` / `.tv-well`, or the scene root for an absolutely placed canvas); without plus-lighter the bloom is
  drawn into the canvas instead;
- costs one 32×32 `putImageData`, one nearest-neighbour upscale, the cached grille and a few core sprites (LED) per new
  frame, plus one CPU blur of the frame shared by every panel; a call with the same frame bytes, size and look (a
  status update, a repeated frame) draws nothing.

`TV.surface(canvas, w, h)` → `{g, w, h}` and `TV.showSurface(s)`: draw a big, rarely changing canvas off-screen and
hand it to the page as a finished bitmap (§6). After `showSurface` the drawing buffer is blank: redraw in full before
each show. Without OffscreenCanvas / bitmaprenderer, `g` is the canvas's own context and `showSurface` does nothing.

Scene timing helpers: `TV.every(fn)` runs `fn(seconds)` on the page's **one** `requestAnimationFrame` loop (return
`false` to stop; it returns an unsubscribe function) — scenes never start their own rAF loops or `setInterval`s for
animation. Panel frames are drawn from the same loop (latest wins). A scene may implement `resize(ctx)` (the stage
scale changed) and `restyle(ctx)` (the theme or the font changed: redraw cached canvases once, now — read the theme
from `html[data-theme]`); a tier change re-mounts it.

Shared CSS (in `tv.html`, use freely): tokens `--chassis-0…4`, `--line`, `--ink-1…4`, `--ember`, `--gold`, `--ok`,
`--warn`, `--bad`, `--info`, `--font` (the TV's sans), `--serif` (display titles), `--mono` (codes); the table theme as `--felt`, `--felt2`, `--felt3`,
`--accent`, `--accent-hi`, `--accent-lo`, `--accent-rgb`, `--ink` on `#stage` (classic green + gold when no casino);
classes `.tv-bezel` (the panel housing: machined frame, screws via `.tv-screw`), `.tv-card` (a raised surface),
`.tv-chip` (a status pill; `data-tone="ok|warn|bad|ember|gold"`), `.tv-label` (engraved uppercase label),
`.tv-big` (a large number), `.tv-avatar` (a canvas for `drawAvatar`). Type is sized for 3 m: labels ≥ 22 px,
body ≥ 28 px, hero numbers 80 px and up.

Scenes live in `src/deskdot/tv/`: `tv.js` (core + the generic scene), `tv-games.js` (games), `tv-casino.js`
(casino tables). A new file there must also be added to `tv.html` (and is copied by `scripts/build_webapp.py`).

## 5. The generic scene

Every app falls back to it: the live panel centred, huge, in a bezel (in the TV's look — Pixel, LED or Glow — in a
recessed well with a diffuser sheen) standing on a soft pool of shadow, the app's name over a rose → gold rule, its
category and the status chips (cards with an accent edge), a *LIVE* pill whose dot breathes on its own opacity (the status's simple values:
score, best, level, player, phase…) at the side, the lobby's players and the join QR when a lobby is open.

## 6. Performance on TV sticks (Fire TV, Android TV, Chromecast)

A TV stick has a phone CPU from years ago and a small GPU, and its browser (Silk on Fire TV) usually reports a
960×540 CSS viewport at devicePixelRatio 2; it may composite in software. What keeps the view smooth there — in
**both** tiers, so lite never costs picture quality — keep it that way:

- **One loop, transforms for motion.** Everything that moves every frame (wheels, balls, dice, reels, stamps) is a
  pre-rendered canvas moved by `transform` / `opacity`. Style writes are skipped when the value didn't change.
- **Big canvases are surfaces.** A composited frame makes a software compositor copy every visible 2D canvas, changed
  or not — with a wheel spinning, the table layers were copied 60 times a second. The casino's big layers (table
  background, table layer, rail, wheel heads; ≥ 200 k device px) draw into an `OffscreenCanvas` and hand the page a
  finished bitmap (`bitmaprenderer`) only when they change (`TV.surface`, `layer().show()` in tv-casino.js). Small or
  constantly changing canvases (the panel, countdown rings, sparks) stay plain canvases — cheaper to copy than to
  hand over.
- **Big canvases redraw rarely.** A casino scene's table layer redraws only when the status changed, while a chip or
  card is in flight (30 Hz), or at the scene's slow rate (≈1 Hz while betting, 4 Hz for turn games). Countdown rings
  sweep in their own small canvases (`hudRing` in tv-casino.js), not in the table layer.
- **No blur per frame.** `shadowBlur` only where something is drawn once (chip, card, die and ball sprites, the cached
  background) or in a countdown ring's own small canvas; a glow in the redrawn table layer (headline text, winning
  boxes, glowing cards and avatar rings, the roulette number disc, slot win lines, the housie call) is a cached
  sprite of exactly that shadow (`glowFx`: the shape drawn off the sprite with its shadow offset back in), stamped
  with one `drawImage`. Text casts a hard offset shadow. The panel's bloom is a CPU box blur on a 64×64 grid, added by
  the compositor. No `filter: blur()` / `backdrop-filter` in CSS, no animated `box-shadow` (glows pulse a
  pseudo-element's opacity). Liquid Glass on the TV (header bar, options menu and its controls) is static faux glass:
  layered tint, top sheen, inner light/shade, a 1 px rim and a soft shadow, painted once — the menu ~93 % opaque so
  text never sits on raw content (docs/STUDIO_UI.md § Liquid Glass). In light mode the TV's panel is the paper panel.
- **No work for nothing.** A panel skips a frame whose bytes didn't change; number formatting is cached; the generic
  scene's ambient glow repaints at most twice a second and only when it visibly changed.
- **Canvases match the screen.** Backing stores are sized to the device pixels they cover after the stage scale,
  capped (table layers at 1.5 device px per stage px, wheels at 2, the panel at 1600 px) — the same in both tiers.
- **Idle sprites leave the layer tree.** A pooled sprite that isn't showing is `display: none`, not `opacity: 0`
  (dozens of transparent composited layers measurably slowed the 6× benchmark). Sprites that only ever show while
  moving and scaling (the win banners, rays, the flash) are painted at stage scale 1 and a soft burst at ¼ size.
- **Paint the expensive once, early.** Sprites that take a long paint (a tier banner: wide stroked text) are cached
  per page and pre-warmed one per 1.5 s while betting, never on the moment's first frame.
- **Measure.** A headless benchmark (software canvas and compositing, CDP CPU throttling ×6 at 960×540 DPR 2, fixture
  statuses over a mocked TV socket) compares p50 / p95 frame intervals and main-thread busy time before and after a
  change; the numbers are in the change's report.

## 7. The casino as the main screen (3.7.0)

DeskDot's future is a hosting device with or without the pixel panel, so a casino table on the TV is the casino's
main screen: an imaginary ultra-luxury table per game, the table as the hero, the players in a gallery beside it.

**The table** (cached background, drawn once per theme — every effect is free per frame): a damask salon wall, an
overhead lamp's warm pool and a vignette; the felt (the theme's, deep pile, grain) sinks under the rail in a soft inner
shadow with a gold pinstripe printed inside it; the rail is lacquered mahogany built from layered strokes (dark edges,
a warm crown, a gloss line) with brass inlay on both edges and a long contact shadow (`luxTable`, `railStroke`;
soft shadows are stacked faint strokes — `softStroke` — never `shadowBlur` on a big path, which costs a TV stick
hundreds of ms). Titles are engraved in gold leaf in a system serif (`txt(…, {font: "serif", gold: true})`); the
printed layout is embossed (`emboss`); roulette's grid is a gold inlay on a dark bed, its cells lacquered, the bowl a
polished brass ring round lacquered walnut with the lamp's reflection, the wheel's frets and turret turned metal. The
poker tables have a padded leather racetrack. The header turns into the casino's own in table mode (tv.html: the
table's name in gold-leaf serif capitals over a gilded double rule).

**In light mode** the room is a daylight salon (`tv-casino.js` `ROOMS.light`, after the studio's light casino and
MATERIALS v2): ivory and champagne walls with a gold damask and a rose / gold-leaf bloom, a white-lacquer rail with a
double gold inlay, an ivory gallery with gold hairlines and ivory seat plaques (players' names in their colour,
deepened — `inkOf`), antique-gold engraving instead of bright gold leaf (`txt(…, {gold: "deep"})`), the LED panel's
inset in a champagne-lacquer housing (the panel stays a dark device), deep ink for type on the room (`roomInk`: the
seat lines, the poker tables' headline, log and hand line). The felt keeps the table theme's colour. The header is
ivory with the table's name in antique gold. Both rooms are drawn into the cached layers: the theme is part of the
background key, and a switch redraws background, table and rail once (`scene.restyle`), never per frame.

**The seat gallery** (right, the rail layer): one leather plaque per player — avatar in a gold bezel, a jewel bar in
their colour, name, status line, a live chip stack of what they have on the table, and their credits on an
**odometer** (`Odo`: a DOM reel per digit moved by transform, rolling with a little overshoot, units a lap or two
further, stopping left to right, a smeared copy fading in at speed; instant with reduced motion). The panel's live
inset appears under the gallery only once panel frames arrive; without a panel the gallery takes the full height (up
to 8 seats). Chips follow the table's chip **set** (`status.chip_set`: clay, ceramic, gold-rimmed, neon, jade,
pixel, ivory — docs/CASINO.md §13), the denomination colours and labels unchanged.

**Game animation** — every outcome-related motion is a pure function of the shared clock (§3), never invented:
- Roulette: the ball carries a motion-blur streak (a pre-rendered tapered sprite turned along its path, faded by
  speed) and hops toward the camera on the frets (a cosmetic scale from the panel's own bounce term); when it
  settles the camera pushes in on the pocket (×1.14) and pans to the layout's number (`S.cam`, a transform of the
  scene root, ≈ 1.3 s); the dealer's unseen hand lifts the **dolly** from its rest beside the wheel, glides it over the
  layout, sets it down on the number `DOLLY_AFTER` (0.95 s) after the settle with a soft click ring and a felt
  shadow that firms up as it lands (`dollyPath`, tested), and takes it home when the next round opens. Its style is
  the house's (`status.house.dolly`, 8 styles drawn as sprites: Classic Gold, Crystal, Chrome, Black Onyx & Gold,
  Rose Gold, Diamond-cut, Marble & Brass, Neon Arcade) — picked in the studio (Casino → House) or from the TV's
  options menu (§2). Losing stacks are swept to the croupier and each winning
  spot gets its payout stack pushed from the dealer (stake × the spot's odds).
- Cards turn in 3D (narrow on the axis, lift toward the camera, the turning edge leans and darkens); dice tumble as
  they roll (a cosmetic turn that unwinds to square as they settle on the panel's faces); slot reels smear along the
  strip at speed; big six's clapper ticks on the pegs; housie balls drop and bounce.

**The win / lose moment** — when a round settles every screen plays the same moment from the result's anchor
`status.clock.phase_at` (a screen that tunes in more than 2.6 s late shows the settled table, no replay). It reads
only the public result: `result.winners` (net > 0, with `stake`) and `result.losers` (docs/CASINO.md §13).
- 0.05 s: losing chips swept to the dealer (0.8 s); a loser's plaque shows "−500" floating up and fading.
- 0.25 s: a tiered banner slams in (scale 1.7 → 1 with overshoot) over turning rays with a gold flash: **WINNER!**
  (payout < 3× the stake), **BIG WIN!** (≥ 3×), **MEGA WIN!** (≥ 10×), **JACKPOT!** (≥ 30×, a straight-up number),
  or **HOUSE WINS** when nobody won; big tiers shake the screen (6 / 10 / 16 px, decaying over 0.55 s). Under it the
  biggest winner's "+12,500" counts up with an easeOutExpo (`tickerAt`, the same function as the phones').
- 0.5 s on: coins fountain from each winner's chips on an arc into their plaque (staggered 0.12 s per winner); when
  they land the plaque lights up in the tier's colour, its "+12,500" badge counts and the odometer rolls to the new
  credits (credits are held until then). Sparkles twinkle round the banner. It all fades by 3.75 s.
- Every part is a pre-rendered sprite moved by transform / opacity: the banners and rays are painted once per page
  (pre-warmed one per second while betting), coins / sparks / plaque overlays are pooled small canvases hidden with
  `display: none` when idle (an idle composited layer still costs a stick its frame rate), chips in flight are a
  pool of stack sprites (`flight` / `flightsFrame`) — the big table layer redraws once when the moment starts, never
  per frame. The phone page plays a lighter moment for the player's own result (docs/CASINO.md §13).

Tables show the chips the house allows (docs/CASINO.md §5): the rail lists the table's rack — `status.chips`, or the
same rack computed from `house.min_bet` / `max_bet` with a copy of the ladder when an older engine doesn't send it
(`chipRack` in tv-casino.js, tested against `casino/chips.py`). Every stack on the felt is its amount broken into
ladder chips (largest at the bottom, greedy), in the ladder's colours and edge stripes; the top chip's inlay is the
player's colour with the amount in K / M. The other tables mark their winning spot with a stamp and a short burst of
sparks.

## 8. The web app (browser version)

In the web app the engine runs in the user's tab. The TV link's URL is `https://idotmatrix.com/tv/<code>`; Netlify
rewrites `/tv/*` to the join page (`web/webapp/join/`), which links the TV to the host tab over WebRTC (the same
tunnel the phones use: `host-rtc.js` also registers the TV code with the signalling function and lets GET `/tv/`
and sockets `/ws/tv/` through). The join page picks the `tv` template (built by `scripts/build_webapp.py` from
`tv.html`, with `/tv/static/*.js` copied to `/app/join/tv/`).

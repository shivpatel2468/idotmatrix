# TV view — DeskDot on the big screen

Any screen with a browser — a smart TV, Fire TV / Android TV, a Chromecast (cast a tab), a tablet, a second laptop,
a projector — shows a full-screen, read-only **TV view** of whatever DeskDot is playing: the panel as a huge,
realistic LED matrix, and for games and casino tables a bespoke scene (the whole roulette layout with everyone's
chips, the housie board, scores per seat…). Nothing is controlled from the TV; it only watches.

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
- The URL is `http://<this computer's LAN IP>:<port>/tv/<code>` on the desktop, or `<public_url>/tv/<code>` in the
  web app (§8). The TV needs the same Wi-Fi as the computer (desktop) — exactly like a phone joining a game.
- **Security:** `LanGate` lets LAN clients reach only `/p/`, `/ws/p/`, `/tv/` and `/ws/tv/` (and never a path with
  `..`). `/tv/{code}` and `/ws/tv/{code}` check the code; `/tv/static/{name}` serves only the TV scripts (public code,
  no data). The TV socket is read-only: it accepts pings and nothing else. Everything it receives is what a phone in
  the room — or anyone looking at the panel — can already see (§3).

## 2. The page

`src/deskdot/tv.html` (no inline script — the web app's CSP forbids it) loads, in order, `tv.js` (core), then
`tv-games.js` and `tv-casino.js` (scenes) from `/tv/static/` (in the web app from `/app/join/tv/`).

- `#stage` is exactly **1920×1080 CSS px**, scaled uniformly to fit the window (letterboxed on black), so every TV
  shows the same layout. `TV.scale` is the current scale; `TV.pixelRatio = TV.scale × devicePixelRatio` is how many
  device pixels one stage pixel covers (canvases size their backing store with it, so they are crisp on a 4K TV).
- **Top bar** (`#bar`, 96 px): the animated DeskDot LED logo (`DeskDotLogo` in tv.js, a copy of the studio's
  `lib/logo.ts`: "Desk" `#ff3f78`, "Dot" `#ffcc33`) with a small "TV" label, the app's name and
  category, the join QR + room code while a multiplayer lobby is open, a clock and the connection dot.
- **Scene area** `#scene`: **1920×984**, below the bar. Exactly one scene is mounted in it.
- **Quality tier** (`TV.quality`, `html[data-q]`): `hq` (soft shadows and glows, the HD panel cross-fades,
  full-resolution canvases) or `lite` (no blurred shadows or glows, fewer particles, table canvases at ¾ resolution,
  no theme cross-fades). `?lite=1` / `?hq=1` (or `?quality=lite|hq`) force one. Otherwise the page starts in hq and
  watches its own frame times while something animates (and for ~8 s after every scene change): a window of 120
  frames whose median is over 22 ms, or with more than 20 % of frames over 34 ms, switches it to lite for the rest of
  the visit (the scene is re-mounted at the new resolution). It never switches back by itself.
- **Panel look** (`TV.look`): `hd` (default) or `led`. *HD* is the frame upscaled with a pixel-art upscaler (Scale2x /
  EPX ×3: 32 → 256 px, then bilinear to the canvas) — smooth diagonals and round corners, but only ever the frame's
  own colours in the frame's own places, so it always shows exactly what the panel shows — with a cheap bloom and, on
  big panels in hq, a ~60 ms cross-fade between frames. *LED* is the classic realistic LED matrix. `?look=led|hd`
  picks one; **L** on a keyboard, or the remote's **select / play-pause / menu** button, toggles it (a short notice
  says which); the choice is remembered on that screen (localStorage).
- States: *Waiting for DeskDot…* (connecting / reconnecting with backoff 0.5 s → 8 s), *This TV link has closed*
  (the studio stopped it or the code is wrong; the page keeps checking every 20 s in case the same code comes back).
- No scrollbars, the cursor hides after 3 s still, the screen never sleeps (Wake Lock API, re-acquired on
  visibility change), dark design using the studio's tokens.

## 3. The socket — `WS /ws/tv/{code}`

Server → TV only (the TV sends `{"type":"ping","t":…}`; the server answers `{"type":"pong","t","server_time"}`).

| Message | When | Shape |
| --- | --- | --- |
| `hello` (text) | on connect and whenever the app on the panel changes | `{"type":"hello","app":id\|null,"meta":{id,name,category,icon,max_players},"avatars":{id:{name,px}},"server_time":t}` |
| `state` (text) | ~5 Hz when something changed, else a 2 s heartbeat | `{"type":"state","app":id\|null,"status":{…},"lobby":{…}\|null,"tv":{…}\|null,"server_time":t}` |
| frame (binary) | every new panel frame, ≤ 12 fps, latest wins | 32×32×3 RGB bytes, row-major (3072 B) |
| `closed` (text) | the TV link closed or the code is wrong | `{"type":"closed"}` then the socket closes |

- `server_time` is the engine's `time.time()` in **seconds**.
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
| `drawPanel(canvas, opts)` | paints the panel big: the HD look or the LED matrix (below) |
| `drawAvatar(canvas, id, color)` | an 8×8 avatar, pixel-crisp, in a player colour |
| `qr(text, canvas, opts)` | draws a QR code (`opts.size` CSS px, `opts.dark`, `opts.light`, `opts.quiet` modules) |
| `fmt(n)` | credits / scores: `12,345` (`fmt(1234567, true)` → `1.2M`) |
| `theme` | the casino table theme's `css` dict (`felt`, `felt2`, `felt3`, `accent`, `accent_hi`, `accent_lo`, `accent_deep`, `accent_rgb`, `ink`, `wing*`, `pattern`, `pattern_size`) or `{}` — `pattern` is the felt's motif: a gradient-only CSS `background-image` (no `url()`), `pattern_size` its `background-size` with one entry per layer; a canvas scene can paint it by drawing the felt through a DOM layer / `CanvasPattern`, or ignore it (see docs/CASINO.md §11) |
| `seatColor(n)` | a lobby seat's colour (the player's pick, else the seat default) |
| `el(tag, className, text)` | tiny DOM helper |
| `esc(s)` | HTML-escapes a string |

`ctx.drawPanel(canvas, {pitch, glow, round, data, look})`:
- sizes the canvas — `pitch` (stage px per LED) sets its CSS size to `32 × pitch`; otherwise it fills the canvas's
  current CSS size (`clientWidth`) — and its backing store to the device pixels it covers (× `TV.pixelRatio`,
  ¾ of that in lite, capped at 1600 px);
- `look` `"hd"` / `"led"` overrides `TV.look` for this canvas; `glow` 0..1 (default 0.6) is the bloom (hq only),
  `round` (LED look, default true) draws round LEDs with a dark unlit dot and a soft specular highlight (false =
  square pixels), `data` draws another 3072-byte frame instead of `ctx.panel`;
- costs a few `drawImage` calls per new frame (the upscale runs once per frame and is shared by every panel; static
  LED layers are cached per size); a call without a new frame (a status update) draws nothing.

Scene timing helpers: `TV.every(fn)` runs `fn(seconds)` on the page's **one** `requestAnimationFrame` loop (return
`false` to stop; it returns an unsubscribe function) — scenes never start their own rAF loops or `setInterval`s for
animation. Panel frames are drawn from the same loop (latest wins). A scene may implement `resize(ctx)` (the stage
scale changed); a tier change re-mounts it.

Shared CSS (in `tv.html`, use freely): tokens `--chassis-0…4`, `--line`, `--ink-1…4`, `--ember`, `--gold`, `--ok`,
`--warn`, `--bad`, `--info`, `--font` (system UI), `--mono`; the table theme as `--felt`, `--felt2`, `--felt3`,
`--accent`, `--accent-hi`, `--accent-lo`, `--accent-rgb`, `--ink` on `#stage` (classic green + gold when no casino);
classes `.tv-bezel` (the panel housing: machined frame, screws via `.tv-screw`), `.tv-card` (a raised surface),
`.tv-chip` (a status pill; `data-tone="ok|warn|bad|ember|gold"`), `.tv-label` (engraved uppercase label),
`.tv-big` (a large number), `.tv-avatar` (a canvas for `drawAvatar`). Type is sized for 3 m: labels ≥ 22 px,
body ≥ 28 px, hero numbers 80 px and up.

Scenes live in `src/deskdot/tv/`: `tv.js` (core + the generic scene), `tv-games.js` (games), `tv-casino.js`
(casino tables). A new file there must also be added to `tv.html` (and is copied by `scripts/build_webapp.py`).

## 5. The generic scene

Every app falls back to it: the live panel centred as a huge LED matrix in a bezel (round LEDs with bloom, a
recessed well and diffuser sheen), the app's name, category and the status chips (the status's simple values:
score, best, level, player, phase…) at the side, the lobby's players and the join QR when a lobby is open.

## 6. Performance on TV sticks (Fire TV, Android TV, Chromecast)

A TV stick has a phone CPU from years ago and a small GPU, and its browser (Silk on Fire TV) usually reports a
960×540 CSS viewport at devicePixelRatio 2. What keeps the view smooth there — keep it that way:

- **One loop, transforms for motion.** Everything that moves every frame (wheels, balls, dice, reels, stamps) is a
  pre-rendered canvas moved by `transform` / `opacity`. Style writes are skipped when the value didn't change.
- **Big canvases redraw rarely.** A casino scene's table layer redraws only when the status changed, while a chip or
  card is in flight (30 Hz, 20 in lite), or at the scene's slow rate (≈1 Hz while betting, 2–4 Hz for turn games).
  Countdown rings sweep in their own small canvases (`hudRing` in tv-casino.js), not in the table layer.
- **No blur per frame.** No `shadowBlur` in per-frame drawing in lite; text casts a hard offset shadow (the text drawn
  twice), never a blurred one. Chips, dice and housie balls are sprites drawn once (shadow baked in) and stamped.
  No `filter: blur()` / `backdrop-filter` in CSS, no animated `box-shadow` (glows pulse a pseudo-element's opacity).
- **Canvases match the screen.** Backing stores are sized to the device pixels they cover after the stage scale,
  capped, and ¾ of that in lite.
- **Measure.** A headless benchmark (CDP CPU throttling ×6 at 960×540 DPR 2, fixture statuses over a mocked TV socket)
  compares p50 / p95 frame intervals before and after a change; the numbers are in the change's report.

## 7. The casino chips

Tables show the chips the house allows (docs/CASINO.md §5): the rail lists the table's rack — `status.chips`, or the
same rack computed from `house.min_bet` / `max_bet` with a copy of the ladder when an older engine doesn't send it
(`chipRack` in tv-casino.js, tested against `casino/chips.py`). Every stack on the felt is its amount broken into
ladder chips (largest at the bottom, greedy), in the ladder's colours and edge stripes; the top chip's inlay is the
player's colour with the amount in K / M. A winning spot's stamp lands with a short burst of sparks — like every
reveal animation, a pure function of the shared clock, so every screen bursts in the same frame.

## 8. The web app (browser version)

In the web app the engine runs in the user's tab. The TV link's URL is `https://idotmatrix.com/tv/<code>`; Netlify
rewrites `/tv/*` to the join page (`web/webapp/join/`), which links the TV to the host tab over WebRTC (the same
tunnel the phones use: `host-rtc.js` also registers the TV code with the signalling function and lets GET `/tv/`
and sockets `/ws/tv/` through). The join page picks the `tv` template (built by `scripts/build_webapp.py` from
`tv.html`, with `/tv/static/*.js` copied to `/app/join/tv/`).

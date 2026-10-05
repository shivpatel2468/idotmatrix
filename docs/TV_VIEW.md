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
  web app (§6). The TV needs the same Wi-Fi as the computer (desktop) — exactly like a phone joining a game.
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
- States: *Waiting for DeskDot…* (connecting / reconnecting with backoff 0.5 s → 8 s), *This TV link has closed*
  (the studio stopped it or the code is wrong; the page keeps checking every 20 s in case the same code comes back).
- No scrollbars, the cursor hides after 3 s still, the screen never sleeps (Wake Lock API, re-acquired on
  visibility change), dark design using the studio's tokens.

## 3. The socket — `WS /ws/tv/{code}`

Server → TV only (the TV sends `{"type":"ping","t":…}`; the server answers `{"type":"pong","t","server_time"}`).

| Message | When | Shape |
| --- | --- | --- |
| `hello` (text) | on connect and whenever the app on the panel changes | `{"type":"hello","app":id\|null,"meta":{id,name,category,icon,max_players},"avatars":{id:{name,px}},"server_time":t}` |
| `state` (text) | ~5 Hz when something changed, else a 2 s heartbeat | `{"type":"state","app":id\|null,"status":{…},"lobby":{…}\|null,"server_time":t}` |
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
| `connected` | the socket is up |
| `now()` | local seconds (`performance.now()/1000` based, monotonic) |
| `serverNow()` | the engine's clock in seconds (`time.time()`), estimated from `server_time` |
| `drawPanel(canvas, opts)` | paints the LED panel big and realistic (below) |
| `drawAvatar(canvas, id, color)` | an 8×8 avatar, pixel-crisp, in a player colour |
| `qr(text, canvas, opts)` | draws a QR code (`opts.size` CSS px, `opts.dark`, `opts.light`, `opts.quiet` modules) |
| `fmt(n)` | credits / scores: `12,345` (`fmt(1234567, true)` → `1.2M`) |
| `theme` | the casino table theme's `css` dict (`felt`, `felt2`, `felt3`, `accent`, `accent_hi`, `accent_lo`, `accent_deep`, `accent_rgb`, `ink`, `wing*`) or `{}` |
| `seatColor(n)` | a lobby seat's colour (the player's pick, else the seat default) |
| `el(tag, className, text)` | tiny DOM helper |
| `esc(s)` | HTML-escapes a string |

`ctx.drawPanel(canvas, {pitch, glow, round, data, sizeToFit})`:
- sizes the canvas — `pitch` (stage px per LED) sets its CSS size to `32 × pitch`; otherwise it fills the canvas's
  current CSS size (`clientWidth`) — and its backing store to that × `TV.pixelRatio` (crisp on 4K);
- `glow` 0..1 (default 0.6) is the bloom, `round` (default true) draws round LEDs with a dark unlit dot and a soft
  specular highlight (false = square pixels), `data` draws another 3072-byte frame instead of `ctx.panel`;
- costs a handful of `drawImage` calls per frame (static layers are cached per size) — fine at 12 fps on a TV.

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

## 6. The web app (browser version)

In the web app the engine runs in the user's tab. The TV link's URL is `https://idotmatrix.com/tv/<code>`; Netlify
rewrites `/tv/*` to the join page (`web/webapp/join/`), which links the TV to the host tab over WebRTC (the same
tunnel the phones use: `host-rtc.js` also registers the TV code with the signalling function and lets GET `/tv/`
and sockets `/ws/tv/` through). The join page picks the `tv` template (built by `scripts/build_webapp.py` from
`tv.html`, with `/tv/static/*.js` copied to `/app/join/tv/`).

# Changelog

The technical log for developers. For the same updates in plain words (before → now), see
[WHATS_NEW.md](WHATS_NEW.md).

## 3.9.0 — 2026-10-31 · Table themes everywhere; web app parity; panel hand-over

- **Watch themes** (`scripts/gen_watch_themes.py` → `android/wear/.../WatchThemes.gen.kt`): the 21 table themes as plain Kotlin (ARGB ints, dark + light, gold-leaf stops) for the Wear OS apps, from `PAGE_THEMES.tokens()` like `gen_page_themes.py`; `--check` and `tests/test_watch_themes.py` catch a stale file; `--out/--package` writes another app's copy (Orbit, the watch faces). New `android/wear/SPEC.md` (R-WEAR-1…5).
- **Web app re-audited** (docs/WEB_APP.md): the engine of 3.3–3.8 (page themes, paper panel, Liquid Glass, TV view +
  options menu over the WebRTC tunnel, casino dolly / chip sets / odometers / win moment, the 14 public-API apps, API
  health, connection sheet, updates) boots in Pyodide 0.29.5 (verified headless: 116 apps, 4 off-web); every
  non-proxied provider endpoint sends CORS headers. `site/app` must be rebuilt (`scripts/build_webapp.py`) to ship it.
- **Now Playing on web**: `providers/media_web.py` `WebBackend` (ListenBrainz `playing-now`, Last.fm
  `user.getRecentTracks` with the user's key, or typed in; 15 s cache, no controls, `player_art=False` skips the
  player-art retries); settings `web_source`/`web_user`/`web_api_key`/`web_title`/`web_artist` (`platforms: ["web"]`);
  `FEATURES["media"]` += web; app `platforms = (*DESKTOP, "web")`.
- **System Monitor on web**: `providers/system.py` `browser_stats()` fed by `host.js` (`{t:"sys-stats"}` every 2 s:
  Compute Pressure, `performance.memory`, Battery, Network Information, rAF fps, cores, deviceMemory) through
  `worker.js` → `web_main.sys_stats()`; `FEATURES["system"] = ALL`; bars read CPU / MEM / BAT in a tab.
- **Updates on web**: `build_webapp.py` writes `site/app/version.json` (`{version, build, notes}` = the newest
  WHATS_NEW section); `Updater(kind="web", web_version_url, build)` checks it every 30 min; `info` adds `build`,
  `latest_build`; `brief` adds `kind`, `latest_build`; studio: "New version — reload" pill, *Reload to update*;
  `sw.js` never caches `version.json`; `worker.js` passes `manifest.build` to `web_main.boot(build=)`.
- **Build**: `desktop.py` left out of the engine archive; index.html's inline pre-paint script stripped (the /app/ CSP
  blocks it; host.js does the same work); build id also hashes the studio assets and the TV font.
- **Studio**: `DesktopAppNote` / `DesktopAppLink` — on web, Not-on-Browser banners, On Air, eye break, OS
  notifications, sleep hand-off and autopilot say why in one line and link to `/download.html`.
- Tests: `tests/test_web_apps.py` (Now Playing sources, browser stats, off-web set, CORS hosts, version.json, inline
  script, archive exclusions), `tests/test_updates.py` (web build check), `test_compat` / `test_web_device` updated.
- **Page themes = `TABLE_THEMES`**: the table data moved to `src/deskdot/gfx/tables.py` (re-exported by
  `apps/_casino.py`); `gfx/themes.py` builds the 21 page themes from it (same ids / names) with `screen_tokens()` (dark =
  the dark casino's room, surfaces, inks, accent, felt glow + motif; light = the porcelain salon, AA-pushed) and LED
  palettes whose hero is the table's LED accent. Default `cyber`; `LEGACY` maps `ember`/`graphite`/`sunset`/`citrus`/
  `glacier` → `cyber`/`noir`/`volcano`/`arcade`/`arctic` (stored state, `POST /api/theme`, the browser). Theme-aware apps
  follow every theme, the default included; `deskdot preview` without `--theme` draws own colours.
  `scripts/gen_page_themes.py` writes `web/src/lib/pageThemes.gen.ts` + `web/src/pageTheme.default.gen.css` (a test
  fails when stale); index.css § TABLE ROOM styles the dark studio's panels as casino wings. First run: Cyber grid,
  dark (studio, launcher, `webapp/host.js`, Android bars/resources); in the web app `deskdot.siteTheme` leads and is
  written back. The top bar's Casino key pins classic gold (`.cz-gold-top`; the page theme's `--gold` leaked into it).
- **TV view**: hello / state carry `page_theme`; `src/deskdot/tv/tv-themes.js` (generated) holds every theme's TV
  tokens; `tv.js` `applyRoom` wears the page theme outside the casino (`stage[data-room]`) and the table at a casino
  table; the bar is a static faux-glass capsule, cards / menu are wings, accents follow. Benchmark (CPU ×6, 960×540
  DPR 2, software compositing, 12 s): clock p50/p95 16.7/16.8 ms both, busy 25.8 → 25.9 %; roulette 16.7/33.3 ms
  both, busy 69.5 → 66.7 %. `build_webapp.py --skip-studio` keeps `web/public` files (intro GIFs).

## 3.8.0 — 2026-10-29 · Desktop installers, a signed release APK, in-app updates

- **Installers** (`packaging/`): PyInstaller onedir spec (`deskdot.spec`; bundles `web/dist`, `deskdot.example.toml`,
  the package's html/js/fonts; excludes tests, legacy, mcp, Android/browser-only modules). Windows: `DeskDot.exe`
  (windowed) + `deskdot-cli.exe` (console), Inno Setup script `windows/DeskDot.iss` → `DeskDot-Setup-<v>-x64.exe`
  (per-user, no UAC; Start menu, optional desktop icon and start-with-login under the launcher's
  `HKCU\…\Run\DeskDot Launcher` value; uninstaller; waits for a running DeskDot on silent updates and relaunches it).
  macOS: `.app` with Info.plist usage strings (Bluetooth, microphone, camera, Apple events, local network) and
  `macos/build_dmg.sh` → `DeskDot-<v>-macOS-{arm64,x64}.dmg` (ad-hoc signed; Developer ID + notarization when the
  optional secrets exist). `packaging/prepare.py` draws the icons and the Windows version resource.
- **`src/deskdot/desktop.py`**: the frozen app's entry. Per-user home (`%LOCALAPPDATA%\DeskDot`,
  `~/Library/Application Support/DeskDot`, `$XDG_DATA_HOME/deskdot`; `DESKDOT_HOME` overrides), first run copies
  `deskdot.example.toml` → `deskdot.toml` there, `chdir`s to it, points `DESKDOT_WEB_DIST` at the bundle, routes
  stdout/stderr of the windowed exe to `data/deskdot.log`; no arguments = start the engine (detached), open the
  studio, run the launcher (tray + hotkey); any CLI subcommand runs as usual. `launcher.engine_command()` /
  `autostart_command()` know the frozen exe.
- **In-app updates** (`src/deskdot/updates.py`): `GET https://api.github.com/repos/shivpatel2468/idotmatrix/releases/latest`
  with a 6 h cache persisted in `state.json` (`updates.release`, `updates.checked_at`), opt-out `updates.auto_check`
  (default on; `DESKDOT_UPDATE_CHECK=0` disables the background loop); semver comparison incl. pre-releases;
  asset per install kind (`windows` / `macos` arm64|x64 / `android`; `source` and `web` never install); only
  `https://github.com/<repo>/releases/download/…` URLs, HTTPS enforced on every redirect hop, 600 MB cap;
  SHA-256 checked against `checksums.txt` (or `<asset>.sha256`), refused and deleted on mismatch or when missing.
  Hand-off: Windows runs the installer `/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS`, quits the launcher and
  exits the engine (SIGINT → normal hand-off, hard exit after 20 s); macOS swaps the `.app` in place after the engine
  exits (or opens the dmg when the folder isn't writable); Android calls `Updater.install()`. API:
  `GET /api/updates`, `POST /api/updates/check`, `PUT /api/updates`, `POST /api/updates/install` (409 with a
  message on refusal); `state.updates` on the websocket (status, progress). Tests: `tests/test_updates.py`,
  `tests/test_desktop.py`.
- **Studio**: `components/Updates.tsx` — Settings → Device → Updates (version, Check now, auto-check, release
  notes rendered from WHATS_NEW-style markdown without HTML injection, Install & restart with progress) and the
  "Update available" pill in both top bars (dismissable per version; one toast per version). `#settings/updates`.
- **Android**: versionName/versionCode come from `src/deskdot/__init__.py` (`major*10000+minor*100+patch` → 30800);
  release signing from the git-ignored `android/keystore.properties` (debug key only as a fallback, with a warning);
  APK named `DeskDot-<v>.apk`; `Updater.kt` (FileProvider `<pkg>.updates` over `files/data/updates/`,
  `REQUEST_INSTALL_PACKAGES`, same-signer check before opening the installer).
- **CI**: `.github/workflows/release.yml` on `v*` tags — version/WHATS_NEW check, ruff + fast tests, studio build,
  Windows installer (+ frozen-engine smoke test on :8799), macOS arm64 + x64 dmgs (+ smoke test), `checksums.txt`,
  a draft release with that version's WHATS_NEW section. Optional signing secrets documented in docs/DEPLOY.md.
- Dependency group `packaging` (`pyinstaller`); `.gitignore`: `.claude/`, `android/keystore.properties`,
  `packaging/build/`.

## 3.7.0 — 2026-10-12 · Page themes; apps follow the theme; luxury TV casino, win moment, dollies, chip sets, odometer credits

- **Now Playing** (`apps/nowplaying.py`, drawing kit `apps/_npdraw.py`): 8 new layouts — `wordpop`, `big_title`
  (2× bitmap type), `cassette`, `vu` (needles with VU ballistics / LED ladders), `cd`, `radio` (FM/AM dial, needle
  sweep per track), `mosaic` (posterised tiles, reveal + glint), `waveform` (audio history or synthetic); 24 new
  settings in groups Track info / Lyrics / Song change / Paused & idle / Art / Layout options: `show_album`,
  `show_source` (generic glyphs only), `scroll_style` (marquee/bounce/page), `highlight` (sweep/word/underline),
  `line_spacing`, `translation` (LRC lines sharing a timestamp → `Line.translation` in `providers/lyrics.py`),
  `transition` (cut/slide/dissolve/zoom; a late cover dissolves in), `rotate`/`rotate_set`/`rotate_every`,
  `pause_style` (auto/dim/badge/freeze/idle after 20 s), idle screens `covers`/`waves`/`silence` + `wall_size`,
  `art_style` (smooth/pixelated/posterised/dithered, calibrated before styling), `dither`, `art_colors`,
  `art_contrast`, `art_saturation`, and per-layout options. `status()` adds `layout`, `album` and `actions`;
  `demo_frame()` / `demo_png()` render any layout for a procedural demo song → `GET /api/nowplaying/layouts/{id}.png`.
  Media backends expose `can_control` (Windows always; macOS Spotify/Music or nowplaying-cli; Linux playerctl) →
  provider value `controls`. Studio: Stage filters action buttons by `status.actions`; `components/MusicDeck.tsx`
  in the full-screen view (track, transport, visual layout picker). Tests in `tests/test_music.py`, `tests/test_api.py`.
- Live Scores: goal / score alerts (the celebration overlay that interrupts other apps) default to Off.
- **Page themes** (studio-wide, separate from the casino's table themes): 21 themes in `gfx/themes.py` `PAGE_THEMES`
  (`ember` = the original look and the default; studio originals `graphite`, `sunset`, `citrus`; 17 adapted table
  concepts). Each has screen seeds (accent, accent_light, metal, tint, gradient-only pattern) and an LED
  `PanelPalette` (accent, accent2, accent3, text, mute, soft ≥ 100, track ≥ 45). `GET/POST /api/theme` (422 on
  unknown ids), `state.settings.page_theme`, MCP tool `page_theme`. Engine: `set_page_theme()` stores the pick at
  once; the panel follows after 1.2 s of quiet and at most every 6 s (`THEME_SETTLE_S`, `THEME_MIN_GAP_S`) so clip
  re-bakes stay within the GIF upload budget. Studio: `lib/pageTheme.ts` (mirror of the seeds, `derive()` with AA
  checks, `themeCss()` scoped to `:root[data-page-theme]:not([data-cz])`, one adopted stylesheet, View Transition
  cross-fade, engine sync with a local fallback in `deskdot.pageTheme` / `deskdot.pageThemeCss`), first paint from the
  cache in `index.html`, `launcher.html`, `webapp/host.js` and `controller.html`; `components/PageThemePicker.tsx`
  (Settings grid with LED dots, Display menu + Quick controls dot rows); `meta theme-color` and the Android bars use
  the tinted colours (`pageBars()`); remaining literal accent colours in `index.css` became token mixes; the dark
  body uses `--m-texture`. docs/STUDIO_UI.md § Page themes.
- **Apps follow the page theme** (docs/APP_SDK.md § Page theme): `App.theme_colors` ({colour setting: role}, applied by
  `themed_settings()` to fields still at their default — stored settings untouched), `App.follows_theme`,
  `App.theme` / `App.themed(role, own)`, an auto-added `follow_theme` switch per theme-aware app (opt-out),
  `clip_key()` includes the theme, previews and `deskdot preview --theme` render in it. Wired: clock, countdown,
  fiveoclock, holidays, timer, calendar, habits, sysmon, currency, uptime, ci, hassentity, airquality, weather,
  space, quakes, rainradar, headlines, daily, trivia, text, fontlab, visualizer (new "Page theme" palette), loops,
  nowplaying, native. Not following: casino, games (genre themes), pets, photos / gallery, flags, agent.
  `tests/test_page_themes.py`.

- **TV casino redesign** (`tv/tv-casino.js`, docs/TV_VIEW.md §6–7): luxury table art in the cached background
  (`luxTable` felt + lacquered mahogany rail with brass inlay, `damask` salon wall, overhead lamp + vignette,
  `softStroke` stacked-stroke shadows instead of `shadowBlur`, embossed / gold-leaf serif text via `txt` options
  `emboss`, `gold`, `font: "serif"`, `spacing`; brass bowl, metal frets and turret; leather racetrack on the poker
  tables); a seat gallery (`plaque`, `railLayout`, `railSeat`) with DOM odometer credits (`Odo`, `odoPos`) and live
  stacks; the panel inset only once frames arrive. Roulette: ball streak sprite + hop scale, camera push-in / pan
  (`S.cam` → `rootFx`), payouts pushed from the dealer, losing stacks swept. 3D card turn in `drawCard`, dice tumble
  rotation, slot reel smear. Table-mode header in `tv.html` (serif gold-leaf name, gilded double rule).
- **Win / lose moment** (TV): anchored on `status.clock.phase_at`; `momentOf` / `momentFrom` / `momentFrame` /
  `momentIngest`, tiers `winTier` (net ÷ stake ≥ 30 / 10 / 3 → jackpot / mega / big, else win; house), `tickerAt`
  count-up, pooled sprites (banner + rays cached per tier and pre-warmed while betting, flash, 30 coins, 14 sparks,
  8 plaque overlays, `flight` stack pool), screen shake, credits held until the coins land (`creditsHeld`); idle
  sprites `display: none`. Late screens (> 2.6 s) show the settled state.
- **Dolly styles**: `House.dolly` (`casino/session.py` `DOLLIES`, select schema, validator; default `classic_gold`)
  in `status.house`; TV `DOLLY_STYLES` (8 sprite styles, `dollyPaint`), dealer-hand path `dollyPath` (rest → lift →
  glide → set down → settle, click ring), `DOLLY_AFTER` 0.95 s after the ball settles; phone `.rt .dolly[data-dolly]`;
  studio `LeftWing` `DollyPicker`.
- **Chip sets**: `casino/chips.py` `CHIP_SETS`, `THEME_CHIP_SET` (one per table theme), `chip_set_for`; `House.chip_set`
  (`auto` | set); `status.chip_set`; TV `chipSprite` per set (`chipSetOf`), phone `html[data-chips]`, studio
  `.cz[data-chips]` + `ChipSetPicker`. Ladder colours / labels unchanged.
- **Odometer credits** in the studio (`bits.tsx` `Credits`, rAF transforms, reduced motion) and the phone's bank
  plaque (`odoSet`); phone win moment (`casino.html` "shared win moment" block: `winTier`, `tickerAt`; rays, tier
  word, coin fountain, shake, per-tier vibration, phase_at-anchored count-up).
- **Result data**: `status.result.winners[].stake`, new `status.result.losers` (`casino/table.py`).
- Tests: `tests/test_casino_dolly.py`; `tests/js/tv_casino.test.mjs` (+7: phone/TV tier agreement, moment anchor,
  moments on every table, dolly path and landing, odometer reels, chip sets); fixture regenerated. Benchmark (6×
  CPU, 960×540 @2, software): roulette p95 16.8 ms (before 16.8), baccarat p95 33.4 ms (before 50.0, lite), tetris
  unchanged; main-thread busy +14–23 pts.
- **TV view polish** (`tv.js`, `tv.html`, `tv-casino.js`, `tvlink.py`): fixed the options menu — `choose(key, v)` was
  shadowed by the hoisted scene matcher `choose()`, so Panel look / Quality picks never applied (now `chooseDisplay` /
  `matchScene`); clicks are taken on `document` (also during the theme's View Transition, by geometry), press / pick
  feedback, Space and D-pad centre (keyCode 23), 12 s idle. Menu text contrast in both themes (a table no longer
  forces dark tokens). New TV menu rows *Dolly* (roulette) and *Chips* at a casino table, drawn with the real sprites
  (`TV.casino.previewDolly` / `previewChips`, `dollyBody` factored out of `dollyPaint`), sent as
  `{"type":"house","dolly"|"chip_set"}` on the TV socket — `TvHub._house` / `house_patch`: one key, known values only,
  casino table only, valid code, ≤ 4/s per TV; replies `house_ok` / `house_err` (`tests/test_tv.py`). Light theme
  restyles the whole casino (`ROOMS` palette: ivory walls, white-lacquer rail with gold inlay, ivory plaques and
  gallery, champagne panel housing, room inks via `roomInk`; `scene.restyle` redraws the cached layers once, inside a
  View Transitions cross-fade); light casino header in `tv.html`. Header: three columns, logo centred;
  `DeskDotLogo.mount({once})` builds in once then holds lit (all five copies). Type: self-hosted Bricolage Grotesque
  (`tv/tv-sans.woff2`, 41 KB, SIL OFL — `tv/OFL.txt`; served by `/tv/static/`, copied by `build_webapp.py`), `--serif`
  display titles, tabular numerals. Studio: Casino → House shows Dolly (roulette) and Chip set first. Tests:
  `tests/js/tv_menu.test.mjs` (headless Chrome: click / tap / keys / remote on every tile; skipped without
  playwright-core + Chrome), `tv_casino.test.mjs` +2 (light room on every table, restyle; menu previews). Benchmark
  (6×, 960×540 @2): roulette p95 33.3 ms, baccarat 33.3, tetris 16.8 (dark and light alike).
- **Casino light mode lit by the table theme** (studio `casino.css` light block, phone `casino.html` light block):
  `state.ts` `lightSwitches()` derives `--cz-tint` (the felt, or the accent when the felt is near-grey: cyber, noir,
  deco, arcade, volcano) and `--cz-pale` (1 for ivory / champagne / ice accents: emerald, burgundy, noir, arctic),
  set by `themeVars()` (+ `--cz-page-tint` in `pageVars()`); `casino.html` `applyTheme()` mirrors them as `--tint` /
  `--pale`. Light surfaces mix `--cz-room` (felt 70 % + tint) into porcelain (wings 13–15 %); wings, rails, section
  rules, host bar, lobby strip, empty states, rows, rack, board and the table plinth carry tint washes and accent
  glow lines (`--cz-glow`); cards (game / preset / theme / chip set / dolly) get a tinted foot and a gilded selected
  state (accent wash, metal ring, accent halo); chip sets and dollies sit on a felt well; primary keys use
  `--cz-key` (accent leaf, or the felt with accent lettering when pale); accent-as-text deepens the felt when pale;
  `text-[var(--gold)]` utilities read `--gold-text` in light. Mute / dim inks darkened (AA ≥ 4.5 on every light
  surface for all 21 themes, incl. the wing foot). Dark mode unchanged (pixel-diffed).
- **Paper panel** (light mode's LED preview; studio only — the panel and the engine's frames are unchanged):
  `lib/paper.ts` maps every frame colour perceptually (OKLab/OKLCH: lit amount = brightest channel; neutrals → ink
  `#1c1a22`, chromatic colours keep hue + relative chroma at a per-hue lightness darkened to ≥ 4.5:1 on the unlit LED
  `#ebe6dc`, yellows lean ≤ 14° toward gold; dim colours blend ground → ink with chroma arriving first), cached per
  exact colour. `LedPanel` draws paper versions of Glow (multiply halo), Pixel and LED (cached porcelain housing) and
  cross-fades on theme change (`crossFade()`); `raw` (calibration) and the new `device` prop (fly view) keep the dark
  device. `lib/paperImg.ts` lays a mapped canvas over every `.led-preview > img` / `.lx-led > img` (library, AppRail,
  casino tiles, launcher) — own GIF decoder, frames mapped once per URL (LRU 48), one timer for visible canvases.
  `html[data-panel="paper|device"]`; Display menu → *Panel preview in light mode* (Paper · Dark device,
  `localStorage deskdot.panelLight`, part of Reset). Light `.bezel` becomes porcelain enamel (not `.cz-bezel`,
  `.fly-full-bezel`); `--led-gap` (registered, fades) colours thumbnail masks; `.led-well`; preset covers tint via
  `--led-paper`. Logo: `lib/logo.ts` `NEON_STYLE` / `PAPER_STYLE` (ink tubes `#c2154d` / `#996300`, multiply halo,
  sheen core), `NeonLogo.setLook()`; `NeonMark` follows `<html data-theme>` with a cross-fade on a porcelain gilded
  `.led-plate`; the `// <deskdot-logo>` copies take `look` and follow their page's theme (`mount(…, { light })`, live),
  swapping a page's dark logo sign for `PAPER_PLATE`; tv.html, controller.html, join.css and host.css plates are
  porcelain in light. `tests/test_logo_copies.py` compares both styles and checks the paper tubes' contrast.
  docs/STUDIO_UI.md § Paper panel.
- **Liquid Glass + light mode without dark spots + no logo plate.** `index.css`: `--lg-*` tokens (light/dark, mixed
  from the chassis so page themes tint them) and `.glass` / `.glass-thick` / `.glass-capsule` / `.glass-control` /
  `.glass-lens` (element transparent + isolated; `::before` = tint, sheen, inner light, `backdrop-filter: blur()
  saturate()`; `::after` = 1 px gradient rim with a pointer-tracked specular spot); applied to `.surface` (all
  panels, menus, dialogs, toasts), `.tabbar` (floating capsule + morphing lens), `.phone-head`, `.sheet` (floating,
  34 px radius), header toolbar capsules (`.lg-toolbar`), keys (capsules, spring squash), `.seg`, `.toggle`, `.fader`
  (glass knob), chips, badges (`.lg-badge`), veils (`.lg-veil`). `lib/glass.ts`: `<html data-glass="liquid|frosted|
  solid">` (inline pre-paint in `index.html` / `launcher.html`; reduced transparency → solid; no backdrop-filter,
  `window.DeskDotAndroid` or ≤ 4 GB / ≤ 4 cores → frosted), `html.lg-lens` (SVG `feDisplacementMap` edge lens via
  `backdrop-filter: url(#lg-lens)` on Chromium + fine pointer), pointer / tilt specular, Display menu → More → Glass;
  touch screens: blur only on the small fixed bars. Glass panels rise with a transform-only animation (an opacity
  animation makes a backdrop root). Light: `--color-scrim` is a porcelain veil, `.theme-dark` forced subtrees reduced to
  the fly's 3D panes and the chosen dark device; paper bezel for `.cz-bezel` and `.fly-full-bezel` (fly panel follows
  paper); light hazard guard, roam tip, page-theme LED dots, casino rail / felt rim / marquee bulbs, AI preview
  (`paperHex`), Now Playing layout tiles (`.led-preview`), theme tiles. `.led-plate` and the logo copies'
  `PAPER_PLATE` removed (and the pages' logo sign CSS). Cross-fade overlay canvases start at 0×0 (their default
  300×150 widened phone pages). Phone pages, web app, launcher and TV (static faux glass, no `backdrop-filter`; paper
  panel ported to `tv.js`) mirror the tokens.

## 3.6.0 — 2026-10-09 · Light theme, phone app, connection, TV options, API health, 14 new apps

- **Themes:** a light theme ("Gallery") beside dark, one switch Light · Dark · Auto (`web/src/lib/theme.ts`, key
  `deskdot.theme`, `data-theme` on `<html>` set before first paint; Settings → Display & colour, the Display menu,
  phone Quick controls and a floating key bottom-left on phones). Tokens per theme in `web/src/index.css` plus the
  "MATERIALS v2" `--m-*` materials (daylight, washes, linen + dot texture, wells, cards, bevels, gold leaf, brass,
  sheen, accent halos) — static gradients only, no reliance on `backdrop-filter`. The logo sits on a dark LED plate
  in light. Mirrored in casino.html, controller.html, join pages, the launcher, the web-app landing and the TV
  (TV defaults to dark; `?theme=light` or the TV menu's Theme row). Light casino "salon": felt rails under the wing
  tabs, gilded keys in the table's accent, a champagne plinth; all 21 table themes adapt (bronze text =
  accent 33 % + ink, ≥ 4.97:1); the table theme id moved to `html[data-table]`. docs/STUDIO_UI.md "Themes".
- **Android app:** highest refresh rate requested (120 Hz), hardware accelerated, `DeskDotAndroid` JS bridge —
  `setBars()` colours the status / navigation bars and window for the theme, `setIcon()` switches between 7
  launcher icons (`<activity-alias>` each, adaptive + monochrome, drawn by `android/tools/gen_icons.py`; Settings →
  App icon inside the app); keeps retrying the studio until the engine is up; clears the WebView cache once per
  install (APK assets share one mtime, so a same-size page would revalidate as unchanged). Links off 127.0.0.1 open
  in the browser.
- **Phone studio:** apps in swipeable rows right under the panel (`AppRail`, Favourites / Recent / categories),
  duotone icons (`IconTile`), preset cards with LED covers, `Picker` bottom-sheet dropdowns, opaque bars and a
  sticky search pinned flush (nothing shows through), LED panel drawn at most once per refresh and only on change.
- **Connection:** `ConnectionSheet` (one status pill → where the panel is connected, signal, attempts, one primary
  action), `device/diagnose.py` (human reasons + next step), `POST /api/device/reconnect {only_if_down}`
  ("Reconnect now" cuts the back-off, never disconnects), explicit "Release the panel" (ADR 0013), `/api/health`
  adds `kind` / `panel` / `link_enabled` (CORS + Private-Network-Access only for idotmatrix.com). Web app: cross-tab
  handover (BroadcastChannel + Web Lock, "Use it here" / "Take it back"), silent reconnects via `getDevices()` +
  advertisements, detects the desktop engine holding the panel.
- **Display menu:** the top-bar gear opens a small menu (Glow / Pixel / LED tiles with live previews, one Glow
  slider, "More", Reset) instead of the full Settings page (`DisplayMenu.tsx`).
- **TV:** the options menu (OK / menu on the remote) and the studio's Show on TV sheet (`POST /api/tv/settings`)
  set the panel look (Pixel · LED · Glow, like the studio; the HD upscale is gone), quality (Auto · HQ · Lite —
  Lite now draws the same picture as HQ, both faster) and theme.

- API health: every provider declares the external URLs it calls (`Provider.endpoints`, `providers/base.py`
  `Endpoint` with a concrete sample, `expect` paths and a `check` that runs the provider's own parser).
  `scripts/api_health.py` probes them all (status, latency, shape, CORS / proxy reachability for the web app), prints
  a table, writes `docs/API_HEALTH.md` and exits 1 when a primary endpoint fails. `tests/test_api_health.py` keeps
  the registry complete (every provider module with a URL declares endpoints) and tests the checker offline.
- Fixed (found by the health check; tests on recorded payloads in `tests/fixtures/health/`):
  - Photo Frame / The Met: `public/collection/v1/search` was retired on 2026-10-01 (410) → `v1.1/search`
    (paginated; a random page once the total is known).
  - Stocks: the Stooq fallback is dead (quote CSV 404, downloads behind a JS challenge) → replaced by
    `api.nasdaq.com/api/quote/{SYM}/chart` (`parse_nasdaq`; US stocks/ETFs + `^IXIC`/`^NDX`).
  - Flight Radar: airplanes.live answers 403 to anonymous clients → replaced by `opendata.adsb.fi` (`parse_readsb`
    reads `aircraft` as well as `ac`).
  - Headlines: Hacker News falls back to `hn.algolia.com` when Firebase fails (ISP DNS blocks of `*.firebaseio.com`).
  - Crypto Ticker (`markets`): on 451/403 from `api.binance.com` (US geo-block) the provider switches to
    `data-api.binance.vision` for the session.
  - CORS proxy allowlist: + `api.nasdaq.com`, `opendata.adsb.fi`, `ssd-api.jpl.nasa.gov`; − `stooq.com`,
    `api.airplanes.live`.
- New apps (keyless APIs from the public-apis list plus NOAA / NASA / Jolpica, all verified live; providers in
  `src/deskdot/providers/`, shared app helpers in `apps/_feed.py`, tests on recorded payloads in
  `tests/test_publicapis.py` + `tests/fixtures/publicapis/`): `aurora` (Aurora Watch — NOAA SWPC Kp, Kp forecast,
  OVATION nowcast; provider `spaceweather`), `btcnet` (Bitcoin Network — mempool.space; `bitcoin`), `cryptomarket`
  (Crypto Market — CoinGecko global/markets + alternative.me Fear & Greed), `racecountdown` (Race Countdown — Jolpica,
  the Ergast successor; `racing`), `longweekend` (Long Weekend — Nager.Date LongWeekend), `bikeshare` (Bike Share —
  CityBikes), `earthevents` (Earth Events — NASA EONET), `worldflags` (World Flags — flagcdn.com; `flags`),
  `rainchance` (Rain Chance) and `windcompass` (Wind Compass) — both Open-Meteo hourly (`hourly`), `wikitrending`
  (Wiki Trending — Wikimedia featured feed; `wiki`), `asteroidflyby` (Asteroid Flyby — JPL SBDB close-approach API,
  proxied on the web; `asteroids`), `gameserver` (Game Server — mcsrvstat.us), `tvtonight` (TV Tonight — TVMaze;
  `tvguide`).
- Photo Frame: new source "Picture of the day (Wikimedia)" (`potd`: the last week's featured pictures).
- Not adopted, noted in docs/API_HEALTH.md: REST Countries now needs a key; dictionaryapi.dev answered 522.

## 3.3.0 – 3.5.0 — 2026-10-02 to 2026-10-07

(3.3.0 = up to 2 Oct, 3.4.0 = 4 Oct, 3.5.0 = 5–8 Oct; newest first.)

- TV view: the panel has the studio's three looks — Pixel, LED (default) and Glow, drawn like the studio's preview —
  and the HD upscale is gone. An options menu on the TV (OK / menu on a Fire TV or Android TV remote, a click or a
  tap) picks the look and the quality (Auto · HQ · Lite), applied at once and remembered on that TV; the studio's
  Show on TV sheet sets both for every TV of the link (`POST /api/tv/settings`, sent to TVs as `display`). Lite now
  draws exactly the same picture as HQ (same resolution, glows, particles, animations): both got faster instead —
  big canvases are handed to the page as finished bitmaps (no per-frame copies under software compositing), glows in
  redrawn layers are cached sprites instead of `shadowBlur`, the panel's bloom is a CPU blur added by the compositor.
- TV view: the panel keeps its classic LED look by default (the HD upscale is opt-in: `?look=hd` or select on the
  remote); roulette marks the winning number with a crystal dolly on a gold base, lowered by the dealer, instead of
  the stamp and sparks.

- Casino chips: high-roller tables now offer 1K, 2K, 5K … up to 1M chips, and chips the table doesn't allow are
  no longer shown at all — the same rack on phones, the laptop and the TV.
- Casino: a rejected bet ("Table min is …", "Not enough credits") now pops up big in the middle of the screen. Before,
  the host on the laptop saw nothing and phones showed it tucked into the header.
- Phones: a new top bar — the credits no longer run into the avatar and buttons; big balances shorten (1.25M).
- Roulette: chips can be dropped or clicked onto a line (split), a crossing of four numbers (corner), a row's edge
  (street) and between rows (six line); dragging with a mouse is smooth on the laptop and on phones.
- Studio: a gold TV key under the panel (next to the QR key) opens Show on TV; "Show QR" brings the join code back.
- TV view: much smoother on a Fire TV (heavy effects removed, a lighter mode kicks in by itself on slow TVs), games
  shown as a sharp HD picture of the panel instead of big glowing dots (select on the remote toggles the classic
  LED look), chips in the table's colours, and a burst of sparks when the winning number is stamped.
- Intro & outro: each theme in Settings now shows a small moving preview under its name. The OG intro was
  redrawn: clean flat LEDs in the two logo colours that glide smoothly into place, with no glare, halos or reflection.
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

# DeskDot design taste — read before designing anything

The owner's taste, distilled from building DeskDot with them (Oct 2026). It applies to **every** surface: the
desktop studio, the browser app (/app), the Android phone app, the Wear OS watch app, the TV view, the phone casino
and controller pages, idotmatrix.com and the GitHub profile. When a choice isn't covered here, pick the option that
is *more premium, more alive and less cluttered*, and show the owner a screenshot before shipping.

## 1. The theme system is the casino's table themes
- The **21 casino table themes** (`src/deskdot/gfx/tables.py`; generated tokens in `web/src/lib/pageThemes.gen.ts`
  and `src/deskdot/tv/tv-themes.js`; the website's `scripts/site_theme.py`) are THE themes everywhere: studio, /app,
  phone app, watch app, TV, website — same ids and names (Cyber grid, Classic green, Royal blue, Crimson velvet,
  Midnight neon, Neon strip, Riviera noir, Imperial jade, Gilded deco, Pixel arcade, Sakura night, Galaxy, …).
  Never invent a separate palette for one product — generate from the tables.
- **Default: Cyber grid, dark.** Dark mode must look exactly like that table's room in the dark casino: felt and
  room tones on the background and panels, the felt motif as a faint texture, the table's accent on selected
  states, switches, buttons, focus, progress and glows. "Mostly grey with a dash of colour" is a bug.
- **Light mode** is the casino's porcelain salon in the table's colours — never flat white; nothing black left
  over (except the "Dark device" panel option, photos/video and game colours).
- Saved choices persist and sync across devices; switching cross-fades, never flashes.

## 2. Materials and finish
- **Liquid Glass** (Apple-style, built by us — never Apple's assets): tinted glass that blurs what's behind, a top
  sheen, a lit hairline rim, soft depth, capsule controls that squash/stretch on press. Always thick enough that
  text never reads through; frosted where blur is slow or unsupported (Android WebView, TV sticks, low-end phones —
  **static/baked glass** on the watch and TV), solid for reduced transparency. Glass on floating chrome only,
  never on large scrolling areas.
- **Luxury casino details**: gold leaf, brass, lacquer, embossed chips, engraved small caps, fine rules, felt.
- **Floating glass capsule header** (website): pinned flush, nothing visible above or around it, every item inside.
- The **LED logo** (rose `#ff3f78` "Desk", gold `#ffcc33` "Dot"; paper variant in light): never boxed; lit steadily
  after one build-in; animate only on load or hover (battery and scrolling).

## 3. Energy, motion and feel
- **Arcade dopamine** where it matters: WINNER / BIG WIN / MEGA WIN / JACKPOT banners, coin fountains, slot-machine
  odometer numbers, dollies and stamps, satisfying haptics — synced across devices.
- **Smooth above all**: 60 fps on TV sticks, 120 Hz on phones; nothing animating forever in the background; no
  stutter, layout jumps or glitches (the owner notices immediately). Measure, don't guess.
- **Seamless sync**: every device shows the same moment at the same time (shared clock).

## 4. Layout and options
- **Use the space** on big screens (wide layouts, multi-column grids); comfortable measure for prose.
- **Simple first, depth on demand**: a few big visual choices (picture tiles with live previews), the rest under
  "More". Show options as pictures, not lists of names.
- **Customisation is loved**: themes, dollies, chip sets, layouts, icons, looks (Pixel / LED / Glow), quality
  (Auto / HQ / Lite with no visible loss). Offer variety; choose a beautiful default.
- **Plain words** everywhere: short labels, plain errors with the fix, "Before / Now" release notes.
- Bottom-sheet pickers on touch screens; bars are opaque or properly glassed (nothing showing through by accident).

## 5. Per surface
- **Phone app** (Android WebView shell): the studio as above; system bars, launch screen and app icon follow the
  theme; a light/dark key; app rows under the panel; 120 Hz.
- **Watch app** (Wear OS, Fossil Gen 6: 416×416 round, 32-bit, small battery): a light remote of the phone. The same
  table themes on **OLED black** — the table's accent and felt tone as rims, rings, tiles and the glass edge, not
  full-screen colour; static/baked glass; LED logo; big round touch targets; crown scrolling; Tiles and
  Complications first; ambient ≤15% lit pixels and ≤1 update/min; no polling; measured battery numbers for every
  change. Arcade touches stay small (a short haptic + a gold flash on a win), never long animations. The same theme
  options as the phone (all 21 tables + light/dark), synced from the phone.
- **TV**: the table is the hero; luxury art; static faux glass; synced; Fire TV budget (docs/TV_VIEW.md §6).
- **Website / GitHub**: the same table themes (Cyber grid dark default), glass capsule header, LED/pixel identity,
  calm but vibrant, fast scrolling.

## 6. How the owner wants work done
- Fix exactly what was asked; don't redesign other things on the way — ask first.
- Before/after screenshots in both themes at phone and desktop sizes; the owner checks real devices.
- Every change in its own PR with plain-words notes; never secrets in git; installers and updates via releases.

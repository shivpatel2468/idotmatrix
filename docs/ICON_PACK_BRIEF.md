# DeskDot icon pack — brief for the image generator

Inventory of every icon DeskDot 3.6.0 shows today (studio `web/src`, phone pages `casino.html` / `controller.html` /
`web/webapp/join`, TV view `tv.html` + `tv/*.js`, launcher `web/src/launcher`, web-app landing `web/webapp/host.js`,
Android `android/`, and the engine's app catalogue `src/deskdot/apps/*.py`). Use it to commission one custom pack that
replaces lucide-react. Each row lists one **canonical icon**. When one glyph serves several places, every usage is
listed under it. "Pressing it" describes the handler's real effect, read from the code.

Abbreviations: `api.x()` is a studio → engine REST call (`web/src/lib/api.ts`). "ws op X" is a phone → engine casino
message `{type:"casino", op:X}`. "send(k)" is a controller key `{k}` over the phone WebSocket.

---

## 1. Style spec (give this to the generator verbatim)

- **One family.** Every glyph looks like it was drawn by the same hand: same stroke, same corner radius, same level of
  detail, same optical size. Friendly-technical, like a premium hardware instrument panel (the product is a 32×32 RGB
  LED panel studio). Geometric, slightly rounded, no skeuomorphism, no perspective unless a prompt asks for it.
- **Format.** SVG, `viewBox="0 0 24 24"`. 2 px safe padding: live art stays inside 2…22. Stroke **1.75 px at 24 px**
  (1.5 px minimum, 2 px maximum). `stroke-linecap="round"`, `stroke-linejoin="round"`, `fill="none"` on the stroke
  layer. No transforms, masks, filters, gradients, embedded raster or `<text>`.
- **Duotone-capable.** Every icon has two layers as separate `<path>`/`<g>` groups:
  1. `class="i-1"` is the **primary stroke layer**, `stroke="currentColor"`. It must read on its own (outline style).
  2. `class="i-2"` is the **secondary fill layer**: closed shapes behind the strokes, `fill="var(--icon-2, currentColor)"`
     and `fill-opacity` left to CSS (today's duo look is about 20 %). Fill only the meaningful masses (a screen, a
     card face, a bell body), never the whole bounding box.
- **Legibility.** Must read at **16 px** (no detail finer than 2 px apart, at most about 3 interior features) and look
  **beautiful at 48 px** (balanced negative space, considered curves). Test on `#0b0b0f` (dark theme) and `#f6f1e7`
  (ivory light theme). No colour is baked in, so CSS tints it per category.
- **No text inside icons.** No letters or numerals, with the explicit exceptions marked *glyph* below (A/B buttons, the
  "D" dealer button, chip denominations). Those are drawn shapes of a single character in the family's own geometric
  letterform, not font text.
- **No brand logos or trade dress.** Generic glyphs only. No Pokéball, Tetris tetromino set/colours, Minecraft
  blocks/creeper/steve, Pac-Man/ghost silhouettes copied from Namco, Space Invaders crab, Chrome dino, Flappy Bird,
  Tron cycle, Connect Four rack, Nyan Cat, F1 logo, FIFA/EA card shape, PlayStation ✕○□△ colours, Xbox/Nintendo marks,
  Bitcoin orange coin, GitHub Octocat, Home Assistant house logo, OBS ring, Plex chevron, Anki star, Claude/Anthropic
  marks, Chess.com pawn, Binance diamond, Spotify waves. Rows that are risky carry the note **(generic!)**.
- **Naming.** `kebab-case.svg`, exactly the `id` in the tables (e.g. `skip-forward.svg`, `app-casino-roulette.svg`).
  Variants add a suffix: `-filled` (active), `-off` (negated state).
- **Grid and keylines.** Circle 20 px diameter, square 18×18, portrait rect 16×20, landscape rect 20×16. Chevrons and
  arrows sit on the same 2 px inset. Pixel/LED-themed subjects use rounded dots on a 4 px pitch so they still read
  as "LED".
- **Filled "active" variant (`-filled`).** Solid silhouette, same outline footprint, negative-space details cut out.
  Required for:
  - the tab bar (`tab-panel`, `tab-apps`, `tab-presets`, `tab-settings`); today the active tab switches to duo + a
    heavier stroke;
  - toggles and pressed states (`favourite`, `shuffle`, `fly-roam`, `sound-on` / `sound-off`, `play`, `stop`,
    `panel-power`, `theme-*`, `view-grid` / `view-list`, `visibility`, `ready`, `chip` selected, `controller-mode-*`
    selected, `casino-preset-*` selected);
  - **every app, category and preset icon**, because `IconTile solid` fills the tile when the app/preset is playing or
    selected.
- **Rotation-safe set.** `chevron-*`, `arrow-*`, `dpad-arrow` and `swipe-arrow` are rotated in code. Draw one canonical
  direction (pointing right for chevrons and arrows, up for the d-pad arrow) and keep it optically centred.

Delivery: one folder of SVGs plus a sprite (`icons.svg` with `<symbol id="…">`) plus a 16/24/48 px contact sheet on
dark and ivory.

---

## 2. Canonical icon table

Columns: **id** · **what it means / what pressing it does (precise)** · **where it appears (file → label)** ·
**current glyph** (lucide name, or `svg:`/`css:`/`char:` for hand-made ones) · **drawing prompt** · **variants needed**.

Paths are abbreviated, and all are under `web/src/` unless noted:

| Abbreviation | Path |
|---|---|
| `C/` | `web/src/components/` |
| `L/` | `web/src/launcher/` |
| `casino.html` | `src/deskdot/casino.html` |
| `controller.html` | `src/deskdot/controller.html` |
| `tv.*` | `src/deskdot/tv.html`, `tv/*.js` |

### 2.1 Navigation & tab bar

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| tab-panel | Phone tab "Panel": switches to the live panel view (tapping it again scrolls to top). Also the palette "Take the panel back", which calls `api.takeBack()` so the studio drives a panel that was running on its own. | `App.tsx` TabBar → "Panel"; `C/Overlays.tsx` palette → "Take the panel back" | monitor-play | A small square display on a short stand with a tiny play triangle in the screen. | outline, duo, -filled |
| tab-apps | Phone tab "Apps": opens the app library. Also the launcher row "Open DeskDot Studio" (opens the studio in the browser) and the Inspector empty state "Pick an app to see its settings" (decorative). | `App.tsx` → "Apps"; `L/Launcher.tsx` → open-studio; `C/Inspector.tsx` empty medallion | layout-grid | A 2×2 grid of rounded squares with even gaps. | outline, duo, -filled |
| tab-presets | Phone tab "Presets": opens the presets/playback page. It is also the default preset icon and the playlist concept everywhere:<br>• Settings section "Playlist & hand-off" and block "Your presets"<br>• fallback icon of any preset without an icon, including every user preset<br>• palette "Play <preset>" (`api.playPreset`)<br>• launcher "Play/Stop the playlist" (`api.playlist(play\|stop)`) and preset rows (`api.playPreset`) | `App.tsx` → "Presets"; `C/Settings.tsx` SECTIONS/Block; `C/PlaylistDock.tsx`, `C/Overlays.tsx`, `C/Settings.tsx` preset rows; `L/Launcher.tsx` | list-music | Three horizontal list lines with a small music note at the lower right. | outline, duo, -filled |
| tab-settings | Phone tab "Settings": opens settings. The same "tune" glyph also opens:<br>• the current app's settings (Stage "Settings" → `inspect(app)`)<br>• the Play-mode phone "Match" sheet (mode, setup, restart, fruit fly)<br>• Colour calibration "Advanced" (every knob)<br>• calibration wizard "Fine-tune" (opens Advanced pre-filled) | `App.tsx` → "Settings"; `C/Stage.tsx` → "Settings"; `C/PlayMode.tsx` → "Match"; `C/calibration/ColourCalibration.tsx` tile "Advanced"; `C/calibration/CalWizard.tsx` → "Fine-tune" | sliders-horizontal | Three horizontal slider tracks, each with a round knob at a different position. | outline, duo, -filled |
| chevron-right | Disclosure and forward. Uses:<br>• "See all <category>" on an app rail: sets the library category and switches to Apps<br>• Display menu "More" (rotates 90° when open) and row arrows that open a settings block<br>• Play-mode "Next game" (`switchGame(+1)`, key `]`)<br>• Match-setup "Move right" (sends `right` to pick a side)<br>• launcher "Brighter" (+10 %)<br>• phones' MiniPlayback row (opens Presets tab) | `C/AppRail.tsx`, `C/DisplayMenu.tsx`, `C/PlayMode.tsx`, `C/MatchSetup.tsx`, `C/Stage.tsx` MiniPlayback, `L/Launcher.tsx` | chevron-right | A single open chevron pointing right, 90° angle, round ends. | outline (rotated in code) |
| chevron-left | Back and previous. Uses:<br>• calibration "‹ Colour" / "‹ Motion" back buttons (leave sub-view, clear test pattern)<br>• Play-mode "Previous game" (key `[`)<br>• Match-setup "Move left"<br>• launcher "Dimmer" (−10 %) | `C/calibration/ColourCalibration.tsx`, `C/calibration/MotionLab.tsx`, `C/PlayMode.tsx`, `C/MatchSetup.tsx`, `L/Launcher.tsx` | chevron-left | Mirror of chevron-right. | outline |
| chevron-down | Opens a dropdown or expander (rotates 180° when open). Uses:<br>• Picker field caret<br>• Create menu<br>• Play-mode game list<br>• Match setup collapse<br>• casino seat row (credits/top-up/kick)<br>• casino round history row (proof details)<br>• dock "Edit playlist" (collapsed)<br>• phone playlist "Move down" (reorders item i → i+1) | `C/Picker.tsx`, `C/Stage.tsx`, `C/PlayMode.tsx`, `C/MatchSetup.tsx`, `C/casino/RightWing.tsx`, `C/PlaylistDock.tsx` | chevron-down | Open chevron pointing down. | outline |
| chevron-up | Dock "Edit playlist" when open (hides the editor) and phone playlist "Move up" (item i → i−1). | `C/PlaylistDock.tsx` | chevron-up | Open chevron pointing up. | outline |
| close | Close or dismiss:<br>• Modal/Sheet "Close (Esc)", Controls panel, AI creator, Fly settings<br>• Play mode "Leave Play mode (Esc)"<br>• clear search box<br>• remove playlist item<br>• remove autopilot rule<br>• delete preset badge (opens confirm)<br>• "Clear search" in Settings<br>• dismiss panel message (`api.dismiss()`)<br>• stop On Air preview (`api.onairSimulate(0)`)<br>• clear status indicator (`api.clearIndicator`)<br>• remove custom app (`api.removeCustom`)<br>• Radar "Clear selection" (`api.action(radar, clear)`; also the radar app action)<br>• TV sheet "Stop TV link" (closes the link, disconnects every screen)<br>• Multiplayer "Cancel" (closes the room, disconnects phones)<br>• Casino "Close the room" (wallets kept)<br>• preset-name form "Cancel"<br>• web-app pill "Hide" (collapses the pill to its LED) | `C/Sheet.tsx`, `C/Overlays.tsx` Modal, `C/PlayMode.tsx`, `C/Library.tsx`, `C/PlaylistDock.tsx`, `C/AutopilotEditor.tsx`, `C/Settings.tsx`, `C/Stage.tsx`, `C/PlatformStrip.tsx`, `C/TvSheet.tsx`, `C/Multiplayer.tsx`, `C/casino/CasinoStage.tsx`, `C/ControlsPanel.tsx`, `C/AiCreator.tsx`, `C/fly/FlyView.tsx`, `web/webapp/host.js` (char ×) | x | Two crossing diagonal strokes forming an X. | outline |
| return-key | Hint that Enter runs the highlighted command (palette); in the launcher footer, the label is the verb Enter will run. | `C/Overlays.tsx` palette row; `L/Launcher.tsx` footer | corner-down-left | A line coming down then turning left into a small arrowhead, like a return key. | outline |
| more | Phone header "Quick controls": opens the sheet with brightness, panel power, theme, fruit fly, Find/Message/Settings/App-icon tiles. An ember dot appears when the fly is playing. | `C/TopBar.tsx` PhoneTopBar | ellipsis | Three evenly spaced dots in a horizontal row. | outline |
| expand-mini | Phone "Now showing" strip: back to the Panel tab. | `App.tsx` MiniPreview | maximize-2 | Two small diagonal arrows pointing to opposite corners. | outline (shares art with `fullscreen`) |

### 2.2 Top bar

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| search | Find. Uses:<br>• top-bar "Find anything (Ctrl K)" / search key: opens the command palette<br>• Quick-controls tile "Find"<br>• search field prefix in Library, Settings, Picker, add-app list, palette<br>• Settings "Find nearby panels" (`api.scan()`)<br>• Connection "Pick panel" / "Pick another panel" (Web Bluetooth chooser)<br>• Library empty state "nothing matches" | `C/TopBar.tsx`, `C/Overlays.tsx`, `C/Library.tsx`, `C/Settings.tsx`, `C/Picker.tsx`, `C/PlaylistDock.tsx`, `C/ConnectionSheet.tsx`, `L/Launcher.tsx` header | search | A magnifying glass: a circle with a short handle to the lower right. | outline, duo |
| brightness | Panel brightness. Uses:<br>• top-bar slider label and phone brightness key (opens a slider popover; slider calls `api.settings({brightness})`)<br>• Quick-controls slider<br>• palette "Brightness 100%"<br>• Settings block "Display"<br>• calibration wizard hint "Set the brightness you normally use"<br>• launcher brightness rows (←/→ ±5)<br>• Composer effect "Glow" | `C/TopBar.tsx`, `C/Overlays.tsx`, `C/Settings.tsx`, `C/calibration/CalWizard.tsx`, `C/ComposerEditor.tsx`, `L/Launcher.tsx` | sun | A small circle with eight short rays. | outline, duo |
| brightness-low | Palette "Brightness 30%": `api.settings({brightness:30})`. | `C/Overlays.tsx` | sun-dim | A small circle with eight dot-length rays. | outline, duo |
| panel-power | Panel display power (the Bluetooth link stays up). Uses:<br>• Safety switch red button: after lifting the guard, `api.settings({power:false})`<br>• "Panel off · turn on" (power on)<br>• palette "Turn the display off/on"<br>• launcher "Turn the panel off/on" | `C/SafetySwitch.tsx`, `C/Overlays.tsx`, `L/Launcher.tsx` | power | A circle open at the top with a vertical stroke through the gap. | outline, -filled (on), -off |
| casino-open | Top-bar gold "Casino": `openCasino()` puts the last casino table on the panel and opens the casino view. | `C/TopBar.tsx` → "Casino" | dices | Two dice at an angle, one overlapping the other, pips as dots. | outline, duo (see also `cat-casino`) |
| message | "Send a message". Uses:<br>• Quick-controls tile "Message" and Create menu item: opens the notify dialog<br>• palette "Computer notifications on the panel" (settings)<br>• Settings section "Notifications & integrations" and block "Computer notifications" | `C/TopBar.tsx`, `C/Stage.tsx` CreateMenu, `C/Overlays.tsx`, `C/Settings.tsx` | bell-ring | A bell with two small vibration arcs on each side. | outline, duo |
| bell | Palette "Send a message to the panel…" (opens notify dialog). Launcher "Dismiss notification" (`api.dismiss()`). | `C/Overlays.tsx`, `L/Launcher.tsx` | bell | A plain bell with a clapper dot. | outline, duo |
| settings | Settings and gear. Uses:<br>• Quick-controls tile "Settings" (opens Settings at Display)<br>• palette "Settings"<br>• Display menu trigger "Display & settings" and "All settings"<br>• launcher "<Section> settings" rows (13 sections, open studio at that tab)<br>• Fly view "Graphics" (toggles the fly settings drawer) | `C/TopBar.tsx`, `C/Overlays.tsx`, `C/DisplayMenu.tsx`, `C/fly/FlyView.tsx`, `L/Launcher.tsx` | settings-2 | A gear with six rounded teeth and a hollow centre. | outline, duo |
| send | Send. Uses:<br>• notify dialog "Send to the panel" (`api.notify`)<br>• Settings "Send a test" (test notification)<br>• launcher "Send 'text' to the panel" (`api.notify`)<br>• launcher "Show 'text' for 30 s" (`api.text`) | `C/Overlays.tsx`, `C/Settings.tsx`, `L/Launcher.tsx` | send | A paper plane pointing to the upper right. | outline, duo |

### 2.3 Playback & playlist

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| play | Start or show. Uses:<br>• transport "Play playlist" (`api.playlist("play")`) and palette "Resume playlist"<br>• preset card play (`api.playPreset`)<br>• Settings preset "Play"<br>• library tile/row "Show on the panel now" and Inspector "Show on panel" (`api.activate(id)`)<br>• Settings sound "Play it" (plays one effect)<br>• CalWizard "Start"<br>• Integrations "Try it now" (eye break now)<br>• AI creator preview play<br>• Match setup "Start" (`start` action)<br>• Multiplayer "Start now" (`api.startLobby`)<br>• Casino "Start round/Next round" (`casinoOp("start_round")`) and "Resume"<br>• app actions Now Playing "Play/Pause" (media toggle) and Focus Timer "Start/Pause"<br>• default for any app action without an icon | `C/NowPlaying.tsx`, `C/PlaylistDock.tsx`, `C/Overlays.tsx`, `C/Settings.tsx`, `C/Library.tsx`, `C/Inspector.tsx`, `C/calibration/CalWizard.tsx`, `C/IntegrationsTab.tsx`, `C/AiCreator.tsx`, `C/MatchSetup.tsx`, `C/Multiplayer.tsx`, `C/casino/CasinoStage.tsx`, engine actions | play | A rounded right-pointing triangle, optically centred. | outline, -filled (used filled in transport) |
| pause | Casino "Pause" (freezes every timer, `casinoOp("pause")`). AI creator preview pause. | `C/casino/CasinoStage.tsx`, `C/AiCreator.tsx` | pause | Two vertical rounded bars. | outline, -filled |
| stop | Transport "Stop playlist" (keeps showing the current app). Preset card stop. Palette "Stop playlist". | `C/NowPlaying.tsx`, `C/PlaylistDock.tsx`, `C/Overlays.tsx` | square (filled) | A rounded square. | outline, -filled |
| skip-back | Previous. Uses:<br>• transport "Previous app (←)" (`api.playlist("prev")`)<br>• launcher "Previous"<br>• AI creator "Previous frame"<br>• Now Playing app action "Previous" (media prev track) | `C/NowPlaying.tsx`, `C/PlaylistDock.tsx`, `C/AiCreator.tsx`, `L/Launcher.tsx`, app action `nowplaying.prev` | skip-back | A left-pointing triangle against a vertical bar. | outline, -filled |
| skip-forward | Next. Uses:<br>• transport "Next app (→)"<br>• palette "Next app"<br>• launcher "Next"<br>• AI creator "Next frame"<br>• app actions "Next story/aircraft/screen/photo/game/question/quote" and Now Playing "Next"<br>• Focus Timer "Skip" (next pomodoro phase) | `C/NowPlaying.tsx`, `C/PlaylistDock.tsx`, `C/Overlays.tsx`, `C/AiCreator.tsx`, `L/Launcher.tsx`; actions headlines/radar/space/nowplaying/photoframe/gamedeals/trivia/daily/timer | skip-forward | A right-pointing triangle against a vertical bar. | outline, -filled |
| shuffle | Shuffle presets on/off (`prefs({shuffle})`; presets then play in random order). Palette "Shuffle presets on/off". App actions Pokédex "Another one" and Chess "Next puzzle" (random). | `C/NowPlaying.tsx`, `C/PlaylistDock.tsx`, `C/Overlays.tsx`; actions pokedex.next, chess.next | shuffle | Two crossing arrows heading right. | outline, -filled (on) |
| fullscreen | Dock "Full screen" (opens the Now Playing full view). Fly view "Full screen" (brain + panel + keyboard), wing "Full screen", "Brain/Both/Keyboard" full-screen buttons. Fly wing placeholder "Showing full screen". | `C/PlaylistDock.tsx`, `C/fly/FlyView.tsx` | maximize-2 | Two diagonal arrows pointing out to opposite corners. | outline |
| exit-fullscreen | Now Playing "Exit full screen (Esc)". Fly view "Exit" / "Back here". | `C/NowPlaying.tsx`, `C/fly/FlyView.tsx` | minimize-2 | Two diagonal arrows pointing in towards the centre. | outline |
| playlist-add | Inspector "Playlist": adds the inspected app to the end of the playlist. | `C/Inspector.tsx` | list-plus | Three list lines with a small plus at the lower right. | outline, duo |
| add | Add. Uses:<br>• "Add app" (opens app finder to append to the playlist)<br>• Create menu trigger "Create"<br>• Composer "Add text" (new text layer)<br>• Autopilot "Rule" (new rule) | `C/PlaylistDock.tsx`, `C/Stage.tsx`, `C/ComposerEditor.tsx`, `C/AutopilotEditor.tsx` | plus | A plus sign with equal arms. | outline |
| save-preset | "Save as preset": opens the name field to save the current playlist as your own preset. | `C/PlaylistDock.tsx` | save | A floppy disk silhouette with a label slot. **(generic, fine)** | outline, duo |
| delete | Delete. Uses:<br>• preset "Delete" (`api.deletePreset`)<br>• Settings preset delete (opens confirm)<br>• canvas "Clear" (`api.action(canvas, clear)`)<br>• Composer "Delete (Del)" layer<br>• media library "Delete" image (`api.deleteMedia`) | `C/PlaylistDock.tsx`, `C/Settings.tsx`, `C/Stage.tsx`, `C/ComposerEditor.tsx`, `C/SchemaForm.tsx` | trash-2 | A lidded bin with two vertical slots. | outline, duo |
| reorder-grip | Phone playlist row drag handle (visual; reordering is by the up/down keys). | `C/PlaylistDock.tsx` | grip-vertical | Two columns of three small dots. | outline |
| item-include | Playlist row switch "Included — tap to skip it". | `C/PlaylistDock.tsx` | css: toggle | Keep as CSS toggle (no icon needed). | — |
| native-loop | MotionLab "Play as native loop": bakes test A as a GIF and lets the panel play it by itself. | `C/calibration/MotionLab.tsx` | repeat | Two arrows chasing each other around a rounded rectangle loop. | outline |

### 2.4 Library & app actions

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| favourite | Star or unstar an app (adds or removes it in Favourites; aria-pressed). Favourites rail header, "Favourites" library section header, empty favourites state. Text "★ Favourites" chip. | `C/Library.tsx`, `C/AppRail.tsx` rail "Favourites" | star | A five-point star with softly rounded points. | outline, -filled (on) |
| recent | App-rail section "Recent" (recently shown apps). | `C/AppRail.tsx` | rotate-ccw-clock | A clock face with a counter-clockwise arrow around its rim. | outline, duo |
| view-grid | Library "Grid view / Big previews" (`prefs({libraryView:"grid"})`). Preview-size slider label. Launcher "Display menu (Tab)" grid view. | `C/Library.tsx`, `L/Launcher.tsx` | layout-grid | 2×2 rounded squares, slightly tighter than `tab-apps` (can share art). | outline, -filled (active) |
| view-list | Library "List view / Compact list". Launcher "Results (Tab)" list view. | `C/Library.tsx`, `L/Launcher.tsx` | list | Three horizontal lines, each with a leading dot. | outline, -filled (active) |
| restart | Restart. Uses:<br>• app action "Restart" (22 games + Chess: restarts the current game/puzzle)<br>• Play mode "Restart (R)"<br>• Match results "Rematch" (sends A: play again, same sides)<br>• CalWizard "Redo step" | `C/PlayMode.tsx`, `C/MatchSetup.tsx`, `C/calibration/CalWizard.tsx`, engine actions | rotate-ccw | A counter-clockwise circular arrow, open at the top. | outline |
| reset | Back to defaults. Uses:<br>• Inspector "Defaults" (puts every app setting back)<br>• Display menu "Reset to default"<br>• "Reset to panel native" calibration<br>• CalAdvanced "Factory" and per-knob reset<br>• Fly settings "Reset every Fly view setting" and "Reset brain"<br>• Trivia "Reset score"<br>• Focus Timer "Reset" | `C/Inspector.tsx`, `C/DisplayMenu.tsx`, `C/calibration/*`, `C/fly/FlyView.tsx`, actions trivia.reset_score, timer.reset | rotate-ccw | A counter-clockwise arrow around a small dot, to tell it apart from `restart`. | outline |
| undo | Undo. Uses:<br>• CalAdvanced "Revert" (back to saved)<br>• Habits "Undo last" (reverts last tick)<br>• casino "Undo" (takes back your last chip bet this round: `unbet` of that one chip, which flies back to the rack; studio and phone) | `C/calibration/CalAdvanced.tsx`, `C/casino/RightWing.tsx`, `casino.html #undo` (svg), action habits.undo | undo-2 / svg curved arrow | A U-turn arrow curving back to the left. | outline |
| autoplay-ai | Hand the game to the AI. Uses:<br>• app action "Autoplay" (22 games: attract/demo mode)<br>• Play mode "Let AI play"<br>• vs-AI segment<br>• AI seat chip and "AI fills N seats" note<br>• palette "Claude: thinking" (`POST /api/agent/thinking`) | `C/PlayMode.tsx`, `C/Multiplayer.tsx`, `C/MatchSetup.tsx`, `C/Overlays.tsx`, actions *.demo | bot | A friendly robot head with an antenna and two round eyes. | outline, duo |
| reveal | Show. Uses:<br>• Chess "Show solution"<br>• Trivia "Reveal" (answer)<br>• Integrations "Preview 8 s" (On Air sign)<br>• CalPresets "Try"<br>• calibration hint "Sit where you usually do"<br>• Composer effect "Blink"<br>• casino "Show QR" (puts join QR back on the panel) | actions chess.solve, trivia.reveal; `C/IntegrationsTab.tsx`, `C/calibration/*`, `C/ComposerEditor.tsx`, `C/casino/CasinoStage.tsx` | eye | An almond eye with a round pupil. | outline, duo |
| visibility | Composer layer "Hide/Show" toggle. Casino "Hide QR" (shows the table instead; phones still join with the code). | `C/ComposerEditor.tsx`, `C/casino/CasinoStage.tsx` | eye / eye-off | An eye; the off variant has a diagonal slash. | outline, -off |
| sparkle-toggle | Pokédex "Toggle shiny" (colour variant on/off). | action pokedex.shiny | sparkles | Two four-point sparkles, one large and one small. | outline, -filled (on) |
| step | Chess "Step": manual move stepping with arrows/A/B. | action chess.input | gamepad-2 | Same art as `gamepad`. | outline |
| refresh | Reload or regenerate (not the panel link). Uses:<br>• Game Deals "Refresh" (re-fetch)<br>• TV sheet "New code" (new TV link code; old screens disconnect)<br>• Fly "Check again" / "Retry" (engine reachability) | action gamedeals.refresh; `C/TvSheet.tsx`, `C/fly/FlyView.tsx` | refresh-cw | Two curved arrows chasing clockwise in a circle. | outline |
| eraser | Canvas tool "Eraser (E)". Canvas app action "Clear" (clears painting to black). | `C/Stage.tsx` CanvasTools; action canvas.clear | eraser | A tilted rectangular eraser with a band, over a short baseline. | outline, duo, -filled (active tool) |
| tick | Habits "Tick 1/2/3" (marks habit done for today). | actions habits.tick1–3 | check | A check mark. | outline (shares `check`) |
| radar-next | Flight Radar card "Next": selects the next aircraft (`api.action(radar,next)`). | `C/Stage.tsx` RadarCard | crosshair | A circle with four short tick marks crossing at the centre. | outline |
| magnify | Magnify bar label (zoom slider for apps that support zoom). | `C/Stage.tsx` MagnifyBar | zoom-in | A magnifier with a plus inside the lens. | outline |
| create-ai | Make with AI. Uses:<br>• Create "Make with AI"<br>• palette "Make pixel art with AI…"<br>• canvas "Draw with AI" (opens AI creator)<br>• AI creator header, Generate button, empty state<br>• SchemaForm group "Graphics" | `C/Stage.tsx`, `C/Overlays.tsx`, `C/AiCreator.tsx`, `C/SchemaForm.tsx` | sparkles | Three four-point sparkles of different sizes. | outline, duo |
| image-upload | Create "Show a picture or GIF": opens a file picker, uploads, shows it in Gallery. | `C/Stage.tsx` CreateMenu | image-up | A landscape picture frame with an up arrow in the corner. | outline, duo |
| image-add | Media picker "Upload": adds an image to the library for an app field. | `C/SchemaForm.tsx` | image-plus | A picture frame with a small plus in the corner. | outline, duo |
| draw | Create "Draw on the panel" (`api.activate("canvas")`). Palette "Draw on the panel". Canvas tool "Brush (B)". | `C/Stage.tsx`, `C/Overlays.tsx` | paintbrush | A round paintbrush tilted 45° with a dab of paint at the tip. | outline, duo, -filled (active tool) |
| fill-bucket | Canvas tool "Fill (F)". | `C/Stage.tsx` | paint-bucket | A tipped paint bucket pouring a drop. | outline, duo, -filled |
| eyedropper | Canvas tool "Pick colour (I)". | `C/Stage.tsx` | pipette | A diagonal eyedropper with a bulb at the top. | outline, duo, -filled |
| write-text | Create "Write text" (`api.activate("composer")`). Composer layer kind "Text". | `C/Stage.tsx`, `C/ComposerEditor.tsx` | type | A capital-T shape built from strokes (allowed: it is a type tool, not text). | outline |
| show-on-tv | Show on TV. Uses:<br>• Create "Show on TV" (opens TV sheet)<br>• palette "Show on TV…"<br>• casino "TV" key<br>• TV sheet loading state<br>• CalPresets group "Display-inspired" | `C/Stage.tsx`, `C/Overlays.tsx`, `C/casino/CasinoStage.tsx`, `C/TvSheet.tsx`, `C/calibration/CalPresets.tsx` | tv | A widescreen TV with two small antenna strokes. | outline, duo |
| duplicate | Composer "Duplicate" layer. Copy address (TV link, lobby URL, casino round hash). | `C/ComposerEditor.tsx`, `C/TvSheet.tsx`, `C/Multiplayer.tsx`, `C/casino/CasinoStage.tsx` | copy | Two overlapping rounded rectangles. | outline, duo |
| ai-key | AI creator "Gemini API" key status. | `C/AiCreator.tsx` | key | A key with a round bow. | outline, duo |
| send-to-panel | AI creator "Send to Panel": uploads the animation as a native baked loop. Settings block "Smooth motion" and palette "Fix tearing / flicker". MotionLab "Measure & suggest" (streams a test, measures the link). AI model "Gemini 2.5 Flash". | `C/AiCreator.tsx`, `C/Settings.tsx`, `C/Overlays.tsx`, `C/calibration/MotionLab.tsx` | zap | A lightning bolt. | outline, duo |
| edit-in-canvas | AI creator "Edit in Canvas": loads the current frame into the pixel painter. | `C/AiCreator.tsx` | brush | A flat brush with a paint drop. | outline |
| export | AI creator "Export GIF" (download). | `C/AiCreator.tsx` | download | A down arrow onto a tray. | outline |
| in-gallery | AI creator "In Gallery": saves to Gallery and shows it. | `C/AiCreator.tsx` | layers | Three stacked rhombus layers. | outline, duo |
| autopilot | Autopilot editor header. Settings block "Follow the app I'm using". Palette "Follow the app I'm using (autopilot)". | `C/AutopilotEditor.tsx`, `C/Settings.tsx`, `C/Overlays.tsx` | wand-2 / wand-sparkles | A magic wand with three small sparkles. | outline, duo |
| group-game / group-flow | SchemaForm group headers "Game" (gamepad) and "Game flow". | `C/SchemaForm.tsx` | gamepad-2 / workflow | Game: see `gamepad`. Flow: three boxes linked by an elbow connector. | outline |
| layer-kind-* | Composer layer kinds:<br>• `time` clock (clock-3)<br>• `seconds` stopwatch (timer)<br>• `date` calendar with days (calendar-days)<br>• `month` calendar (calendar)<br>• `day` calendar with check (calendar-check)<br>• `weather` thermometer<br>• `cpu` chip (cpu)<br>• `ram` memory stick<br>• `price` coin (bitcoin) | `C/ComposerEditor.tsx` KIND_ICON (Picker options) | clock-3, timer, calendar-days, calendar, calendar-check, thermometer, cpu, memory-stick, bitcoin | 9 small glyphs: a clock face; a stopwatch; a calendar with a dot grid; a plain calendar; a calendar with a tick; a bulb thermometer; a square chip with pins; a RAM stick with contacts; a generic coin with a currency stroke **(generic! no ₿ logo)**. | outline, duo |
| effect-* | Composer text effects:<br>• `solid` circle<br>• `rainbow` arcs<br>• `gradient` overlapping circles (blend)<br>• `pulse` heartbeat line (activity)<br>• `blink` eye (reveal)<br>• `glow` sun (brightness)<br>• `scroll` horizontal double arrow (move-horizontal) | `C/ComposerEditor.tsx` EFFECT_ICON | circle, rainbow, blend, activity, eye, sun, move-horizontal | 5 new glyphs: a filled dot; three nested arcs; two overlapping translucent circles; a left-right double arrow; (pulse = `cat-data`, blink = `reveal`, glow = `brightness`). | outline, duo |
| ai-model-* | AI model picker: Flash (zap), 1.5 Flash (sparkle), Pro "Deep" (brain). | `C/AiCreator.tsx` | zap, sparkle, brain | Sparkle: one four-point star. Brain: a brain outline with a centre fold. | outline, duo |

### 2.5 Settings sections

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| section-display | Settings section "Display & colour" (theme, brightness, night mode, sounds, colours, smooth motion). Palette "Night mode & display". Display menu trigger "Display: <look>" (opens look popover). Launcher "Now showing" row (opens studio). | `C/Settings.tsx` SECTIONS, `C/Overlays.tsx`, `C/DisplayMenu.tsx`, `L/Launcher.tsx` | monitor | A desktop monitor on a short foot. | outline, duo, -filled (selected nav) |
| section-alerts | "Notifications & integrations". | `C/Settings.tsx` | bell-ring | = `message`. | -filled |
| section-playlist | "Playlist & hand-off". | `C/Settings.tsx` | list-music | = `tab-presets`. | -filled |
| section-device | "Device" section. Block "Connection". Palette "Device & connection" (opens panel settings). | `C/Settings.tsx`, `C/Overlays.tsx` | bluetooth | = `bluetooth`. | -filled |
| block-sound | Settings block "Sound" (UI sound effects). "Test" plays one effect per enabled category. | `C/Settings.tsx` | volume-2 | A speaker with two sound-wave arcs. | outline, duo |
| block-theme | Settings block "Studio theme". | `C/Settings.tsx` | sun-moon | A circle split half sun (rays) and half crescent moon. | outline, duo |
| block-appicon | Settings block "App icon" (Android only). Quick-controls tile "App icon" (opens it). Integrations "Phone pushes (ntfy)". Casino lobby "Friends join from their phones". Controls "On-screen touch controls". | `C/Settings.tsx`, `C/TopBar.tsx`, `C/IntegrationsTab.tsx`, `C/casino/CasinoStage.tsx`, `C/ControlsPanel.tsx` | smartphone | A portrait phone with a speaker slot. | outline, duo |
| block-intro | Settings block "Intro & outro" (boot show). | `C/Settings.tsx` | clapperboard | A film clapperboard with striped top arm. | outline, duo |
| block-calibrate | Settings block "Colour calibration". Palette "Calibrate panel colours…". Calibration tile "Presets". | `C/Settings.tsx`, `C/Overlays.tsx`, `C/calibration/ColourCalibration.tsx` | palette | A painter's palette with three paint dots and a thumb hole. | outline, duo |
| block-transitions | Settings block "App transitions". | `C/Settings.tsx` | move-right | A right arrow with a short tail bar. | outline |
| block-handoff | "Keep showing when my computer is off". "Let the panel run on its own now" (`api.handoffNow()`; the panel keeps running, the computer can sleep). Palette handoff entries. | `C/Settings.tsx`, `C/Overlays.tsx` | laptop-minimal | An open laptop seen from the front. | outline, duo |
| block-location | "Location & units". Palette "Location & units". | `C/Settings.tsx`, `C/Overlays.tsx` | map-pin | A map pin with a hollow centre. | outline, duo |
| block-audio-input | "Sound input" (system audio / microphone for visualisers). Palette "Sound input". Also app Visualizer. | `C/Settings.tsx`, `C/Overlays.tsx` | audio-lines | Five vertical bars of varied height, like a level meter. | outline |
| block-sources | "Data sources" (health of live-data providers). | `C/Settings.tsx` | activity | = `cat-data` pulse line. | — |
| integration-onair | "On Air" section: a full-screen ON AIR sign while camera/mic is live. | `C/IntegrationsTab.tsx` | radio | A broadcast tower dot with two radiating arcs each side. | outline, duo |
| integration-eyebreak | "Eye break · 20-20-20" section. "Try it now" = play. | `C/IntegrationsTab.tsx`; PlatformStrip "eye break" chip | eye | = `reveal`. | — |
| integration-indicators | "Status indicators" (three corner LEDs set by scripts). | `C/IntegrationsTab.tsx` | square-dot | A rounded square with a dot in the centre. | outline, duo |
| integration-homeassistant | "Home Assistant" section; "Test connection". | `C/IntegrationsTab.tsx` | house | A simple house outline with a door **(generic! not the HA logo)**. | outline, duo |
| integrations | PlatformStrip "Integrations" (opens Settings → integrations). Palette "Integrations: On Air, eye break…". | `C/PlatformStrip.tsx`, `C/Overlays.tsx` | plug-zap | A plug with a lightning bolt. | outline, duo |
| plug | "Use the panel here" (`api.link(true)`: connect and keep reconnecting). Palette "Connect to the panel". HA "Test connection". | `C/Settings.tsx`, `C/Overlays.tsx`, `C/IntegrationsTab.tsx` | plug | A two-prong plug with a cord. | outline, duo |
| unplug | "Release the panel…" (asks to confirm; then DeskDot disconnects and stops reconnecting, and the panel shows its pairing screen). Palette "Disconnect from the panel". | `C/Settings.tsx`, `C/ConnectionSheet.tsx`, `C/Overlays.tsx` | unplug | A plug pulled apart from its socket with a gap. | outline |
| webhook | Custom-app chip in the platform strip (screens pushed by scripts). App Custom. | `C/PlatformStrip.tsx` | webhook | Three nodes linked in a triangle by curved hooks. | outline |
| cal-guided | Calibration "Guided match" (A/B test videos converge on a match). MotionLab "Find my smoothest". | `C/calibration/ColourCalibration.tsx`, `C/calibration/MotionLab.tsx` | scan-eye | An eye inside four corner brackets. | outline, duo |
| cal-testbench | MotionLab "Test bench". | `C/calibration/MotionLab.tsx` | flask-conical | A conical lab flask with liquid. | outline, duo |
| cal-quiz | CalPresets "Answer 3 questions" (Claude quick match quiz). | `C/calibration/CalPresets.tsx` | message-circle-question | A round speech bubble with a question mark *glyph*. | outline, duo |
| cal-standard | CalPresets group "Standards". | `C/calibration/CalPresets.tsx` | ruler | A straight ruler with tick marks. | outline |
| cal-lamp | CalWizard tip "Avoid a lamp shining right onto the panel". | `C/calibration/CalWizard.tsx` | lamp | A table lamp with a cone shade. | outline, duo |

### 2.6 Display menu, TV sheet & media sharing

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| look-pixel / look-led / look-glow | Panel look on this screen. In the studio Display menu they are text segments today; on the TV remote menu (`.tvm-opt`) they are drawn as 3×3 swatches: hard squares, rounded LEDs on black, blurred glow. Picking applies it to this screen and remembers it. | `C/DisplayMenu.tsx` (text), `tv.*` TV menu (svg swatch) | svg swatches | Three 3×3 dot grids: square cells; round LEDs with gaps; round LEDs with a soft halo ring. | outline, duo |
| tv-link | TV sheet intro "Open this address in any browser…". | `C/TvSheet.tsx` | monitor-play | = `tab-panel`. | — |
| same-wifi | Note "The screen must be on the same Wi-Fi". Multiplayer note. TV sheet. | `C/TvSheet.tsx`, `C/Multiplayer.tsx` | wifi | Three nested arcs over a dot. | outline |
| share-screen | MediaPrompt "screen": start or stop sharing your screen for Screen Mirror (`DeskDotMedia.start("screen")`). | `C/MediaPrompt.tsx` | monitor-up | A monitor with an up arrow on the screen. | outline, duo |
| share-camera | MediaPrompt "camera": start the webcam for Camera Mirror. | `C/MediaPrompt.tsx` | camera | A compact camera with a round lens. | outline, duo |
| share-mic | MediaPrompt "audio": start listening for the visualiser; "Use microphone". | `C/MediaPrompt.tsx` | mic | A capsule microphone on a stand arc. | outline, duo |
| upload-drop | Drop zone "Drop to show on the panel" (drag a file anywhere). | `C/Overlays.tsx` DropZone | upload | An up arrow rising out of a tray. | outline |

### 2.7 Connection & device

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| bluetooth | Bluetooth link. Uses:<br>• Connection primary "Use the panel here" (`api.link(true)`)<br>• Settings "Reconnect" (`api.reconnect()`)<br>• Device section/block<br>• web-app landing "Connect panel" (opens Web Bluetooth chooser; text-only today) | `C/ConnectionSheet.tsx`, `C/Settings.tsx`, `web/webapp/host.js` (candidate) | bluetooth | The rune-like B: a vertical stroke with two closed angled loops. **(generic shape, no SIG logo badge)** | outline, -off |
| reconnect | Re-establish the panel link now. Uses:<br>• top-bar "Reconnect now" (`api.reconnect(true)`) and Quick controls<br>• Connection "Reconnect now" / "Reconnect" (drop the link and connect again; the panel blinks its pairing icon)<br>• launcher "Reconnect the panel" (wrongly Wifi today) | `C/TopBar.tsx`, `C/ConnectionSheet.tsx`, `L/Launcher.tsx` | refresh-cw (launcher: wifi) | A circular arrow wrapped around a small Bluetooth B. | outline |
| this-computer | Connection: "DeskDot on this computer, over Bluetooth" / "A simulated panel". "Is DeskDot open on this computer?" (probes desktop). Desktop-holding note. | `C/ConnectionSheet.tsx` | laptop | = `block-handoff` laptop. | — |
| this-browser | Connection: "This browser tab, over Web Bluetooth" / "The DeskDot Android app". | `C/ConnectionSheet.tsx` | monitor-smartphone | A monitor with a phone standing in front of it. | outline, duo |
| link-state | Panel connection LED in the top bar, phone header, quick controls, TV bar, launcher, web-app pill, phones' `#netdot`:<br>• ok = connected<br>• warn = connecting/scanning/reconnecting<br>• bad = off/busy/Bluetooth off/engine offline | `C/TopBar.tsx`, `tv.*`, `L/Launcher.tsx`, `web/webapp/host.js`, `casino.html`, `controller.html`, `web/webapp/join` | css: LED dot | Keep as CSS LED. Optional icon set: a dot inside a ring for ok, a half ring for warn, a ring with a slash for bad. | -ok, -warn, -bad (optional) |
| net-latency | Controller top bar "online / {ms} ms / connecting / offline" with a coloured dot: green below 60 ms, amber below 120 ms, red otherwise. | `controller.html .net` | css dot + text | Optional: three ascending signal bars. | -good, -fair, -poor, -off |
| bluetooth-off | Connection problem "Bluetooth is off". | `C/ConnectionSheet.tsx` (text + LED) | (none) | Bluetooth B with a diagonal slash. | candidate |

### 2.8 Phone controller (controller.html, studio TouchControls / ControlsPanel / MatchSetup)

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| dpad-arrow | D-pad arm Up/Down/Left/Right: sends `up/down/left/right` (send(k) on phones; `pressKey` in the studio). Held = repeat; sliding between arms changes direction. Also swipe-mode direction glyph, tap-zone Left/Right, TV remote hints ◀▶▲▼. | `controller.html .arm` (svg triangle), `C/TouchControls.tsx` (char ▲▼◀▶), `tv.*` hints | svg triangle / char | A solid rounded isosceles triangle pointing up. | -filled only (rotated) |
| button-a | A button: sends `a` (action, confirm, ready). Also Joystick "tap for A". *glyph* A. | `controller.html .k.fb`, `C/TouchControls.tsx` ABButtons, `C/calibration/parts.tsx` ABKeys | char A | A circle containing a geometric capital A drawn in strokes. | outline, -filled (pressed) |
| button-b | B button: sends `b` (back, cancel, alternate). Swipe-mode hold or two-finger tap = B ring. *glyph* B. | `controller.html`, `C/TouchControls.tsx` | char B | A circle containing a geometric capital B drawn in strokes. | outline, -filled |
| button-start / button-select | Gamepad legend: Start restarts the game; Select lets the AI play. Text today. | `C/ControlsPanel.tsx` legend, `controller.html` gamepad diagram | text | Start: a pill with a right triangle. Select: a pill with two small bars. | outline (candidate) |
| face-buttons | Brand-neutral face-button diagram (bottom/right/left/top) to replace ✕○□△ and Xbox letters in the legend. | `C/ControlsPanel.tsx` (lib/gamepads GLYPHS), `controller.html` legend | char ✕ ○ □ △ | Four small circles in a diamond, one highlighted per variant. **(generic! no PlayStation shapes/colours)** | -bottom, -right, -left, -top |
| controller-mode-dpad | Controller layout "D-pad + A/B" (switches the phone controller mode, saved per game). | `controller.html #lay`, mode cards; studio touch style picker | svg filled plus | A plus-shaped d-pad with a centre hub. | outline, -filled (selected) |
| controller-mode-joystick | "Analog stick". | same | svg circle + knob | A circle with a smaller filled knob offset to the upper right. | outline, -filled |
| controller-mode-swipe | "Swipe" (swipe = direction, tap = A). Swipe glyph `#swglyph`. | same | svg arrow + dot | A finger-trail dot with a right arrow leaving it. | outline, -filled |
| controller-mode-tap | "Tap zones" (hold left/right halves). | same | svg two rects | Two tall rounded rectangles side by side, the right one emphasised. | outline, -filled |
| controller-mode-keyboard | "Keyboard" mode. Also ControlsPanel per-player keyboard picker, "One player" keyboard setup, MatchSetup device "keys". | `controller.html`, `C/ControlsPanel.tsx`, `C/MatchSetup.tsx` | keyboard | A keyboard with a dot grid of keys and a wide spacebar. | outline, -filled |
| controller-mode-gamepad | "Game controller". Also `gamepad` everywhere:<br>• Play-mode "Controls" (opens Controls panel)<br>• Stage "Play" (full-window game view)<br>• Match "Controllers"<br>• palette "Play a game…"<br>• per-pad card<br>• SchemaForm group "Game"<br>• chess Step<br>• cat-games | `controller.html`, `C/PlayMode.tsx`, `C/Stage.tsx`, `C/MatchSetup.tsx`, `C/ControlsPanel.tsx`, `C/Overlays.tsx` | gamepad-2 | A rounded gamepad with a cross pad on the left and two buttons on the right. | outline, duo, -filled |
| controller-mode-tilt | "Tilt to steer". | `controller.html` | svg tilted phone | A phone tilted 20° with a curved motion arc beside it. | outline, -filled |
| controller-mode-hand | "Hand picker" (rock-paper-scissors). | `controller.html` | svg fist + hand | A closed fist next to an open flat hand. | outline, -filled |
| controller-settings | Controller gear "All controllers and settings" (opens Controls sheet, releases held keys). | `controller.html #gear` | svg gear | = `settings` gear. | — |
| steering-wheel | Tilt mode's live wheel (display only, rotates with tilt). | `controller.html #wheel` | svg wheel | A round steering wheel with three spokes and a top marker. | outline |
| locked-mode | A mode that is unavailable (insecure page or unsupported browser). | `controller.html` | svg padlock | = `lock`. | — |
| two-players | Controls "Two on one keyboard". Casino "Everyone". Multiplayer "Play with friends". Palette "Play with a friend…". | `C/ControlsPanel.tsx`, `C/casino/RightWing.tsx`, `C/Multiplayer.tsx`, `C/Overlays.tsx` | users | Two head-and-shoulder silhouettes, one behind the other. | outline, duo |
| rumble | ControlsPanel "test" rumble on a gamepad. | `C/ControlsPanel.tsx` | vibrate | A phone with short vibration lines on both sides. | outline |
| ready | Ready. Uses:<br>• Match "Ready" (sends `a`; press again to change your mind)<br>• seat Ready badge<br>• multiplayer seat joined<br>• controller "Ready" | `C/MatchSetup.tsx`, `C/Multiplayer.tsx`, `controller.html` | check | = `check`. | -filled |
| game-menu | Match "Menu on panel" (`api.action(app,"menu")`, same as B). Results "Menu" (sends `b`). | `C/MatchSetup.tsx` | home | A house outline (shares `integration-homeassistant` art or a simpler roof). | outline |
| results-trophy | Match results header. Casino phone "Players and leaderboard" (opens leaderboard sheet). | `C/MatchSetup.tsx`, `casino.html #players-btn` (svg trophy) | trophy | A two-handled cup on a short stem and base. | outline, duo |
| leave-friends | Play mode "End friend game" (closes the room, disconnects phones). | `C/PlayMode.tsx` | log-out | A door frame with an arrow leaving to the right. | outline |
| touch-dpad-hub / stick | Joystick base, knob, wedge, d-pad hub. | `C/TouchControls.tsx`, `controller.html` | css | Keep CSS. | — |

### 2.9 Casino actions (studio CasinoStage/wings, phone casino.html)

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| round-start | "Start round" / "Next round": `casinoOp("start_round")` opens betting for a new round. | `C/casino/CasinoStage.tsx` | play | = `play`. | — |
| bets-lock | "Lock now" ("No more bets": closes betting now). Housie "Start calling" (closes buy-in, starts calling numbers). Phone lock banner "No more bets / Paying out / Table closed" (display). | `C/casino/CasinoStage.tsx`, `casino.html #lockb` (svg padlock) | lock | A closed padlock with a rounded shackle. | outline, duo, -open (unlocked) |
| table-pause | Host "Pause" / "Resume" (freezes every timer). | `C/casino/CasinoStage.tsx` | pause / play | = `pause` / `play`. | — |
| caller-pace | Housie caller pace "Call faster −" / "Call slower +" (`casinoOp("pace",{delta})`). | `C/casino/CasinoStage.tsx` | char − + | A minus or plus inside a small stopwatch. | -faster, -slower (candidate) |
| fairness | Provably fair. Uses:<br>• round commitment chip (copies the SHA-256 hash of the round's secret seed, published before any bet)<br>• history "Verify" (recomputes the hash and outcome in this browser)<br>• phone "You: profile, fairness and rules" opens the Fair-play sheet<br>• "Verify on this phone" | `C/casino/CasinoStage.tsx`, `C/casino/RightWing.tsx`, `casino.html` | shield-check | A shield with a check mark inside. | outline, duo, -filled |
| verify-pass / verify-fail | Round proof result: ✓ fair / ✗ mismatch, in the history list and Fair-play checks. | `C/casino/RightWing.tsx` (circle-check / circle-x, char ✓✗), `casino.html` | circle-check / circle-x | A circle with a check; a circle with an X. | outline, -filled |
| casino-room | "Open the room" (opens the casino lobby: QR + room code; phones join, up to 8 seats). | `C/casino/CasinoStage.tsx` | qr-code | A QR-like square with three corner finder squares and a few dots **(not a scannable code)**. | outline, duo |
| leave-casino | "Leave casino": back to the normal studio (the table keeps running). | `C/casino/CasinoStage.tsx` | door-open | An open door with a doorway behind. | outline, duo |
| casino-preset-friendly | House preset "Friendly night" (small stakes, relaxed timers, kindest rules; sets house and rules). | `C/casino/LeftWing.tsx` | coffee | A coffee mug with steam. | outline, duo, -filled (active) |
| casino-preset-vegas | House preset "Vegas" (American wheel, 6-deck shoe, standard limits). | `C/casino/LeftWing.tsx` | sparkles | A marquee star with sparkle rays. | outline, duo, -filled |
| casino-preset-high | House preset "High rollers" (deep stacks, big limits, European wheel + La Partage). Host seat crown in the players list. | `C/casino/LeftWing.tsx`, `C/casino/RightWing.tsx` | crown | A three-point crown with dots on the points. | outline, duo, -filled |
| new-session | "New session…" (confirm → `reset_session`: wallets reset, open bets refunded). "Everyone back to starting credits". | `C/casino/LeftWing.tsx`, `C/casino/RightWing.tsx` | rotate-ccw | = `reset`. | — |
| table-switch-note | Footnote "Switching tables keeps every wallet". | `C/casino/LeftWing.tsx` | gem | A faceted gem. | outline, duo |
| player-kick / player-unkick | Seat "Kick" (`casinoOp("kick",{on:true})`) / "Let back in". | `C/casino/RightWing.tsx` | ban / user-check | Kick: a circle with a diagonal slash. Let back in: a person silhouette with a check. | outline |
| rank-medal | Leaderboard top 3 (gold/silver/bronze tint). | `C/casino/RightWing.tsx` | medal | A round medal hanging from a V ribbon. | outline, duo |
| bet-rebet | "Rebet": places last round's bets again (studio and phone; text-only on phone). | `C/casino/RightWing.tsx`, `casino.html #rebet` | rotate-ccw | A circular arrow around a small chip. | outline |
| bet-clear | "Clear": takes back all your chips this round (`clear`). Text-only today. | `C/casino/RightWing.tsx`, `casino.html #clear` | (none) | A chip stack with a small X. | candidate |
| bet-done | "Done betting" / "✓ Done": tells the table you're done; when everyone is done the round locks early. | `C/casino/RightWing.tsx`, `casino.html #done` | check | = `check`. | -filled |
| game-moves | Header glyph of the per-game move buttons (the moves themselves are text). | `C/casino/RightWing.tsx` | hand | An open raised hand, palm forward. | outline |
| move-hit / stand / double / split / surrender / insurance / no-insurance | Blackjack moves (ws op of the same name):<br>• hit = take a card<br>• stand = keep the hand<br>• double = double the bet, take one card<br>• split = split a pair into two hands<br>• surrender = give up half the bet<br>• insurance / no-insurance = answer the insurance offer | studio RightWing (text), `casino.html` (text) | text | Hit: a card with a plus. Stand: a flat open palm. Double: two stacked chips with ×2 bars. Split: one card splitting into two. Surrender: a small white flag. Insurance: a shield over a card. No-insurance: a shield with a slash. | candidates |
| move-fold / check / call / raise / allin | Hold'em moves:<br>• fold = give up the hand<br>• check = pass without betting<br>• call = match the bet<br>• raise = "Raise to N"<br>• allin = bet the whole stack | same | text | Fold: two cards face-down sliding away. Check: a knuckle-tap mark (two short arcs). Call: two equal chip stacks. Raise: a chip stack with an up arrow. All-in: a tall stack with a burst. | candidates |
| move-pack / chaal / see / show / sideshow / accept / refuse | Teen Patti moves:<br>• pack = fold<br>• chaal = bet<br>• see = look at your cards<br>• show = ask for a final show<br>• sideshow = compare with the previous player<br>• accept / refuse = answer a sideshow | same | text | Pack: cards face-down. Chaal: one chip forward. See: an eye over cards. Show: cards fanned face-up. Sideshow: two fans facing. Accept: a check. Refuse: an X. | candidates |
| housie-claim-* | Housie claims (`claim {prize, ticket}`): early5 (Early Five), top / middle / bottom (lines), corners (Four Corners), full (Full House). | `casino.html` (text); studio gameOps (text) | text | A ticket grid with the claimed part highlighted: 5 dots; the top, middle or bottom row; four corners; all cells. | candidates (6) |
| slots-pull | Slots "PULL" lever (drag the knob down past 60 %) and "SPIN": `pull {bet}`. | `casino.html #sl-lever`, `#sl-go` | css lever | A slot-machine lever with a ball knob, pulled halfway. | outline, duo |
| casino-alert | Big casino alert (rejected bet/move); tap to dismiss. | `C/casino/alert.tsx`, `casino.html #alert` ("!" in gold disc) | circle-alert | A circle with an exclamation mark *glyph*. | outline, -filled |
| casino-help | Phone "How to play and rules" (help sheet: How to play / Rulebook / Payouts). Controller "? Rules". | `casino.html #help-btn`, `controller.html` | char ? | A circle with a question mark *glyph*. | outline, duo |
| sound-on / sound-off | Phone mute toggle (saved; unmuting plays a tap). | `casino.html #snd-btn` | svg speaker + waves / speaker + X | A speaker with two waves; off = speaker with a small X. | outline, -off |
| text-size | Help sheet "Smaller text A−" / "Bigger text A+" (zoom 0.85–1.8). | `casino.html` | text A− A+ | A small and a large A *glyph* side by side, with a minus or plus. | -smaller, -bigger |
| new-seed | Fair-play "New seed": new client seed, used from the next round. | `casino.html #reseed` | text | A seedling sprouting from a small die. | candidate |
| credits-coin | Credit balance marker (display). | `casino.html .bk-coin` (css), studio Credits | css coin | A coin with a striped edge, seen face-on. | outline, duo |
| escrow | "On the table (escrow)" amount in a seat row. | `C/casino/RightWing.tsx` | char ⛁ | A small stack of three chips seen from the side. | outline |

### 2.10 Casino games & glyphs

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| suit-spade | Card suit ♠ (cards, TV casino pips, empty-state ornament). | `C/casino/RightWing.tsx` MyCards, `casino.html` PC.card, `tv/tv-casino.js` suitPath, `casino.css .cz-empty` | char ♠ / canvas | A classic spade with a short stem. | -filled (primary), outline |
| suit-heart | ♥ (red). | same | char ♥ | A symmetrical heart. | -filled, outline |
| suit-diamond | ♦ (red). | same | char ♦ | A tall rhombus with slightly concave sides. | -filled, outline |
| suit-club | ♣. | same | char ♣ | Three round lobes with a short stem. | -filled, outline |
| card-back | Face-down card (`.pc.back`); blackjack dealer "+?" hole card. | `casino.html`, `tv/tv-casino.js` | css | A portrait card with a lattice pattern. | outline, duo |
| card-slot | Empty card slot (`.pc.empty`). | `casino.html` | css | A dashed portrait card outline. | outline |
| chip | Casino chip (rack selector, flying chips, stake badges, confetti, TV chips). The value is drawn as text by code: 1, 5, 25, 100, 500, 1K … 1M. Tapping a rack chip selects that value; tapping a spot bets one chip (`bet {spot,amount}`); holding a spot for 550 ms or dragging off it takes chips back (`unbet`). | `C/casino/bits.tsx` Chip, `casino.html #rack`, `tv/tv-casino.js` | css / canvas | A face-on chip: an outer ring with six edge inserts and an empty centre disc (the label is overlaid by code). | outline, duo, -selected |
| chip-all-in | "All in" chip: bet = min(free credits, max bet). | `casino.html .chip.call`, studio rack | css "ALL IN" | A chip with an upward burst in the centre (no text). | outline, duo |
| chip-remove | Red ✕ badge on a dragged chip ("let go to take it back"). | `casino.css`, `casino.html .fly.ghost.rm` | char ✕ | = `close` in a small filled circle. | -filled |
| dealer-button | Poker / Teen Patti dealer seat "D". | `casino.html`, `tv/tv-casino.js` | text D | A white disc with a geometric D *glyph*. | -filled |
| seat-tag-* | Seat tags: AI = all-in, S = seen, B = blind (Teen Patti). | `casino.html` | text | All-in: a chip stack burst. Seen: an eye. Blind: an eye with a slash. | candidates |
| dolly | Roulette win marker (crystal dolly on gold base, lowered onto the winning number). | `tv/tv-casino.js` dollyPaint | canvas | A small chess-pawn-like marker with a wide base and a faceted head. | outline, duo |
| roulette-wheel | (concept) roulette spin / app tile. | app tile | circle-dot | See `app-casino-roulette`. | — |
| diamond-red / diamond-black | Roulette Red and Black bet spots. | `casino.html .dia` | css rhombus | A rhombus. | -filled |
| dice | 7 Up 7 Down dice; TV dice. | `casino.html`, `tv/tv-casino.js` | css / canvas | A single die face showing three pips diagonal. | outline, duo |
| sevens-under / sevens-lucky / sevens-over | Bet zones "Under 7 ▼", "Lucky 7", "Over 7 ▲". | `casino.html` | char ▼ 7 ▲ | Under: a down chevron over a bar. Lucky 7: a die with a four-point sparkle. Over: an up chevron over a bar. | candidates |
| bigsix-joker | Big Six "joker" segment (spot `joker`). | `casino.html` (char 🃏), `tv/tv-casino.js` ("J") | emoji 🃏 | A jester's three-pointed hat with bells. | outline, duo |
| bigsix-logo | Big Six "logo" segment (spot `logo`). | `casino.html` (★), `tv/tv-casino.js` (★) | char ★ | A five-point star in a circle. | outline, -filled |
| andar / bahar | Andar Bahar zones A (blue) / B (red). Text today. | `casino.html` | text | Left-pointing card stack / right-pointing card stack. | candidates |
| baccarat-player / banker / tie / pair | Baccarat zones and side bets; bead road P/B/T. | `casino.html` | text | Player: a single person. Banker: a vault door. Tie: an equals bar. Pair: two cards. | candidates |
| housie-ball | Housie called ball (shows "?" before the first call); "Board" opens the called-numbers sheet. | `casino.html` | css | A bingo ball with a blank band. | outline, duo |
| housie-ticket | Ticket cells / daub stamp; tickets "−/+" buy count; "I'm ready". | `casino.html` | css | A ticket with a 3×5 grid and one daubed circle. | outline, duo |
| history-pill | Last 12 results strip; studio "Rounds" tab. | `casino.html #hist`, `C/casino/RightWing.tsx` | css pills | Optional: a clock with a short list. | candidate |
| countdown-ring | Betting countdown dial (∞ when no timer). | `C/casino/bits.tsx`, `casino.html #ring` | svg ring | Keep code-drawn. | — |
| win-stamp | TV "WIN" / "TIE" stamp. | `tv/tv-casino.js` | canvas text | Keep code-drawn. | — |
| who-dots | Up to 5 player-colour dots on a spot. | `casino.html .wd` | css | Keep CSS. | — |
| slot-symbols | Reel symbols (Seven, Bar, Bell, Plum, Orange, Lemon, Cherry; neon and space sets). | engine pixel sprites | pixel art | **Out of scope** (panel pixel art). | — |
| avatars | Player 8×8 avatars: bot, cat, ghost, alien, knight, ninja, slime, frog. | `src/deskdot/gfx/avatars.py` | pixel art | **Out of scope** (panel pixel art). | — |

### 2.11 TV view & remote menu

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| tv-quality-auto / hq / lite | Remote menu "Quality":<br>• Auto (picks per screen)<br>• HQ (full quality)<br>• Lite (less work for slow sticks)<br>Applies to this TV. Also the studio TV sheet "TV quality" segment. | `tv.*` `.tvm-opt`, `C/TvSheet.tsx` | text | Auto: a gauge needle with an A-less spark. HQ: a diamond. Lite: a feather. | candidates |
| tv-theme-dark / light | Remote menu "Theme": a dark room or ivory room preview. | `tv.*` | svg room | A wall with a lit 2×2 LED panel, dark or light background. | -dark, -light |
| tv-menu-check | Marks the selected option. | `tv.*` `::after` | char ✓ | = `check`. | — |
| remote-keys | Hints "◀ ▶ ▲ ▼ Move · OK Choose · Back Close". | `tv.*` `.tvm-hint` | chars | `dpad-arrow` plus an OK disc and a back-arrow keycap. | -ok, -back |
| tv-waiting | Veil "Waiting for DeskDot…" (chasing dots). | `tv.*` `.veil-dots` | css dots | Keep CSS. Optional: four dots in a row. | — |
| tv-link-closed / too-many / bad-link | Veil error states: link closed, too many screens, link doesn't look right. | `tv.*` | (none) | Closed: a broken chain link. Too many: three overlapping screens. Bad link: a link with a question mark. | candidates |
| tv-lives | Hearts left in TV games ("♥" repeated). | `tv/tv-games.js` | char ♥ | = `suit-heart`. | — |
| tv-rating | Fish rating ★/☆, "★ New best". | `tv/tv-games.js` | char ★ ☆ | = `favourite` filled/outline. | — |
| tv-leader | "♛" crown on the leading seat. | `tv/tv-games.js` | char ♛ | = `casino-preset-high` crown. | — |
| tv-versus | "VS" badge / round timer ring. | `tv/tv-games.js` | text / svg | Optional: two crossed swords. | candidate |

### 2.12 Themes

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| theme-light | "Light" (porcelain and ink, rose accents): `setThemePref("light")`. Theme FAB sun (tap toggles to the other theme, hold for the menu). | `C/ThemePicker.tsx`, `C/ThemeFab.tsx` | sun | = `brightness` sun, slightly bolder. | outline, -filled (selected) |
| theme-dark | "Dark" (graphite instrument panel). Theme FAB moon. | same | moon | A crescent moon. | outline, -filled |
| theme-auto | "Auto" (follow this device / phone). | same | monitor | A half-filled circle (light/dark split). Do not reuse `section-display`. | outline, -filled |
| theme-selected | Check on the current choice in the FAB menu. | `C/ThemeFab.tsx` | check | = `check`. | — |

### 2.13 Status & feedback

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| check | Confirm, done or selected. Uses:<br>• Save (Integrations, CalAdvanced "Save", "Save calibration", preset-name Save)<br>• "Use this" / "Use it" / "Apply" in calibration<br>• Picker selected row<br>• app-icon selected badge<br>• copied ✓<br>• AI key configured<br>• casino preset active<br>• Done betting<br>• ready states<br>• verify ✓<br>• Habits tick<br>• TV menu ✓ | many (`C/*`, `casino.html`, `tv.*`) | check | A check mark with a slightly longer right arm. | outline, -filled (in circle) |
| warning | Warning note. Uses:<br>• Connection problem<br>• "Release the panel" confirm text<br>• MotionLab "packet spacing below presets"<br>• ControlsPanel conflicts (triangle-alert, red) | `C/ConnectionSheet.tsx`, `C/Settings.tsx`, `C/calibration/MotionLab.tsx`, `C/ControlsPanel.tsx` | alert-triangle / triangle-alert | A rounded warning triangle with an exclamation *glyph*. | outline, duo |
| info | Info note. Uses:<br>• Controls "what works where"<br>• App-icon picker note<br>• casino win card "tap ⓘ to verify" (no such button exists; candidate for opening Fair play) | `C/ControlsPanel.tsx`, `C/AppIconPicker.tsx`, `casino.html` | info | A circle with a lowercase-i shape (dot plus stem). | outline, duo |
| toast-tone | Toast LED: ok / error / ember. | `C/Overlays.tsx` Toasts | css LED | Keep CSS. Optional icons: `check` / `warning` / `info`. | — |
| live-badge | "Live" badge on a library tile; "Live from the table". | `C/Library.tsx`, `casino.html` | css LED + text | Optional: a dot with two broadcast arcs. | candidate |
| onair-chip | Platform strip "ON AIR" chip (stop preview = `close`). | `C/PlatformStrip.tsx` | css LED | = `integration-onair`. | — |
| loading | Busy spinners / skeletons (launcher row, controller reconnect, chip-stack loader). | `L/Launcher.tsx`, `controller.html #recon`, `casino.html .stack` | css | Keep CSS (the casino chip-stack loader is brand art). | — |
| empty-library | Library "nothing matches" / "no favourites yet". | `C/Library.tsx` | search / star | = `search` / `favourite`. | — |
| empty-ai | AI creator "Type a prompt and click generate". | `C/AiCreator.tsx` | sparkles | = `create-ai`. | — |
| engine-offline | Launcher "Can't reach the DeskDot engine" / "Nothing matches" (text only today). | `L/Launcher.tsx` | (none) | A plug with a small cloud-slash. | candidate |
| copy-done | Copy → ✓ swap after copying an address or hash. | `C/TvSheet.tsx`, `C/Multiplayer.tsx`, `C/casino/CasinoStage.tsx` | copy → check | = `duplicate` → `check`. | — |

### 2.14 Fruit fly

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| fly-play | "Let the fly play" toggle:<br>• in a game: `letFlyPlay()` hands the game to the fruit-fly brain (F)<br>• otherwise: opens the game picker<br>• while playing: shows "Fly playing · Take back" (`takeBackFromFly()`)<br>Also palette "Let the fly play", launcher "Let the fly play" / "Play <App> with the fly" (pilot = fly), Stage "Fly view", fly status pill, Fly view header. | `C/FlyToggle.tsx` FlyGlyph (svg), `C/Overlays.tsx`, `C/Stage.tsx`, `C/fly/FlyView.tsx`, `L/Launcher.tsx` (bug) | svg fly / bug | A top-down fruit fly: two angled oval wings, round thorax, oval abdomen, two big eyes. | outline, duo, -filled (playing; wings animate in CSS) |
| fly-take-back | "Take back" (palette "Take the game back from the fly", Fly view "Take back"): the fly returns to roaming and you get the game. Launcher "Give <app> back to the AI" (pilot = ai). | `C/Overlays.tsx`, `C/fly/FlyView.tsx`, `L/Launcher.tsx` (bug) | hand | A hand reaching to grab, palm down. | outline, duo |
| fly-roam | Roaming-fly sign:<br>• on: green "flies welcome" ring with a check; click sprays it away (mist puff)<br>• off: red prohibition slash; click lets it back | `C/FlyToggle.tsx` RoamSign (svg) in the top bar, Quick controls, casino title, fly bar | svg fly in ring + check / slash | A fruit fly inside a circle; on = a small check at the lower right; off = a diagonal prohibition slash. | -on, -off |
| fly-view-settings | Fly view settings header "Fly view" (graphics, scene, fly & keys, brain, layout tabs). | `C/fly/FlyView.tsx` | gauge | A semicircular gauge with a needle. | outline, duo |
| fly-panels | Fly view "Panels": closes the fly view, brings the side panels back. | `C/fly/FlyView.tsx` | panel-left-open | A window with a left sidebar and a right-pointing chevron. | outline |
| fly-brain | "Needs a newer engine" note in the Brain tab. Brain view icon. AI model "Pro". | `C/fly/FlyView.tsx` | brain | A brain outline with a central fissure. | outline, duo |
| fly-full-view-* | Full-screen "What to show": Brain / Both / Keyboard, and layouts Side by side / Brain big / Stacked. Text segments today. | `C/fly/FlyView.tsx` | text | Brain = `fly-brain`. Keyboard = `controller-mode-keyboard`. Both = brain + keyboard split. Layouts: two columns / one large + inset / two rows. | candidates |
| fly-emoji-tip | Roaming fly tooltip "🪰 Let the fly play — click me". | `C/RoamingFly.tsx` | emoji 🪰 | Replace with `fly-play`. | — |

### 2.15 App catalogue (one icon per app, 117 registered; `eyebreak` and `onair` are hidden)

Every app tile, library card, rail row, palette entry, Inspector header, "Now showing" card, playlist row, Play-mode
game list and fly game picker renders `Icon`/`IconTile` with the app's declared `icon`. **Pressing** an app anywhere
calls `api.activate(id)`, which shows it on the panel (in Play mode it switches game; in the fly picker it runs
`letFlyPlay(id)`). Ids are `app-<app id>`. All need outline, duo and -filled variants (`IconTile solid` when the app
is playing or selected).

| id | what it means (what the app shows) | category | current glyph | drawing prompt |
|---|---|---|---|---|
| app-clock | Clock faces: hero, stacked, minimal, analog with a seconds ring | time | clock | A round analog clock at ten past ten with a seconds dot on the rim. |
| app-countdown | Counts down to any moment | time | hourglass | An hourglass with sand mostly in the bottom bulb and a falling stream. |
| app-daynight | World map with the live day/night terminator | time | earth | A globe split by a curved terminator, night half with two city-light dots. |
| app-fiveoclock | A city where it's 17:xx now, clinking glasses | time | beer | Two beer mugs clinking at an angle with a foam splash. |
| app-holidays | Countdown to the next public holiday | time | party-popper | A party popper cone bursting confetti dots and streamers. |
| app-longweekend | Days to the next long weekend | time | tree-palm | A palm tree leaning over a small sun on the horizon. |
| app-progress | Day/week/month/year progress bars, ring or dot grid | time | hourglass | A horizontal progress bar two-thirds filled with a percent-tick above it. |
| app-sky | Sunrise/sunset, the sun's path, moon phase | time | sunrise | A half sun on a horizon line with an up arrow above it. |
| app-airquality | AQI gauge, pollutants, UV, pollen | data | wind | A leaf with a small gauge arc behind it. |
| app-asteroidflyby | Next asteroid passing near Earth | data | orbit | A small rock tracing a dashed arc past a tiny planet. |
| app-aurora | Kp index and aurora chance | data | sparkles | Three wavy vertical curtains of light over a horizon line. |
| app-bikeshare | Bikes and docks at nearby stations | data | bike | A side-view bicycle with round wheels. |
| app-btcnet | Bitcoin fees, block time, halving | data | bitcoin | A chain of three linked cubes with a small clock **(generic! no ₿ coin logo)**. |
| app-cryptomarket | Crypto market cap, dominance, movers, fear & greed | data | coins | A stack of three generic coins with a small up/down arrow pair. |
| app-currency | Exchange rates and converter | data | banknote | A banknote with two opposing exchange arrows over it. |
| app-earthevents | Wildfires, storms, volcanoes on a world map | data | earth | A globe with a small flame marker and a storm swirl on it. |
| app-gameserver | Players online on your block-game server | data | server | A server rack with two drive bays and a person-count dot **(generic! no Minecraft)**. |
| app-github | Contribution graph, total, streak | data | git-commit-horizontal | A 3×5 grid of small squares in varied fill densities **(generic! no Octocat)**. |
| app-hassentity | Any Home Assistant entity: state, unit, sparkline | data | house | A house with a small sensor dot and a sparkline below **(generic! not the HA logo)**. |
| app-headlines | HN / Spaceflight / DEV / Lobsters stories | data | newspaper | A folded newspaper with a headline bar and text lines. |
| app-markets | Crypto prices with 24 h change | data | chart-candlestick | Three candlesticks of different heights with wicks. |
| app-planets | Naked-eye planets tonight on a sky dome | data | orbit | A ringed planet with two small dots on a dashed orbit. |
| app-quakes | Live earthquakes, map with pulsing rings | data | activity | A seismograph spike line with a ring pulse under the peak. |
| app-racecountdown | Next Grand Prix countdown, live, podium | data | flag | A chequered flag on a pole **(generic! no F1 logo)**. |
| app-radar | Radar scope of live aircraft | data | radar | A radar scope circle with a sweep wedge and a plane blip. |
| app-rainchance | Rain chance per hour for 12 h | data | umbrella | An open umbrella with three raindrops beside it. |
| app-rainradar | Animated rain radar with home marker | data | cloud-rain | A cloud over a grid of radar-dot rain. |
| app-scores | Live sports scores | data | trophy | A scoreboard rectangle with two score digits replaced by bars, and a ball. |
| app-space | Next launch, ISS, people in orbit | data | rocket | A rocket lifting off with a short exhaust plume. |
| app-stocks | Stocks/indices cards, ticker, heatmap | data | trending-up | A rising line chart with an arrowhead and baseline. |
| app-sysmon | Live CPU, memory, storage, network | data | cpu | A chip with pins and a small bar meter inside. |
| app-tides | Tide curve and surf | data | waves-horizontal | Two stacked waves with a high-tide marker. |
| app-tvtonight | What's on TV now and tonight | data | tv | A retro TV with a crescent moon on screen. |
| app-wear | What to wear for the next hours | data | shirt | A T-shirt with a small weather drop on the chest. |
| app-weather | Animated conditions and temperature | data | cloud-sun | A sun partly behind a cloud. |
| app-wikitrending | Most-read Wikipedia articles, spike chart | data | trending-up | An open book with a small spike chart rising from it **(generic! no Wikipedia W)**. |
| app-windcompass | Wind speed, gusts and direction on a compass | data | wind | A compass rose with a wind arrow through it. |
| app-worldflags | Flag of the day, quiz | data | flag-triangle-right | Three small pennant flags of different shapes on poles. |
| app-camera | Webcam on the LEDs with looks | media | camera | A webcam on a little base with a lens dot. |
| app-gallery | Your uploaded photos and pixel art | media | images | Two overlapping photo frames with a mountain and sun. |
| app-mediaserver | Latest home-media additions and streams | media | clapperboard | A stack of film posters with a play triangle **(generic! no Plex/Jellyfin)**. |
| app-mirror | Your screen mirrored on the LEDs | media | monitor-up | A monitor with a smaller LED-dot square reflected at the right. |
| app-nowplaying | Album art, lyrics, vinyl, spectrum | media | music | A vinyl record with a music note overlapping it **(generic!)**. |
| app-photoframe | Art and nature slideshow | media | frame | A thick picture frame with a hanging wire. |
| app-visualizer | Reacts to what the PC plays | media | audio-lines | Mirrored equaliser bars around a centre line. |
| app-pet | A pixel pet that wanders, naps, dances | pets | paw-print | A paw print with four toe pads. |
| app-petworld | Lofi pets in a scrolling world | pets | trees | Two small trees and a little pet silhouette walking between. |
| app-pokedex | Creature of the day: sprite, types, stats | pets | sparkles | An index card with a cute round creature silhouette and stat bars **(generic! no Pokéball, no Pokédex device)**. |
| app-arcade | Snake (2–4 snakes, arenas) | games | gamepad-2 | A segmented snake curving around a single apple dot. |
| app-asteroids | A tiny ship among splitting rocks | games | orbit | A triangle ship with three jagged rocks around it **(generic!)**. |
| app-breakout | Smash a brick wall | games | brick-wall | A paddle and ball under three rows of bricks **(generic!)**. |
| app-chess | Daily chess puzzle | games | crown | A chess knight head **(generic! no Chess.com pawn)**. |
| app-cycles | Glowing bikes leaving walls | games | zap | Two right-angle light trails meeting head-on **(generic! no Tron cycle)**. |
| app-digworld | Block-world miner sandbox | games | pickaxe | A pickaxe over a single cube with ore dots **(generic! no Minecraft)**. |
| app-dino | Endless desert runner | games | footprints | A small cactus with a jump arc over it **(generic! no Chrome dino)**. |
| app-flappy | A bird threading pipes | games | bird | A round little bird between two vertical pipe gaps **(generic!)**. |
| app-fourup | Four-in-a-row | games | grid-3x3 | Four discs in a diagonal line on a hint of grid **(generic! no Connect Four rack)**. |
| app-g2048 | Slide and merge tiles | games | grid-2x2 | Two rounded tiles merging into one with motion lines **(generic!)**. |
| app-gamedeals | Free games and PC discounts | games | gamepad-2 | A price tag with a gamepad cut-out. |
| app-infinity | A ship flying through a neon cave | games | infinity | A tiny ship inside a wavy tunnel. |
| app-invaders | Hold off a marching alien fleet | games | rocket | A generic flying saucer over a small cannon **(generic! no Space Invaders crab)**. |
| app-leafleap | Flip-screen platformer | games | sprout | A sprout character jumping between two platforms toward a flag. |
| app-maze | Eat dots in a maze while chased | games | ghost | A maze corner with a row of dots and a chaser blob **(generic! no Pac-Man ghost)**. |
| app-mines | Minesweeper | games | bomb | A round mine with a fuse spark beside a small flag. |
| app-neonheat | Neon city getaway, cops & robbers | games | siren | A car seen from above with a police light flashing. |
| app-penguin | Sliding-ice escape puzzle | games | snowflake | A penguin on an ice tile with a slide arrow. |
| app-pong | Paddles and ball | games | circle-dot | Two vertical paddles with a ball and a dashed centre line. |
| app-raycaster | First-person 3D dungeon | games | **square (missing)** | A corridor in one-point perspective with a doorway at the end. |
| app-rps | Rock paper scissors | games | hand | A fist, an open palm and a V hand in a row. |
| app-starship | Vertical space shooter | games | plane | A pointed fighter ship with two shot dashes ahead. |
| app-streetsurge | Pseudo-3D street race | games | gauge | A road vanishing to a point with a speed gauge arc. |
| app-tetris | Falling blocks | games | blocks | A single falling square group dropping into a gap in a floor **(generic! no tetromino set/colours)**. |
| app-tictactoe | X and 0 | games | hash | A 3×3 grid with one X and one O stroke. |
| app-trivia | Quiz with A–D answers | games | circle-question-mark | A speech bubble with four small answer bars. |
| app-casino-andarbahar | Andar Bahar | casino | spade | A joker card with two card stacks fanning left and right. |
| app-casino-baccarat | Baccarat (Punto Banco) | casino | spade | Two cards face-up side by side with a small "vs" bar between. |
| app-casino-bigsix | Big Six money wheel | casino | disc | A wheel of segments with a clapper at the top. |
| app-casino-blackjack | Blackjack | casino | club | Two overlapping cards (an ace shape and a face card) with a chip. |
| app-casino-holdem | Texas Hold'em | casino | spade | Two hole cards over a row of three board cards. |
| app-casino-housie | Housie / tambola | casino | **grid (renders as square)** | A bingo ticket with daubed numbers and a called ball. |
| app-casino-roulette | Roulette | casino | circle-dot | A roulette wheel top-down with pockets and a ball. |
| app-casino-sevens | 7 Up 7 Down | casino | dices | Two dice showing three and four pips. |
| app-casino-slots | Slots | casino | cherry | A three-reel window with a lever at the side. |
| app-casino-teenpatti | Teen Patti | casino | spade | Three cards in a tight fan. |
| app-avatar | Pixel avatars and identicons | creative | user-round | A pixel-stepped face inside a rounded square **(generic! no Minecraft face)**. |
| app-boids | Flocking boids, particle life | creative | **square (missing)** | Five small arrowhead birds flying in a loose V. |
| app-brain | Spiking neural network waves | creative | **square (missing)** | A cluster of linked neuron nodes with a pulse travelling along one link. |
| app-canvas | Pixel painting on the LEDs | creative | brush | A brush painting a stepped pixel stroke. |
| app-composer | Text Studio: layout text and live values | creative | text-cursor-input | A text box with a blinking I-beam cursor. |
| app-emotes | Full-screen animated emotes | creative | face-slightly-smiling-plus | A grinning face with a small plus sparkle. |
| app-flybrain | Fruit fly driven by its visual circuit | creative | bug | = `fly-play` fly with a small neuron spark above its head. |
| app-fontlab | Fonts, styles, fills, animations | creative | case-sensitive | An "Aa"-like pair of letterform shapes (one serif, one pixel). Allowed glyph. |
| app-pixabots | Animated robot avatars | creative | bot | A boxy pixel robot waving one arm. |
| app-playercard | Your own rated football card | creative | id-card | A shield-topped collectible card with a portrait circle and stat bars **(generic! no FIFA card shape)**. |
| app-sand | Falling sand simulation | creative | **square (missing)** | A pile of grains under a pouring stream. |
| app-synthwave | 80s outrun horizon | creative | **square (missing)** | A striped setting sun over a perspective grid floor. |
| app-text | Scrolling or auto-fitted messages | creative | type | A text line with a scroll arrow under it. |
| app-wireframe | 3D vector graphics, tesseract | creative | **square (missing)** | A wireframe cube nested inside a larger cube, corners joined. |
| app-activeapp | Icon of the app you're using + focus time | productivity | app-window | A window with a title bar and a small timer badge. |
| app-agent | Agent mascot status: thinking/working/done | productivity | bot | A friendly agent face with a thought bubble **(generic! no Claude mascot)**. |
| app-anki | Flashcards due today | productivity | layers | Two stacked flashcards with a flip arrow **(generic! no Anki star)**. |
| app-calendar | Next meeting countdown, timeline | productivity | calendar-clock | A calendar page with a small clock at the lower right. |
| app-ci | CI status tiles, deploy verdict | productivity | git-branch | A branching line with three nodes and a check on one. |
| app-custom | Screens pushed by scripts | productivity | webhook | = `webhook` hooks. |
| app-daily | Quotes, jokes, facts | productivity | quote | Two heavy open quotation marks. |
| app-eyebreak | 20-20-20 eye break (hidden) | productivity | eye | An eye with a tiny timer arc around it. |
| app-focuspet | Lofi pet that studies with you | productivity | **square (missing)** | A small pet at a desk lamp with a book. |
| app-habits | Three daily habits, streak flame | productivity | flame | A flame above a row of three dots. |
| app-obs | Streaming LIVE/REC status | productivity | radio | A red-dot REC circle beside a broadcast arc **(generic! no OBS ring)**. |
| app-onair | ON AIR sign (hidden) | productivity | radio | A lit rectangular sign plate with a mic grille dot. |
| app-qr | Wi-Fi / link / note QR | productivity | qr-code | = `casino-room` QR art with a Wi-Fi arc. |
| app-timer | Pomodoro, countdown, stopwatch | productivity | timer | A stopwatch with a tomato-like cap leaf **(generic)**. |
| app-uptime | HTTP/TCP checks, outage alerts | productivity | activity | A heartbeat line passing through a status dot. |
| app-ambient | Plasma, aurora, lava, fireworks… | ambient | sparkles | Soft overlapping blobs like a lava lamp. |
| app-loops | Novelty loops | ambient | infinity | An infinity loop with a small pixel cat-head dot riding it **(generic! no Nyan Cat)**. |
| app-native | The panel's own firmware modes | device | microchip | A microchip with a small LED dot grid on its face. |
| app-printer | 3D printer progress, temperatures | device | printer | A 3D-printer gantry with a nozzle over a half-built cube. |

### 2.16 Categories

Used for library chips and section headers, app-rail headers, category tints and category presets. Pressing a chip
filters the library (`prefs({category})`). The launcher has a *different* map (in brackets); the pack should
unify both on these ids. Each needs outline, duo and -filled.

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| cat-time | "Time" category; Composer kind "Time". Preset "Clocks & time" uses `clock`. | `C/Icon.tsx` CATEGORY_ICON, `C/AppRail.tsx`, `C/Library.tsx`, `L/Launcher.tsx` [Clock] | clock-3 | A clock face with hands at three o'clock. | outline, duo, -filled |
| cat-data | "Live data". Settings "Data sources". Composer effect "Pulse". Preset "Live data". | same [Zap] | activity | A pulse line with one sharp peak. | outline, duo, -filled |
| cat-media | "Media" (preset uses `music`). | same [Music] | image | A picture frame with a mountain and sun. | outline, duo, -filled |
| cat-creative | "Create". Preset "Creative & art". | same [Palette] | palette | = `block-calibrate` palette. | -filled |
| cat-ambient | "Ambient". Preset "Ambient". | same [Sparkles] | sparkles | Three soft sparkles over a wave. | outline, duo, -filled |
| cat-productivity | "Focus & agents" (preset uses `briefcase`). | same [Workflow] | target | A bullseye of three rings with a centre dot. | outline, duo, -filled |
| cat-pets | "Pets & characters". Preset "Pets & characters". | same [PawPrint] | paw-print | = `app-pet` paw (give the category a two-paw variant). | outline, duo, -filled |
| cat-games | "Games". Preset "All games". | same [Gamepad2] | gamepad-2 | = `gamepad`. | -filled |
| cat-casino | "Casino". Top-bar Casino button. | same [Dices] | dices | = `casino-open` dice. | -filled |
| cat-device | "Panel" (device). | same [Monitor] | cpu | A small LED panel square with a 3×3 dot grid. | outline, duo, -filled |
| cat-favourites | Rail "Favourites". | `C/AppRail.tsx` | star | = `favourite`. | -filled |
| cat-recent | Rail "Recent". | `C/AppRail.tsx` | rotate-ccw-clock | = `recent`. | -filled |

### 2.17 Presets

Pressing a preset calls `api.playPreset(id, shuffle)`, which fills the playlist and starts rotating. The card's play
key toggles play/stop, and the toast says "Playing <name>". Each needs outline, duo and -filled (active preset = solid).

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| preset-dashboard | "Desk dashboard": clock, weather, stocks, currency, headlines, sky. | `src/deskdot/engine/presets.py`; `C/PlaylistDock.tsx` cards/dock, `C/Settings.tsx`, palette, launcher | layout-dashboard | Four unequal panels: one tall, three small. | outline, duo, -filled |
| preset-chill | "Chill": petworld, loops, ambient, photoframe, pet. | same | coffee | = `casino-preset-friendly` mug. | -filled |
| preset-planet | "Planet & space": daynight, space, quakes, rainradar, airquality, planets. | same | globe | A globe with latitude and longitude lines. | outline, duo, -filled |
| preset-cat-games | "All games" (45 s each). | same | gamepad-2 | = `cat-games`. | -filled |
| preset-cat-pets | "Pets & characters" (40 s each). | same | paw-print | = `cat-pets`. | -filled |
| preset-cat-time | "Clocks & time" (20 s each). | same | clock | = `app-clock` or `cat-time`. | -filled |
| preset-cat-data | "Live data" (15 s each). | same | activity | = `cat-data`. | -filled |
| preset-cat-media | "Media" (20 s each). | same | music | A double music note. | outline, duo, -filled |
| preset-cat-creative | "Creative & art" (25 s each). | same | palette | = `cat-creative`. | -filled |
| preset-cat-ambient | "Ambient" (45 s each). | same | sparkles | = `cat-ambient`. | -filled |
| preset-cat-productivity | "Focus & desk" (20 s each). | same | briefcase | A briefcase with a handle. | outline, duo, -filled |
| preset-everything | "Everything": every app that isn't excluded. | same | infinity | An infinity loop drawn as one continuous stroke. | outline, duo, -filled |
| preset-user | Any user-saved preset (always the fallback). | same | list-music | = `tab-presets`. | -filled |

### 2.18 Android launcher & brand artwork (generated by `android/tools/gen_icons.py`)

These are **app-icon artwork** on a 108×108 adaptive canvas, not UI glyphs. Commission them separately or keep the
generator. Picking one in Settings → App icon (`C/AppIconPicker.tsx`, radio) calls `MainActivity.switchIcon(id)`
(which enables that launcher alias and disables the others) and shows a check badge.

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| launcher-classic | "Classic": the original ember dot D (default; also `ic_launcher.xml`). | Android launcher, `web/src/lib/appIcons.ts` | svg dot D | A 5×5 ember dot "D" on graphite. | adaptive fg/bg/mono |
| launcher-monogram | "Monogram": DD in rose and gold LEDs. | same | svg | Two dot-matrix D's, rose and gold. | adaptive |
| launcher-ink | "Gold leaf": gold dots on midnight ink. | same | svg | A gold dot D on deep indigo. | adaptive |
| launcher-sunset | "Sunset": rose-to-gold tile, white LEDs. | same | svg | A white dot D on a rose→gold gradient. | adaptive |
| launcher-porcelain | "Porcelain": the panel on an ivory tile. | same | svg | A black panel with a rainbow dot D and a gold rim on ivory. | adaptive |
| launcher-chip | "Casino chip": an ember chip on green felt. | same | svg | A red chip with white inserts and a gold dot D on felt. | adaptive |
| launcher-heart | "Pixel heart": a lit pixel heart. | same | svg | A dot-matrix heart. | adaptive |
| android-notification | Small icon on the ongoing engine-service notification (tap opens the app). | `ic_stat_deskdot.xml` | svg 3×3 dots | A white 3×3 dot grid, single colour. | mono 24 dp |
| desktop-tray | Desktop tray icon. Its menu is text: "Show (hotkey)", "Open studio", "Start DeskDot engine", "Start with login", "Quit launcher". | `src/deskdot/launcher.py` tray_image | PIL dots | A 4×4 gradient dot glyph on a dark rounded square. | 16/32 px |
| favicon | Browser tab icon for the studio, launcher and TV. | `web/public/favicon.svg` | svg DD | A rose-and-gold DD dot monogram on a dark tile. | 16/32 px |
| brand-dotmark | Launcher header 4×4 brand dot mark (decorative). | `L/Launcher.tsx` DotMark | css | Keep code-drawn. | — |

### 2.19 Misc

| id | what it means / what pressing it does | where it appears | current glyph | drawing prompt | variants |
|---|---|---|---|---|---|
| launcher-autostart | Launcher search-only row "Start with login" (toggles autostart); falls back to Sparkles by accident. | `L/Launcher.tsx`, `L/search.ts` | sparkles (fallback) | A power symbol with a small sunrise arc. | outline |
| launcher-quit | Launcher row "Quit launcher" (quits the shell); falls back to Sparkles. | same | sparkles (fallback) | A door with an exit arrow (can share `leave-friends`). | outline |
| ai-prompt-chips | AI creator preset prompt chips use emoji: 🔥 Campfire, 🚀 Rocket, ⚡ Neon Heart, 🌧 Thunderstorm, 🐱 Cat, 👾 Arcade Ghost, ☕ Mug, 🪐 Planet. | `C/AiCreator.tsx` PRESET_PROMPTS | emoji | Optional set of 8: campfire, rocket, heart with bolt, storm cloud, cat face, pixel ghost **(generic!)**, steaming mug, ringed planet. | outline, duo (optional) |
| notice-icons | 27 LED notice icons for "Send a message" (bell, info, warn, ok, error, mail, chat, heart, claude, home, bolt, drop, temp, sun, cloud, bulb, battery, door, lock, person, fire, star, music, clock, eye, mic, cam). They are panel pixel sprites; the studio shows them as **text chips** today (pressing one picks the icon for the notice). | `src/deskdot/gfx/icons.py`, `C/Overlays.tsx` Notify | text chips | Optional: 27 vector twins so the chips can show pictures. `claude` → a generic spark **(no Anthropic mark)**. | outline (optional, 27) |
| select-caret | Fly view mini-select caret. | `index.css .fly-mini` data-URI | svg triangle | = `chevron-down` (filled micro). | -filled |
| keycaps | Keyboard hints (Ctrl K, ← ↑ → ↓, WASD, Space, Esc, ↵, ⌘). | many | text kbd | Keep as text keycaps. | — |
| qr-codes | Real scannable QR codes (TV link, lobby, casino room, app QR). | `C/Multiplayer.tsx` QrCode, `C/TvSheet.tsx`, `tv.*` | generated | **Out of scope.** | — |
| logo-led | DeskDot LED wordmark (studio, TV, phones, host landing). | canvas | brand art | **Out of scope.** | — |

---

## 3. Counts

Rows counted as canonical ids. A row like `layer-kind-*`, which bundles several glyphs, counts each glyph it asks to
be drawn (shown in the "glyphs to draw" column). Rows that say "= other-id" or "Keep CSS / out of scope" count as
**0** new drawings.

| Group | Rows | New glyphs to draw |
|---|---|---|
| 2.1 Navigation & tab bar | 12 | 11 |
| 2.2 Top bar | 9 | 9 |
| 2.3 Playback & playlist | 15 | 14 (item-include stays CSS) |
| 2.4 Library, create & app actions | 36 | 46 (incl. 9 layer kinds, 4 new effects, 2 AI-model glyphs, flow group) |
| 2.5 Settings sections | 27 | 22 |
| 2.6 Display, TV sheet & media | 7 | 8 (3 looks) |
| 2.7 Connection & device | 7 | 4 (+ optional LED/latency state set) |
| 2.8 Phone controller | 23 | 22 (incl. 4 face-button states, start + select) |
| 2.9 Casino actions | 31 | 52 (incl. 19 game moves, 6 housie claims) |
| 2.10 Casino games & glyphs | 28 | 29 |
| 2.11 TV view & remote | 10 | 12 |
| 2.12 Themes | 4 | 3 |
| 2.13 Status & feedback | 11 | 5 |
| 2.14 Fruit fly | 8 | 10 |
| 2.15 App catalogue | 117 | 117 (one per app, de-duplicated so every app is distinct) |
| 2.16 Categories | 12 | 7 |
| 2.17 Presets | 13 | 5 |
| 2.18 Android & brand artwork | 11 | 10 (separate commission) |
| 2.19 Misc | 8 | 2 core + 35 optional (8 AI prompt chips, 27 notice icons) |
| **Grand total** | **389 rows** | **378 core UI glyphs + 10 brand artworks + 35 optional** |

Plus variants: `-filled` for about 175 icons (all apps, categories, presets, tab bar and toggles), `-off` for 6
(panel-power, visibility, sound, bluetooth, fly-roam, theme), and `-dark` / `-light` for the TV theme preview.

Priority order for the commission:
1. §2.1–2.4 and 2.13 (the studio chrome, about 90 glyphs).
2. §2.15–2.17 (the catalogue, 130).
3. Casino (§2.9–2.10).
4. Phones, TV and fly.
5. Optional sets.

---

## 4. Known issues and uncertainties

1. **Housie shows a square today.** `casino_housie` declares `icon = "grid"`, which is not in lucide's `icons` map, so
   `Icon.tsx` falls back to `Square`. This was found from lucide's export list and not checked on screen.
2. **Seven apps declare no icon** and render the default `square`: raycaster, boids, brain, focuspet, sand, synthwave,
   wireframe.
3. **Duplicate app glyphs today** (the brief gives each app its own):
   - spade ×4 (andarbahar, baccarat, holdem, teenpatti)
   - orbit ×3 (asteroidflyby, asteroids, planets)
   - sparkles ×3 (aurora, pokedex, ambient)
   - activity, bot, circle-dot, earth, gamepad-2, hourglass, infinity, radio, rocket, trending-up, wind ×2 each
4. **App count is 117, not 116.** The parser found 117 `@register` apps. Two are hidden (eyebreak, onair), so 115
   appear in the library.
5. **Two category icon maps.** The launcher (`L/Launcher.tsx`) maps categories to Clock/Zap/Music/Palette/Sparkles/
   Workflow/PawPrint/Gamepad2/Dices/Monitor; the studio uses clock-3/activity/image/palette/sparkles/target/paw-print/
   gamepad-2/dices/cpu. The pack should unify both on `cat-*`.
6. **Wrong or accidental glyphs.**
   - Launcher "Reconnect the panel" uses Wifi, but the link is Bluetooth; use `reconnect`.
   - Launcher autostart/quit rows fall back to Sparkles.
   - Launcher fly and fly-handback share Bug.
   - send-message and show-text share Send.
   - open-studio and grid view share LayoutGrid.
7. **`restart` vs `reset`.** Both are `rotate-ccw` today. I split them by meaning (start the game over vs back to
   defaults). Confirm you want two drawings.
8. **Casino win card copy says "tap ⓘ to verify", but no ⓘ control exists.** Verifying is behind the profile/fairness
   button. Either add an `info`/`fairness` button or change the copy.
9. **Text-only controls proposed as icon candidates** (decide if you want them):
   - Casino Clear / Rebet / SPIN and all 19 game moves
   - Housie claims
   - TV quality options and veil error states
   - Host-landing buttons ("Connect panel", "Open studio", "Use it here", "Find that tab")
   - Fly full-screen view/layout segments
   - Engine-offline empty state
10. **Not verified against the Python handlers:** the effect of phone `done`, `clear` and `rebet` comes from the
    client code and in-page tour text. Rock-paper-scissors and Penguin have their own demo/restart code paths that may
    behave slightly differently from the shared handler.
11. **Brand-risky subjects** are marked **(generic!)**. Pay particular attention to:
    - pokedex, tetris, digworld/gameserver, agent, maze, invaders, dino, flappy, cycles, fourup, loops, playercard,
      racecountdown, chess, github, hassentity, obs, mediaserver, nowplaying, btcnet
    - the gamepad face buttons
12. **Out of scope** (keep as pixel or code art): slot reel symbols, the 8 casino/controller avatars, RPS pixel hands,
    countdown rings, LED status dots, real QR codes, the LED wordmark, chip-stack loader, and the boot-show art
    (`C/boot/*`, `C/NeonMark.tsx`, `C/CoinDrop.tsx`).

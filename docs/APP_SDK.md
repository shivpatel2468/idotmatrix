# App SDK

Everything on the panel is an **App**: one Python class. The studio form, the MCP `list_apps` output, the
playlist and the tests all discover it automatically. There is no frontend work.

## Hello, panel

```python
# plugins/hello.py   (or src/deskdot/apps/hello.py + import it in apps/__init__.py)
from pydantic import Field
from deskdot.engine import App, AppSettings, Choice, Color, register
from deskdot.gfx import Frame, scale

class HelloSettings(AppSettings):
    name: str = Field("WORLD", max_length=8, title="Name")
    size: str = Choice("small", {"small": "Small", "tiny": "Tiny"})
    color: Color = Field("#00ff8c", title="Colour")

@register
class Hello(App):
    id = "hello"                      # stable, used in URLs and state.json
    name = "Hello"
    description = "Greets someone."
    icon = "hand"                     # any lucide.dev icon name
    category = "creative"             # time | data | media | creative | ambient | productivity | device
    Settings = HelloSettings
    fps = 1.0

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        f.text_center(8, "HELLO", scale(s.color, 0.6))
        f.text_center(17, s.name, s.color, font=s.size)
```

Restart the engine (`uv run deskdot serve --sim`) — **Hello** appears in the Library with a working form.
Preview without a panel: `uv run deskdot preview hello --settings '{"name":"ADA"}' --out hello.png`.
A complete example lives in `plugins/_example_countdown.py`.

## The class, field by field

| Attribute | Meaning |
| --- | --- |
| `id`, `name`, `description`, `icon`, `category` | identity and library presentation (all required for tests) |
| `Settings` | a subclass of `AppSettings` (pydantic). Unknown keys are ignored, so renames are safe |
| `fps` | stream render rate. Frames are deduped, so a static screen costs nothing |
| `uses` | provider names acquired while the app is visible, e.g. `("weather",)` |
| `actions` | `Action(id, label, icon)` buttons the studio shows; handled in `async def action()` |
| `clip_seconds`, `clip_fps` | loop length and rate when baked as a clip |
| `clip_colors` | palette cap for the baked GIF (gradients look fine at 48; the engine also enforces a 40 KB budget) |
| `hidden` | hide from the library (internal apps) |

## Settings → UI mapping

| Python | Studio control |
| --- | --- |
| `Choice("a", {"a": "Label A", "b": "Label B"})` | segmented (≤ 4) or select; value validated |
| `bool` | toggle |
| `int`/`float` with `Field(ge=…, le=…)` | fader |
| `Color` | colour picker with LED palette swatches |
| `str` with `json_schema_extra={"format": "media"}` | media library picker |
| `str` (`max_length > 80` → textarea) | text input |
| `date`, other types | text input (validated by pydantic) |

Always set `title=` (and `description=` for anything non-obvious). Bounds are required for faders.

More UI hints:

| Python | Studio |
| --- | --- |
| `Field(..., json_schema_extra={"group": "Exposure"})` / `Choice(..., group="Framing")` | collapsible section (first group open) |
| `datetime` / `date` fields | native date-time / date pickers |
| `list[...]` with `json_schema_extra={"format": "layers"}` | hidden in the form (edited on the preview, like Text Studio) |
| subclass `deskdot.gfx.adjust.ImageControls` | the full exposure / colour / framing panel for camera-like apps |

## Lifecycle

```
__init__(ctx, settings)   once per slot (manual app, or each playlist item with overrides)
on_start()                became visible        ← register provider wants here (markets.want("BTC"))
render(f, t)              every tick; t = seconds since on_start
on_settings()             settings replaced (live edits); reset derived state
on_stop()                 hidden
```

## Output kinds — pick the cheapest that works

| `kind()` | When | Cost on the link |
| --- | --- | --- |
| `"stream"` (default) | content depends on live data or wall time | one PNG per *changed* frame, capped at `max_fps` |
| `"clip"` | a deterministic loop (animation, scrolling text, uploaded GIF) | one GIF upload per `clip_key()` change; then zero |
| `"native"` | a firmware feature does it | one command per settings change |

`kind()` may depend on settings (Text scrolls → clip; fits → stream). For clips, either rely on the default
`clip_frames()` (samples `render()` at `clip_fps` over `clip_seconds`) or return a `Clip(frames, durations_ms)`.
Override `clip_key()` if the loop depends on more than settings (e.g. provider data).

## Reading data

```python
d = self.ctx.provider("weather").value          # None until the first fetch
err = self.ctx.provider("weather").error        # last failure message or None
if d is None:
    return (offline if err else loading)(f, ...)  # from deskdot.apps._kit
```

Built-in providers: `system`, `weather`, `markets` (`.want(*symbols)`), `stocks` (`.want(symbols, range_)`, Yahoo),
`sports` (`.want(*leagues)`, `.want_table(*leagues)`, 27 ESPN leagues), `media` (`.position`, `.art`, `.art_image`,
`.palette`, `.source_label`, `await .control("next")`; Windows SMTC or macOS AppleScript/nowplaying-cli), `lyrics`
(`.get(title, artist, album=, duration=)` → `Lyrics | None`, LRCLIB first, word timing via `words_at`), `window`
(foreground app + icon), `screen`, `camera`, `audio` (bands, beat, bpm; system loopback or mic), `github`,
`notifications` (OS toasts → `os_notification` events), `flights` (ADS-B around the location).
Public-API providers (see [PUBLIC_APIS.md](PUBLIC_APIS.md)): `quakes`, `rainradar`, `airquality`, `holidays`, `space`
(`.want(parts, launch_filter)`), `iss`, `sky`, `daily`, `trivia`, `headlines`, `currency`, `photos`, `pokedex`,
`avatars`, `chess`, `gamedeals`.
Platform providers (Settings → Integrations; see [API.md](API.md#integrations-on-air-eye-break-ntfy-home-assistant)):
`onair` (Windows camera/mic usage from the ConsentStore registry → `{"in_use": {"webcam": [...], "microphone": [...]}}`;
filter with `providers.onair.filter_apps`), `idle` (Windows `idle_s` since the last input and `fullscreen`),
`ntfy` (streams ntfy topics, emits `ntfy` events), `homeassistant` (`.want(entity, poll_s, history_h)` → `value[entity]`
= `{state, value, unit, name, device_class, history}`; config and token from the store, never log it) and `custom`
(the validated registry of pushed custom apps; `.value[name]` is the AWTRIX-style body). Location-aware providers call `await self.hub.location()`; web text headed for the
panel goes through `providers.daily.clean_text` (fonts are ASCII-only); tiny world maps come from `gfx.worldmap`.

Characters for pets and games live in `deskdot.gfx.characters`: `draw_character(f, char_id, anim, t, x, y, *,
colors=, flip=, scale=1|2, beat=, accessory=)` draws one of 53 original 16×16 rigs (see `CHARACTERS`, `GROUPS`,
`ANIMS`, `ACCESSORIES`). Self-playing games subclass `apps.games_core.GameApp` (fixed-step sim, AI/human hand-over,
best score, themes).

Need a new source? Subclass `Provider`, implement `async def fetch()`, set `interval`, add it to
`providers.ALL`. Use `self.hub.http` (shared `httpx.AsyncClient`), never `requests`/`urllib`.
High-rate sources (audio, screen, camera) override `announce()` to return `False` so they don't flood the studio
with state updates. Discrete happenings (a goal, a game start) go through `self.hub.emit(event, data)`; the engine
turns them into overlays (see `Engine._on_event`).

Engine-level features that are **not** apps: status indicators and the On-Air badge / glow are *persistent overlays*
(`engine/persistent.py`, drawn after the app, the notice and the transition); On Air (full screen) and the eye break are
*takeovers* — hidden apps (`onair`, `eyebreak`) the engine selects instead of the playlist while their condition holds.
The icon vocabulary shared by notices, custom apps and Home Assistant lives in `gfx/icons.py` (`ICONS`, `draw_icon`).

Also available: `window` (foreground app, `.icon(exe)` → 32×32 RGBA), `screen`/`camera` (32×32 frames via
`.configure(...)`), `audio` (32 spectrum bands), `github` (`.want(user)`).

## Context (`self.ctx`)

| Member | Purpose |
| --- | --- |
| `provider(name)` | a data provider |
| `data` / `save()` | persisted per-app JSON scratch space (e.g. canvas pixels) |
| `invalidate()` | re-render now and re-bake the clip |
| `notify(title=, message=, icon=, color=, style=, duration=)` | queue an overlay |
| `library` | the media library (uploads) |

## Scheduling hooks (playlist)

| Hook | Effect |
| --- | --- |
| `relevant() -> bool` | `False` = skip this item when rotating (no live games, no music) |
| `watches_focus() -> bool` | keep providers alive while in the playlist so focus can be detected |
| `wants_focus() -> bool` | `True` = take over the playlist now (music started, favourite team live) |
| `status() -> dict` | small JSON shown next to the preview and to agents (`panel_status`) |

## Drawing toolbox (`deskdot.gfx`)

`Frame`: `clear, set, get, rect, hline, vline, line, polyline, circle, gradient_v, blend, dim, blit, sprite,
text, text_center, text_right, bar, sparkline`. Fonts: `measure, wrap, fit, draw_marquee`.
Colour: `PALETTE, to_rgb, hsv, mix, scale, calibrate`. Sprites: `Sprite.parse(rows, palette)`.
Kit (`deskdot.apps._kit`): `ring` (edge progress), `loading`, `offline`, `compact_number`, `bytes_rate`.

## Games (`apps.games_core.GameApp`)

Games subclass `GameApp` and *declare* how they can be played; the framework builds the rest.

```python
class Pong(GameApp):
    max_players = 4                                  # seats: seat 1 = host, 2–4 = phones (QR lobby) or local pads
    controls = ("joystick", "dpad", "gamepad")       # recommended controllers, best first
    modes = (Mode("solo", "Solo"), Mode("duel", "Versus", 2, 4, "versus"))   # teams: solo|coop|ffa|versus
    maps = {"classic": "Classic", "block": "Centre block"}
    game_themes = {"arcade": Theme(...)}             # genre themes on top of the shared THEMES
```

- **Settings**: `mode`, `map`, `players` and the genre `theme` are added to the game's Settings automatically, next to
  `effects` (full / calm / minimal), `intro_outro` and `attract`.
- **Flow** (`self.flow`): attract (the AI plays; arrows take over instantly) → **B** = home menu (mode, players, map,
  theme, START) → teams (FIFA-style side select for versus modes: ←/→ picks a side, A = ready, AI fills the smaller
  side) → intro (3-2-1 GO) → play → outro (A = rematch, B = menu). If nobody touches the menu for 45 s, it falls back to attract.
- **In game code**: `reset()` builds the match from `self.play_mode`, `self.map_id`, `self.n_players` and `self.roster`
  (an empty roster means attract/classic solo). Draw players with `self.colour_of(seat)`. The AI drives every seat where
  `not self.is_human(seat)`. End a match with `self.result(winner_seat=…, winner_team=…, scores=…)`, and call
  `self.damage()` when a human takes a hit (red fading edge flash + shake).
- **Studio / agents**: the `menu` and `start {mode, players, map, theme}` actions; `status()` reports `flow`, `mode`,
  `map`, `roster` and `outcome`.
- **Themes must not camouflage gameplay**: keep backgrounds dark and desaturated, with a big luminance gap to every
  gameplay colour.

## Rules (enforced by review and `tests/test_apps.py`)

1. `render()` is pure and fast: no I/O, no sleeping, no randomness without a fixed seed in clips.
2. Every `Choice` option must render without provider data.
3. Follow [DISPLAY_DESIGN.md](DISPLAY_DESIGN.md): margins, type scale, palette, states.
4. Don't hold references to other apps or the engine; use `ctx`.
5. Keep per-frame allocations small; precompute sprites and LUTs in `__init__`/`on_settings`.

## Shipping a built-in app

1. `src/deskdot/apps/<id>.py`, import it in `apps/__init__.py` (`BUILTIN`).
2. `uv run pytest -q` — the parametrised app tests pick it up.
3. Add it to the gallery render (`docs/assets/apps.png`) and the app list in `docs/VISION.md`.
4. If agents should drive it specially, add an MCP tool (usually `show_app` is enough).

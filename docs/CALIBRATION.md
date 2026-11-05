# Colour calibration & the motion lab

Two Settings → Display blocks help the panel and the studio preview match and move well. Code:
`src/deskdot/gfx/calib.py` (maths), `gfx/calib_presets.py` (presets, quick match, motion presets, auto-tune),
`gfx/testvideo.py` (animated test videos, motion tests, the engine's test cards), `calibration_api.py` (HTTP),
`web/src/lib/calib.ts` (the same maths in the studio) and `web/src/components/calibration/` (UI).
Endpoints are in [API.md](API.md).

## Where calibration applies (unchanged architecture)

- **Panel calibration** (`PanelCalibration`) corrects *this panel's* deviations. The engine applies it to every
  frame on its way to the LEDs (`Engine._panel`) and to baked clips. Design colours are authored for LEDs and only
  pass through this panel correction.
- **Photo calibration** (`color.calibrate()`) is separate: photos and album art go through it once, at import
  (rule 9). Nothing here changes that.
- **Studio preview**: `lib/look.ts` *colour match* (`led` default, `all`, `off`) decides whether `LedPanel` shows
  frames through the same calibration (computed locally by `lib/calib.ts`), i.e. what the panel is sent.
  Golden LUT values in `tests/test_calibration.py` and `lib/calib.ts` keep the two ports identical.

## The maths

Per channel, in order: saturation (around the pixel mean) → contrast S-curve `x^k / (x^k + (1-x)^k)` (0 and 255
never move) → gamma × per-channel gamma → gain (white balance × colour temperature × peak level) → shadow lift →
black cutoff. Colour temperature uses a blackbody fit normalised to 6500 K (max gain 1: never brightens).
Optional ordered (Bayer 4×4) dithering is static per pixel and leaves fully-off and fully-on channels alone, so
1-bit text stays crisp. Every field of `PanelCalibration` defaults to "no change" (the identity); stored state is
loaded tolerantly (`PanelCalibration.load` drops invalid keys and fills missing ones with "no change", rule 15).

## The default

A fresh install does **not** start uncorrected: when nothing is stored, the engine starts on the house default,
`DEFAULT_CALIBRATION` in `gfx/calib.py` (preset id `deskdot`, "DeskDot (tuned)", first in the preset list).
The owner tuned it by eye on their own panel (2026-11-04, read from their phone engine) and asked for it to be the
starting point of every build:

| red | green | blue | gamma | per-channel gamma | black cutoff | lift | saturation | contrast | temperature | peak | dither |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.029 | 1.025 | 1.035 | 2.225 | 1 / 1 / 1 | 0 | 14 | 1.4 | 1.0 | 6500 K | 1.0 | off |

Why these: the high gamma gives LED mid-tones the depth they have on a screen, the shadow lift keeps the faint
levels that gamma would crush visible, and the extra saturation brings back colour the LEDs wash out. The RGB gains
are *that* panel's white balance; panels vary, so for another panel they are a good start, not a measurement — the
guided match refines them.

- Every build runs the same Python engine (Windows / Mac desktop, the Android phone app, a watch hosting the engine,
  the browser `/app` via Pyodide), so `Engine.__init__` → `calib.initial_calibration()` is the one place it applies.
  The default is not written to `state.json`; it is simply what "nothing stored" means.
- A stored calibration (anyone's own tuning, a preset, the wizard, or "Panel native") is kept exactly as stored and
  is never replaced by the default, even if it is old (missing keys still mean "no change").
- The studio's **Reset to default** (Colour calibration home), Advanced's **Default** button and per-knob resets, and
  the wizard's **Start fresh** all go to these values (`DEFAULT_CALIB` in `web/src/lib/calib.ts`; a test pins it to
  the Python values). **Panel native** under Presets › Standards is still the "off / no correction" choice.
- The preset follows the usual rule: applied with *keep my panel's white balance*, your current RGB gains stay;
  without it (or from scratch) you get the owner's gains too.

## Guided match (A/B, converging)

While a test runs the panel shows the video through two candidates — **A** in the left half, **B** in the right,
the same content in both halves — and the studio preview shows the *uncorrected reference*. The user picks the half
closer to the screen; each pick moves to that candidate and halves the step (an eye-test bisection), "look the same"
stops early. Steps: gamma (grey ramp sweep) · black level / lift (pulsing near-black) · blue, green, red gains
(neutral greys, skin) · saturation (moving colour bars). Gains are normalised so the brightest channel drives fully.
A final before/after **wipe** (draggable split) compares old and new on several videos, then saves.

Test videos change at 4 fps; every frame stays within two BLE packets (tests pin it).

## Presets

`deskdot` (DeskDot (tuned), the default above), `claude` (Quick match from 3 questions, Accurate, Comfortable night, Punchy games, Photo & art, Low-glare desk),
`inspired` (Sony-style Natural / Cinema, LG-OLED-style Deep black, Samsung-style Vivid, MacBook-style P3 warm,
Dell/BenQ-style sRGB office) and `standard` (sRGB D65, Rec.709 cinema, Warm night 3400 K, Panel native).
The "-style" presets are **approximations, not official values**, unaffiliated, with no logos. A preset sets the
picture style and keeps the measured RGB gains unless asked not to. "Try" plays a wipe on the panel without saving
(saving re-bakes clips, and frequent GIF uploads stall the panel — HARDWARE_PROTOCOL.md #16).

## Motion lab

Tests: pursuit UFO, bouncing ball, scrolling text, sweeping bar, gradient pan (link stress), live data (smoothing),
app transitions. Two configs share the panel stacked (A top, B bottom) or alternating every 4 s. Guided:
frame-rate bisection over 4–12 fps (same → the lighter rate), a transition tournament (cut/fade/push/wipe), and
temporal smoothing. Presets: Smoothest, Balanced, Battery/BLE friendly, Calm streams, and Claude auto-tune (streams
the pan test at 12 fps for a few seconds and caps the stream a little above the delivered rate).

Fixed, never knobs (rule 13): one un-acked frame in flight, GIF ≤ 40 KB, baked loops ≤ 10 fps (test clips ≤ 96
frames, one upload per 20 s), and packet spacing ≥ 18 ms in every preset/test (30 ms is the first verified value; the
pre-existing manual slider now starts at 18 and warns if a stored value is lower). Streams in tests stay ≤ 12 fps.
"Temporal smoothing" (`display.smoothing`, default 0) blends streamed frames with the previous one and snaps when
within a few levels, so still screens settle exactly.

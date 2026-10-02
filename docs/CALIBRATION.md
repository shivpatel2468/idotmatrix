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
1-bit text stays crisp. Every field defaults to "no change"; stored state is loaded tolerantly
(`PanelCalibration.load` drops invalid keys, rule 15).

## Guided match (A/B, converging)

While a test runs the panel shows the video through two candidates — **A** in the left half, **B** in the right,
the same content in both halves — and the studio preview shows the *uncorrected reference*. The user picks the half
closer to the screen; each pick moves to that candidate and halves the step (an eye-test bisection), "look the same"
stops early. Steps: gamma (grey ramp sweep) · black level / lift (pulsing near-black) · blue, green, red gains
(neutral greys, skin) · saturation (moving colour bars). Gains are normalised so the brightest channel drives fully.
A final before/after **wipe** (draggable split) compares old and new on several videos, then saves.

Test videos change at 4 fps; every frame stays within two BLE packets (tests pin it).

## Presets

`claude` (Quick match from 3 questions, Accurate, Comfortable night, Punchy games, Photo & art, Low-glare desk),
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

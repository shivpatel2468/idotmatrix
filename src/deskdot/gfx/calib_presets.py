"""Picture-style presets for the panel calibration, and the motion presets (docs/CALIBRATION.md).

The "inspired by" styles are *approximations* of how well-known displays tend to look out of the box
(natural, cinema, deep blacks, vivid, warm...), translated to what a 32x32 LED panel can do. They are not
official values, not affiliated with or endorsed by those companies, and carry no logos.

A preset sets the *style* fields (gamma, black level, lift, saturation, contrast, colour temperature, peak
level, dithering). The RGB gains are the panel's own white balance (measured by the wizard), so applying a
preset keeps them by default; `keep_balance=False` swaps in the preset's gains instead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .calib import PanelCalibration, apply
from .color import to_hex
from .frame import Frame

Group = Literal["claude", "inspired", "standard"]

#: The colours shown in each preset's swatch strip: skin, sky, foliage, ember, mid grey, dark grey, white.
SWATCH_COLOURS: list[tuple[int, int, int]] = [
    (226, 172, 125),
    (70, 150, 235),
    (60, 170, 70),
    (255, 72, 24),
    (128, 128, 128),
    (40, 40, 48),
    (255, 255, 255),
]

BALANCE_FIELDS = ("red", "green", "blue")


class CalibPreset(BaseModel):
    id: str
    name: str
    group: Group
    blurb: str
    values: dict[str, Any] = Field(default_factory=dict)

    def calibration(
        self, current: PanelCalibration | None = None, keep_balance: bool = True
    ) -> PanelCalibration:
        """The full calibration for this preset; with `keep_balance` the current RGB gains carry over."""
        data = PanelCalibration().model_dump()
        data.update(self.values)
        if keep_balance and current is not None:
            for k in BALANCE_FIELDS:
                data[k] = getattr(current, k)
        data["preset"] = self.id
        return PanelCalibration.model_validate(data)

    def swatches(self) -> list[str]:
        f = Frame()
        for i, c in enumerate(SWATCH_COLOURS):
            f.set(i, 0, c)
        out = apply(f.px, self.calibration())
        return [to_hex(tuple(int(v) for v in out[0, i])) for i in range(len(SWATCH_COLOURS))]


def _p(id: str, name: str, group: Group, blurb: str, **values: Any) -> CalibPreset:
    return CalibPreset(id=id, name=name, group=group, blurb=blurb, values=values)


PRESETS: list[CalibPreset] = [
    # ---- Claude presets: tuned to land a good result fast on these LEDs
    _p(
        "claude_quick",
        "Quick match",
        "claude",
        "Three questions about your room, use and panel tint — done.",
        gamma=1.6,
        lift=3,
        temperature=6500,
    ),
    _p(
        "claude_accurate",
        "Accurate",
        "claude",
        "Even grey steps, neutral white, true-to-screen colour.",
        gamma=1.7,
        lift=3,
        gamma_blue=1.05,
        temperature=6500,
    ),
    _p(
        "claude_night",
        "Comfortable night",
        "claude",
        "Warm, soft and dim-friendly for late evenings.",
        gamma=1.7,
        lift=1,
        saturation=0.9,
        contrast=0.92,
        temperature=3600,
        level=0.85,
    ),
    _p(
        "claude_games",
        "Punchy games",
        "claude",
        "Bright mid-tones and bold colour that pops across the room.",
        gamma=1.35,
        lift=4,
        saturation=1.35,
        contrast=1.15,
        temperature=7000,
    ),
    _p(
        "claude_photo",
        "Photo & art",
        "claude",
        "Gentle contrast, natural skin, dithered smooth gradients.",
        gamma=1.75,
        lift=3,
        saturation=1.05,
        contrast=1.02,
        temperature=6200,
        dither=True,
    ),
    _p(
        "claude_lowglare",
        "Low-glare desk",
        "claude",
        "Lower peak and softer contrast for a panel at arm's length.",
        gamma=1.9,
        black_level=3,
        saturation=0.92,
        contrast=0.9,
        temperature=5600,
        level=0.8,
    ),
    # ---- inspired by well-known displays (approximations, not official values)
    _p(
        "sony_natural",
        "Sony-style Natural",
        "inspired",
        "Inspired by a natural TV picture mode: calm, true colour.",
        gamma=1.6,
        lift=2,
        temperature=6300,
    ),
    _p(
        "sony_cinema",
        "Sony-style Cinema",
        "inspired",
        "Inspired by a cinema picture mode: warmer, richer shadows.",
        gamma=1.8,
        black_level=2,
        saturation=0.95,
        contrast=1.08,
        temperature=5800,
    ),
    _p(
        "lg_oled",
        "LG-OLED-style Deep black",
        "inspired",
        "Inspired by OLED TVs: inky blacks and punchy contrast.",
        gamma=1.7,
        black_level=6,
        saturation=1.05,
        contrast=1.15,
    ),
    _p(
        "samsung_vivid",
        "Samsung-style Vivid",
        "inspired",
        "Inspired by a showroom vivid mode: cool, bright, saturated.",
        gamma=1.4,
        lift=3,
        saturation=1.3,
        contrast=1.12,
        temperature=8500,
    ),
    _p(
        "apple_p3",
        "MacBook-style P3 warm",
        "inspired",
        "Inspired by wide-gamut laptop screens with a warm ambient tone.",
        gamma=1.6,
        lift=2,
        saturation=1.12,
        contrast=1.04,
        temperature=5900,
    ),
    _p(
        "dell_srgb",
        "Dell/BenQ-style sRGB office",
        "inspired",
        "Inspired by office monitors in sRGB mode: plain and even.",
        gamma=1.6,
        lift=2,
        saturation=0.95,
        temperature=6500,
    ),
    # ---- standards (approximated for LEDs)
    _p(
        "std_srgb",
        "sRGB · D65",
        "standard",
        "The web standard: D65 white, sRGB-like tone curve on LEDs.",
        gamma=1.6,
        lift=2,
        temperature=6500,
    ),
    _p(
        "std_rec709",
        "Rec.709 cinema",
        "standard",
        "Video mastering look: slightly darker mid-tones, D65 white.",
        gamma=1.8,
        black_level=2,
        contrast=1.05,
        temperature=6500,
    ),
    _p(
        "std_warm",
        "Warm night · 3400 K",
        "standard",
        "Incandescent-warm white for evenings.",
        gamma=1.6,
        saturation=0.9,
        contrast=0.95,
        temperature=3400,
    ),
    _p("native", "Panel native", "standard", "No correction at all: exactly what the LEDs do on their own."),
]
PRESET_IDS = {p.id for p in PRESETS}


def get_preset(pid: str) -> CalibPreset | None:
    return next((p for p in PRESETS if p.id == pid), None)


def preset_listing() -> list[dict[str, Any]]:
    return [{**p.model_dump(), "swatches": p.swatches()} for p in PRESETS]


Room = Literal["bright", "dim", "dark"]
Use = Literal["mixed", "text", "photos", "games"]
Tint = Literal["neutral", "blue", "yellow", "green", "pink"]


def quick_match(
    room: Room, use: Use, tint: Tint, current: PanelCalibration | None = None
) -> PanelCalibration:
    """ "Quick match": a good calibration from three answers (no test cards needed).

    Starts from "Accurate", then: a darker room wants a warmer, softer, lower peak; games want punch, photos
    want smooth gradients, text wants crisp shadows; the panel's visible tint is cancelled in the RGB gains
    (starting from the current gains, so an earlier wizard result is refined, not thrown away).
    """
    base = get_preset("claude_accurate")
    assert base is not None
    c = base.calibration(current, keep_balance=current is not None).model_dump()
    if room == "dim":
        c.update(temperature=5800, contrast=0.97, level=0.92)
    elif room == "dark":
        c.update(temperature=4800, contrast=0.92, level=0.8, lift=1)
    if use == "games":
        c.update(gamma=1.45, saturation=1.25, contrast=c["contrast"] * 1.1)
    elif use == "photos":
        c.update(saturation=1.05, dither=True, gamma=1.75)
    elif use == "text":
        c.update(lift=0, black_level=2, contrast=c["contrast"] * 1.05)
    r, g, b = c["red"], c["green"], c["blue"]
    if tint == "blue":
        b *= 0.86
        g *= 0.95
    elif tint == "yellow":
        r *= 0.93
        g *= 0.95
    elif tint == "green":
        g *= 0.88
    elif tint == "pink":
        r *= 0.92
        b *= 0.92
    top = max(r, g, b)
    if top > 1.0:  # keep the brightest channel at full drive at most
        r, g, b = r / top, g / top, b / top
    c.update(red=round(max(0.3, r), 3), green=round(max(0.3, g), 3), blue=round(max(0.3, b), 3))
    c["contrast"] = round(max(0.6, min(1.6, c["contrast"])), 3)
    c["preset"] = "claude_quick"
    return PanelCalibration.model_validate(c)


# =================================================================== motion presets
class MotionPreset(BaseModel):
    id: str
    name: str
    blurb: str
    max_fps: float = Field(ge=4, le=12)
    packet_gap_ms: float = Field(ge=18, le=40)
    transition: Literal["cut", "push", "fade", "wipe"]
    smoothing: float = Field(0.0, ge=0, le=0.6)


#: Packet spacing never goes below this in presets or tests: the value the shipped default and the camera
#: HIL runs use (docs/CAMERA_HIL_TESTING.md); 30 ms is the first hardware-verified value (HARDWARE_PROTOCOL #1).
MIN_SAFE_PACKET_GAP_MS = 18.0

MOTION_PRESETS: list[MotionPreset] = [
    MotionPreset(
        id="smoothest",
        name="Smoothest",
        blurb="Pushes the link to its verified ceiling; fades between apps.",
        max_fps=12,
        packet_gap_ms=18,
        transition="fade",
    ),
    MotionPreset(
        id="balanced",
        name="Balanced",
        blurb="The recommended default: quick, steady and glitch-free.",
        max_fps=10,
        packet_gap_ms=20,
        transition="cut",
    ),
    MotionPreset(
        id="ble_friendly",
        name="Battery / BLE friendly",
        blurb="Fewer frames and wider spacing for a busy "
        "or weak Bluetooth link; animations still play smoothly as native loops.",
        max_fps=6,
        packet_gap_ms=30,
        transition="cut",
    ),
    MotionPreset(
        id="calm",
        name="Calm streams",
        blurb="Balanced, plus smoothing that steadies jittery live data.",
        max_fps=10,
        packet_gap_ms=20,
        transition="fade",
        smoothing=0.35,
    ),
]


def get_motion_preset(pid: str) -> MotionPreset | None:
    return next((p for p in MOTION_PRESETS if p.id == pid), None)


def autotune(link_fps: float, frame_bytes: int) -> MotionPreset:
    """ "Claude: auto-tune": pick a stream cap from the frame rate the link actually delivered in a stress test.

    A cap a little above the measured rate keeps the pipeline full without piling up superseded frames; heavy
    (multi-packet) frames get a little more spacing. Never leaves the verified bounds.
    """
    fps = max(4.0, min(12.0, round(link_fps * 1.15)))
    gap = MIN_SAFE_PACKET_GAP_MS if frame_bytes <= 514 else 20.0
    if link_fps < 4:  # a struggling link: give each packet more room
        gap = 30.0
    return MotionPreset(
        id="auto",
        name="Claude: auto-tune",
        blurb=f"Measured {link_fps:.1f} frames/s on your link.",
        max_fps=fps,
        packet_gap_ms=gap,
        transition="cut" if fps < 9 else "fade",
    )

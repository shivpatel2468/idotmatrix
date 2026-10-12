"""Now Playing — album art, track info and karaoke-synced lyrics from Spotify, YouTube Music or any player.

Layouts (all 32×32, all render without media / art / lyrics):

========== ===================================================================================
karaoke    lyric rows in big type; the current line fills left→right word by word; rows scroll up
lyrics     the same stream, whole current line lit (no fill); good for plain / estimated lyrics
lyrics_art lyrics over the album art, blurred and darkened, with a 1 px shadow
cover      full-bleed album art
cover_text art with a darkened caption strip (title · artist marquee) and progress
live_art   full-bleed art with a slow Ken Burns pan/zoom and a breathing (or beat) brightness
vinyl      a spinning record with the art as its label and a tonearm that tracks the song
split      art tile + equaliser + time, title and artist below
minimal    source · title · artist · progress · time
palette    an ambient gradient flowing between the art's colours, title on top
spectrum   album-coloured spectrum bars (live audio if the audio provider has data, else synthetic)
wordpop    one lyric word at a time, as big as it fits, popping in on its beat
big_title  the song name huge (2× bitmap type), artist and time below
cassette   a tape with the title on its label; the reels turn and the tape packs trade size
vu         twin analogue VU needles (or LED ladders) driven by system audio, title below
cd         the cover printed on a spinning CD with a clear hub and a rainbow sheen
radio      a backlit FM / AM dial; the needle sweeps to a new station on every song
mosaic     the cover as posterised tiles with grout, revealed tile by tile, one tile glinting
waveform   a scrolling waveform of the music (system audio, else synthetic)
========== ===================================================================================

Around every layout: song-change transitions (cut / slide / dissolve / art zoom), auto-rotation through a layout
set, pause behaviour (layout's own / dim / pause badge / freeze / idle), art styles (smooth / pixelated /
posterised / dithered) and idle screens (NO MUSIC, clock, last cover, calm waves, recent covers, silence).

Everything per-track (scaled art, blurs, palettes, lyric row layouts) is computed once per art / lyrics
object; `render()` only composes numpy arrays and bitmap text.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, ClassVar

import numpy as np
from PIL import Image, ImageFilter
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, calibrate, mix, scale, to_rgb
from ..gfx.font import FONTS, draw_marquee, fit, measure
from ..platforms import DESKTOP
from ..providers.lyrics import normalize_track
from ..providers.media import decode_art, extract_palette
from . import _npdraw as kit
from ._kit import loading, offline, unsupported

RGB = tuple[int, int, int]
LYRIC_LAYOUTS = ("karaoke", "lyrics", "lyrics_art", "wordpop")
FAST_LAYOUTS = (
    "karaoke", "lyrics", "lyrics_art", "live_art", "vinyl", "palette", "spectrum_art",
    "wordpop", "big_title", "cassette", "vu", "cd", "radio", "mosaic", "waveform",
)  # fmt: skip
AUDIO_LAYOUTS = ("spectrum_art", "vu", "waveform")  # acquire system audio while one of these can show
ROTATE_SETS: dict[str, tuple[str, ...]] = {
    "art": ("cover", "live_art", "vinyl", "cd", "mosaic"),
    "lyrics": ("karaoke", "lyrics_art", "wordpop"),
    "retro": ("cassette", "vinyl", "vu", "radio"),
    "info": ("cover_text", "split", "big_title", "minimal"),
    "mix": ("cover_text", "karaoke", "vinyl", "cassette", "cd", "big_title", "mosaic", "spectrum_art"),
}
TRANSITION_S = 0.7  # song-change transition length
ART_REVEAL_S = 1.2  # mosaic tiles appearing on a new cover
RADIO_SWEEP_S = 1.4  # dial needle travelling to the new station
PAUSE_IDLE_S = 20.0  # "switch to idle" pause behaviour waits this long
PAGE_S = 2.4  # "Pages of words": each page of a long title stays this long
SPACING = {"tight": -1, "normal": 0, "loose": 1}  # lyric line pitch adjustment (px)
BADGE_LAYOUTS = ("cover", "live_art", "palette", "cd", "mosaic")  # paused: a big pause sign (Layout's own)
TRACK = (22, 22, 32)
SCROLL_S = 0.4  # row scroll animation (4 frames at 10 fps: 0.28 s was a 2-3 frame lurch)
READABLE = 200  # art-derived UI colours are lifted until their brightest channel reaches this
FLOOR = 64  # dim lyric rows keep at least this much in their brightest channel (gamma 1.5 eats less)
FALL = 1.4  # spectrum bars fall at most this much of their height per second (smooth decay)

# pixel-centre grids, shared by the procedural layouts
_Y, _X = np.mgrid[0:32, 0:32].astype(np.float32) + 0.5


# ------------------------------------------------------------------------------------------------ text
_SUBST = {
    "’": "'", "‘": "'", "`": "'", "´": "'", "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "—": "-", "–": "-", "‐": "-", "…": "...", "×": "X", "¿": "", "¡": "", "ß": "SS", "æ": "AE", "ø": "O",
    "œ": "OE", "đ": "D", "ł": "L", "&": "+",
}  # fmt: skip


@lru_cache(maxsize=4096)
def clean(text: str, font: str = "tiny") -> str:
    """Text as the bitmap font can draw it: accents stripped, quotes straightened, unknown glyphs dropped."""
    fnt = FONTS[font]
    out: list[str] = []
    for ch in unicodedata.normalize("NFKD", text or ""):
        if unicodedata.combining(ch):
            continue
        for c in _SUBST.get(ch, ch):
            c = c.upper() if fnt.upper else c
            if c in fnt.glyphs:
                out.append(c)
            elif c == '"' and "'" in fnt.glyphs:
                out.append("'")
            elif c == "+" and "&" in fnt.glyphs:
                out.append("&")
            elif c in ";" and "," in fnt.glyphs:
                out.append(",")
            elif c.isspace():
                out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


@lru_cache(maxsize=2048)
def text_mask(text: str, font: str) -> np.ndarray:
    """Boolean (height, width) bitmap of `text` in `font` (1 px letter spacing)."""
    fnt = FONTS[font]
    glyphs = [fnt.glyph(c) for c in text]
    if not glyphs:
        return np.zeros((fnt.height, 0), dtype=bool)
    w = sum(g.shape[1] for g in glyphs) + len(glyphs) - 1
    m = np.zeros((fnt.height, w), dtype=bool)
    x = 0
    for g in glyphs:
        m[:, x : x + g.shape[1]] = g
        x += g.shape[1] + 1
    m.setflags(write=False)
    return m


def paint(
    px: np.ndarray,
    m: np.ndarray,
    x: int,
    y: int,
    col: np.ndarray | RGB,
    clip: tuple[int, int, int, int] = (0, 0, 31, 31),
) -> None:
    """Draw mask `m` at (x, y) inside `clip` (inclusive). `col` is one RGB or one RGB per mask column."""
    h, w = m.shape
    x0, y0 = max(x, clip[0], 0), max(y, clip[1], 0)
    x1, y1 = min(x + w - 1, clip[2], 31), min(y + h - 1, clip[3], 31)
    if x0 > x1 or y0 > y1:
        return
    sub = m[y0 - y : y1 - y + 1, x0 - x : x1 - x + 1]
    region = px[y0 : y1 + 1, x0 : x1 + 1]
    c = np.asarray(col, dtype=np.uint8)
    if c.ndim == 1:
        region[sub] = c
    else:
        cols = np.broadcast_to(c[x0 - x : x1 - x + 1][None], (y1 - y0 + 1, x1 - x0 + 1, 3))
        region[sub] = cols[sub]


def fmt_time(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 3600}:{s // 60 % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _vivid(c: Any, sat: float = 0.85) -> RGB:
    """The same hue, pushed to at least `sat` saturation (pastel palette entries turn muddy when mixed)."""
    import colorsys

    r, g, b = (v / 255 for v in to_rgb(c))
    h, s_, v = colorsys.rgb_to_hsv(r, g, b)
    if s_ < 0.08:
        return to_rgb(c)
    rr, gg, bb = colorsys.hsv_to_rgb(h, max(sat, s_), v)
    return round(rr * 255), round(gg * 255), round(bb * 255)


@lru_cache(maxsize=256)
def _display(title: str, artist: str) -> tuple[str, str]:
    """Title/artist as shown: YouTube-style noise stripped ("Artist - Song (Official Video)" -> "Song")."""
    t, a = normalize_track(title, artist)
    return (t or title), (a or artist)


def _title(m: dict[str, Any]) -> str:
    return _display(str(m.get("title") or ""), str(m.get("artist") or ""))[0]


def _artist(m: dict[str, Any]) -> str:
    return _display(str(m.get("title") or ""), str(m.get("artist") or ""))[1]


def _lift(c: Any, floor: int) -> RGB:
    """Raise a colour (same hue) until its brightest channel reaches `floor`: dark tones vanish on the LEDs."""
    r, g, b = to_rgb(c)
    m = max(r, g, b)
    if m >= floor:
        return r, g, b
    if m == 0:
        return floor, floor, floor
    k = floor / m
    return min(255, round(r * k)), min(255, round(g * k)), min(255, round(b * k))


def _arr(c: Any) -> np.ndarray:
    return np.array(to_rgb(c), dtype=np.float32)


# ------------------------------------------------------------------------------------------------ art
@dataclass
class ArtSet:
    """Every derived form of one cover, computed once per art_id."""

    cover32: np.ndarray  # calibrated, uint8
    cover16: np.ndarray
    big64: np.ndarray  # calibrated float32, for the Ken Burns crop
    blur32: np.ndarray  # calibrated + blurred float32, for lyrics over art
    palette: list[RGB]
    src: Image.Image | None = None  # the adjusted, calibrated source, for mosaic tiles
    tiles: dict[tuple[int, int, str], np.ndarray] | None = None  # mosaic tiles per (grid, colours, dither)


def build_art(
    img: Image.Image,
    palette: list[RGB] | None = None,
    *,
    style: str = "smooth",
    colors: int = 6,
    dither: str = "bayer",
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> ArtSet:
    img = kit.adjust(img.convert("RGB"), contrast, saturation)

    def cal(i: Image.Image, dt: Any = np.uint8, profile: str = "vibrant") -> np.ndarray:
        return np.asarray(calibrate(i, profile), dtype=dt)  # type: ignore[arg-type]

    # LED levels once, at full size: styled art is calibrated *before* it is styled
    lit = calibrate(img, "vibrant")
    if style == "smooth":
        c32 = cal(img.resize((32, 32), Image.Resampling.LANCZOS))
        c16 = cal(img.resize((16, 16), Image.Resampling.LANCZOS))
        b64 = cal(img.resize((64, 64), Image.Resampling.LANCZOS), np.float32)
    else:  # calibrating afterwards would sharpen the blocks and dither and add halo colours
        s32 = kit.stylise(lit, 32, style, colors, dither)
        c32 = np.asarray(s32, np.uint8)
        c16 = np.asarray(kit.stylise(lit, 16, style, colors, dither), np.uint8)
        # Living art pans over the same pixels the cover shows
        b64 = np.asarray(s32.resize((64, 64), Image.Resampling.NEAREST), np.float32)
    small = img.resize((32, 32), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(2.2))
    blur = cal(small, np.float32, "natural")
    return ArtSet(c32, c16, b64, blur, palette or extract_palette(img), lit, {})


def art_tiles(art: ArtSet, grid: int, colors: int, dither: str) -> np.ndarray:
    """Mosaic tiles for one cover, computed once per (grid, colours, dither)."""
    key = (grid, colors, dither)
    tiles = art.tiles if art.tiles is not None else {}
    got = tiles.get(key)
    if got is None and art.src is not None:
        got = np.asarray(kit.mosaic_tiles(art.src, grid, colors, dither), np.uint8)
        tiles[key] = got
        art.tiles = tiles
    if got is None:  # no source image kept: reduce the 32 px cover
        k = 32 // grid
        got = art.cover32.reshape(grid, k, grid, k, 3).mean(axis=(1, 3)).astype(np.uint8)
    return got


def _bilinear(src: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    h, w = src.shape[:2]
    sx = np.clip(sx, 0, w - 1.001)
    sy = np.clip(sy, 0, h - 1.001)
    x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    a, b = src[y0, x0], src[y0, x0 + 1]
    c, d = src[y0 + 1, x0], src[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


# ------------------------------------------------------------------------------------------------ vinyl
_VC = 16.0  # disc centre
_VR = np.hypot(_X - _VC, _Y - _VC)
_VTH = np.arctan2(_Y - _VC, _X - _VC)
_LABEL_R = 7.0
_LABEL = (_VR < _LABEL_R) & (_VR >= 1.3)
_HOLE = _VR < 1.3


def _vinyl_base() -> np.ndarray:
    """The static part of the record: grooves, a fixed sheen and an anti-aliased rim."""
    groove = 0.5 + 0.5 * np.sin(_VR * 2.9)
    base = 30 + 22 * groove  # 12..26 was below what the panel's gamma 1.5 shows: the disc read as a hole
    sheen = np.maximum(0, np.cos(2 * (_VTH + math.pi / 4))) ** 6 * 48 * (_VR > _LABEL_R + 0.8)
    v = base + sheen
    img = np.stack([v * 0.95, v * 0.95, v * 1.15], axis=-1)
    edge = np.clip(15.8 - _VR, 0, 1)[..., None]
    img = img * edge
    ring = (np.abs(_VR - (_LABEL_R + 0.3)) < 0.5)[..., None]
    return np.where(ring, img * 0.4, img).astype(np.float32)


_VINYL = _vinyl_base()
_ARM_PIVOT = (30.0, 30.0)  # bottom-right corner; the arm reaches up into the grooves
_ARM_LEN = 24.0


def _arm_angles() -> tuple[float, float]:
    """Tonearm angles (rad) putting the stylus at the outer groove and at the label edge."""
    betas = np.linspace(math.radians(232), math.radians(268), 600)
    sx = _ARM_PIVOT[0] + _ARM_LEN * np.cos(betas)
    sy = _ARM_PIVOT[1] + _ARM_LEN * np.sin(betas)
    r = np.hypot(sx - _VC, sy - _VC)
    return float(betas[np.argmin(np.abs(r - 13.0))]), float(betas[np.argmin(np.abs(r - _LABEL_R - 1.5))])


_ARM_OUT, _ARM_IN = _arm_angles()


# ------------------------------------------------------------------------------------------------ lyric rows
@dataclass
class Row:
    """One on-panel row of a lyric line: its bitmap and each word's time span and pixel span."""

    line: int
    mask: np.ndarray
    words: list[tuple[float, float, int, int]]  # (start, end, x0, x1) — x1 exclusive
    start: float
    end: float
    dy: int = 0  # vertical offset inside the row slot (a compact row centred in a big-type slot)

    @property
    def w(self) -> int:
        return self.mask.shape[1]

    def fill_word(self, pos: float) -> float:
        """Like `fill_x`, but a word lights whole the moment it starts."""
        fx = 0.0
        for s, _e, _x0, x1 in self.words:
            if pos < s:
                break
            fx = float(x1)
        return fx

    def fill_x(self, pos: float) -> float:
        """Pixel column the karaoke fill has reached at `pos`."""
        fx = 0.0
        for s, e, x0, x1 in self.words:
            if pos < s:
                break
            k = 1.0 if pos >= e else (pos - s) / max(0.01, e - s)
            fx = x0 + k * (x1 - x0)
        return fx


def layout_line(line: Any, idx: int, font: str, width: int = 30) -> list[Row]:
    """Greedy-wrap a lyric line into rows of `width` px, keeping each word's timing.

    `font` is "small", "tiny" or "auto": big 7 px rows, except that a word too wide for a big row gets a
    compact 5 px row of its own (centred in the big slot) instead of being cut off.
    """
    base = "tiny" if font == "tiny" else "small"
    rows: list[Row] = []
    cur: list[tuple[str, float, float, int]] = []
    cur_w = 0

    def emit(items: list[tuple[str, float, float, int]], f: str) -> None:
        space = measure(" ", f) + 2  # the space glyph plus letter spacing on both sides
        text = " ".join(w for w, *_ in items)
        words, x = [], 0
        for _w, s0, e0, ww in items:
            words.append((s0, e0, x, x + ww))
            x += ww + space
        dy = (FONTS[base].height - FONTS[f].height) // 2
        rows.append(Row(idx, text_mask(text, f), words, items[0][1], items[-1][2], dy))

    space = measure(" ", base) + 2
    for word in line.words:
        txt = clean(word.text, base)
        if not txt:
            continue
        ww = measure(txt, base)
        if font == "auto" and ww > width:
            if cur:
                emit(cur, base)
                cur, cur_w = [], 0
            small = clean(word.text, "tiny")
            emit([(small, word.start, word.end, measure(small, "tiny"))], "tiny")
            continue
        need = ww if not cur else cur_w + space + ww
        if cur and need > width:
            emit(cur, base)
            cur = []
            need = ww
        cur.append((txt, word.start, word.end, ww))
        cur_w = need
    if cur:
        emit(cur, base)
    return rows


# ------------------------------------------------------------------------------------------------ settings
LAYOUT_LABELS: dict[str, str] = {
    "karaoke": "Karaoke",
    "lyrics": "Synced lyrics",
    "lyrics_art": "Lyrics over art",
    "wordpop": "Word pop",
    "cover": "Album art",
    "cover_text": "Art + title",
    "live_art": "Living art",
    "vinyl": "Vinyl",
    "cd": "CD",
    "cassette": "Cassette",
    "mosaic": "Mosaic",
    "split": "Art + info",
    "minimal": "Minimal",
    "big_title": "Big title",
    "palette": "Colour wash",
    "spectrum_art": "Spectrum",
    "vu": "VU meters",
    "waveform": "Waveform",
    "radio": "Radio dial",
}


def _g(group: str) -> dict[str, Any]:
    return {"json_schema_extra": {"group": group}}


class NowPlayingSettings(AppSettings):
    layout: str = Choice("karaoke", LAYOUT_LABELS, title="Layout")
    take_over: bool = Field(True, title="Take over while music plays", description="In the playlist")
    color: Color = Field(
        "#ffd600", title="Lyric colour", description="Current line in the Synced lyrics layout"
    )
    accent: Color = Field(
        "#00ff8c", title="Accent", description="Progress and equaliser (unless themed from art)"
    )
    fallback_cover: bool = Field(True, title="Show art when no lyrics")

    # ---- track info
    show_album: bool = Field(False, title="Show album", description="After the artist", **_g("Track info"))
    show_source: bool = Field(
        True, title="Show where it plays", description="A small generic glyph: music app, browser or player",
        **_g("Track info"),
    )  # fmt: skip
    scroll_style: str = Choice(
        "marquee",
        {"marquee": "Marquee (loops)", "bounce": "Bounce", "page": "Pages of words"},
        title="Long text",
        group="Track info",
    )
    scroll_speed: float = Field(12.0, ge=6, le=24, title="Scroll speed (px/s)", **_g("Track info"))

    # ---- lyrics
    offset: float = Field(
        0.3, ge=-5, le=5, title="Lyric offset (s)", description="Positive = earlier", **_g("Lyrics")
    )
    karaoke_color: Color = Field("#ffd600", title="Sung colour", **_g("Lyrics"))
    karaoke_dim: Color = Field("#5a5a78", title="Unsung colour", **_g("Lyrics"))
    font: str = Choice(
        "auto",
        {"auto": "Auto (big when it fits)", "small": "Big 7 px", "tiny": "Compact 5 px"},
        title="Lyric size",
        group="Lyrics",
    )
    lyric_align: str = Choice(
        "center", {"center": "Centre", "left": "Left"}, title="Lyric alignment", group="Lyrics"
    )
    highlight: str = Choice(
        "sweep",
        {"sweep": "Sweep through words", "word": "Whole words", "underline": "Underline"},
        title="Sung highlight",
        group="Lyrics",
    )
    line_spacing: str = Choice(
        "normal",
        {"tight": "Tight", "normal": "Normal", "loose": "Loose"},
        title="Line spacing",
        group="Lyrics",
    )
    translation: bool = Field(
        True, title="Translation line", description="When the lyrics carry one (same-time lines in the LRC)",
        **_g("Lyrics"),
    )  # fmt: skip

    # ---- display
    show_progress: bool = Field(True, title="Progress bar", **_g("Display"))
    show_time: bool = Field(True, title="Show time", **_g("Display"))
    time_mode: str = Choice(
        "elapsed", {"elapsed": "Elapsed", "remaining": "Remaining"}, title="Time", group="Display"
    )

    # ---- song change / rotation
    transition: str = Choice(
        "dissolve",
        {"cut": "Cut", "slide": "Slide", "dissolve": "Dissolve", "zoom": "Art zoom"},
        title="Between songs",
        group="Song change",
    )
    rotate: str = Choice(
        "off",
        {"off": "Off", "song": "Every song", "timer": "Every few seconds"},
        title="Rotate layouts",
        group="Song change",
    )
    rotate_set: str = Choice(
        "mix",
        {"mix": "Best of", "art": "Art", "lyrics": "Lyrics", "retro": "Retro gear", "info": "Track info"},
        title="Rotate through",
        group="Song change",
    )
    rotate_every: int = Field(45, ge=10, le=600, title="Rotate every (s)", **_g("Song change"))

    # ---- paused / idle
    pause_style: str = Choice(
        "auto",
        {
            "auto": "Layout's own",
            "dim": "Dim",
            "badge": "Pause sign",
            "freeze": "Freeze",
            "idle": "Idle screen after 20 s",
        },
        title="When paused",
        group="Paused & idle",
    )
    idle_screen: str = Choice(
        "no_music",
        {
            "no_music": "NO MUSIC",
            "clock": "Clock",
            "last_art": "Last album art",
            "covers": "Recent covers",
            "waves": "Calm waves",
            "silence": "Silence",
            "nothing": "Nothing",
        },
        title="When nothing plays",
        group="Paused & idle",
    )
    wall_size: str = Choice(
        "4", {"4": "4 covers", "16": "16 covers"}, title="Recent covers wall", group="Paused & idle"
    )

    # ---- art
    art_brightness: float = Field(1.0, ge=0.2, le=1.0, title="Art brightness", **_g("Art"))
    art_dim: float = Field(
        0.3, ge=0.05, le=0.7, title="Art behind lyrics", description="Background level for Lyrics over art",
        **_g("Art"),
    )  # fmt: skip
    theme_from_art: bool = Field(
        True, title="Colours from album art", description="Sung colour and accent follow the cover's palette",
        **_g("Art"),
    )  # fmt: skip
    art_style: str = Choice(
        "smooth",
        {"smooth": "Smooth", "pixelated": "Pixelated", "posterised": "Posterised", "dithered": "Dithered"},
        title="Art style",
        group="Art",
    )
    dither: str = Choice(
        "bayer",
        {"bayer": "Ordered (crosshatch)", "diffusion": "Error diffusion", "none": "None"},
        title="Dither",
        description="Dithered art and Mosaic",
        group="Art",
    )
    art_colors: int = Field(
        6, ge=2, le=16, title="Colours", description="Posterised / dithered art and Mosaic", **_g("Art")
    )
    art_contrast: float = Field(1.0, ge=0.5, le=1.8, title="Contrast", **_g("Art"))
    art_saturation: float = Field(1.0, ge=0.0, le=2.0, title="Saturation", **_g("Art"))
    beat_sync: bool = Field(
        False, title="Pulse with the beat", description="Living art breathes with system audio (starts audio capture)",
        **_g("Art"),
    )  # fmt: skip

    # ---- per-layout
    title_size: str = Choice(
        "huge",
        {"huge": "Huge (14 px)", "tall": "Tall (10 px)"},
        title="Big title size",
        group="Layout options",
    )
    cassette_shell: str = Choice(
        "art",
        {"art": "From the cover", "classic": "Black", "chrome": "Chrome", "red": "Red"},
        title="Cassette shell",
        group="Layout options",
    )
    vu_style: str = Choice(
        "needles",
        {"needles": "Twin needles", "ladders": "LED ladders"},
        title="VU meters",
        group="Layout options",
    )
    cd_shine: bool = Field(True, title="CD rainbow sheen", **_g("Layout options"))
    radio_band: str = Choice("fm", {"fm": "FM", "am": "AM"}, title="Radio band", group="Layout options")
    mosaic_grid: str = Choice(
        "8", {"8": "Big tiles (8 × 8)", "16": "Small tiles (16 × 16)"}, title="Mosaic", group="Layout options"
    )
    wave_style: str = Choice(
        "mirror", {"mirror": "Mirrored bars", "line": "Trace"}, title="Waveform", group="Layout options"
    )


# ------------------------------------------------------------------------------------------------ app
@register
class NowPlaying(App):
    id = "nowplaying"
    name = "Now Playing"
    description = (
        "Spotify / YouTube Music / any player: album art, karaoke lyrics, vinyl, cassette, CD, VU meters, "
        "radio dial and more."
    )
    icon = "music"
    category = "media"
    Settings = NowPlayingSettings
    theme_colors: ClassVar[dict[str, str]] = {
        "color": "accent2",
        "accent": "accent",
        "karaoke_color": "accent2",
    }  # page theme (docs/APP_SDK.md § Page theme)
    uses = ("media", "lyrics")  # "audio" is acquired on demand (spectrum / VU / waveform / beat-synced only)
    # the host's media session: Windows GSMTC, macOS AppleScript / nowplaying-cli, Linux MPRIS (playerctl)
    platforms = DESKTOP
    web_reason = (
        "A browser tab can't read the computer's media session (Spotify, Music, browser players); "
        "use the desktop app."
    )
    actions = (
        Action("prev", "Previous", "skip-back"),
        Action("toggle", "Play/Pause", "play"),
        Action("next", "Next", "skip-forward"),
    )

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._art_id: str | None = None
        self._art_cfg: tuple[Any, ...] | None = None
        self._art: ArtSet | None = None
        self._last_art: ArtSet | None = None
        self._art_t0 = -99.0  # when the current cover arrived (mosaic reveal); -99 = shown at once
        self._recent: list[tuple[str, np.ndarray, np.ndarray]] = []  # (art_id, 16 px, 8 px), newest first
        self._lyr: Any = None
        self._rows: dict[tuple[int, str], list[Row]] = {}
        self._audio_held = False
        self._visible = False
        self._t = 0.0
        self._cur_layout: str = self.settings.layout
        self._reset_motion()

    def _reset_motion(self) -> None:
        """Per-visit animation state: transitions, freeze, rotation, meters, dial."""
        self._last: np.ndarray | None = None  # the frame shown last (a transition starts from it)
        self._key: tuple[str, str, bool] | None = None  # (track, layout, has art)
        self._tr_from: np.ndarray | None = None
        self._tr_t0 = 0.0
        self._tr_kind = "cut"
        self._frozen: np.ndarray | None = None
        self._paused_at: float | None = None
        self._rot_track: str | None = None
        self._rot_n = 0
        self._vu_lv = np.zeros(2, np.float32)
        self._vu_pk = np.zeros(2, np.float32)
        self._vu_t: float | None = None
        self._wave = np.zeros(30, np.float32)
        self._wave_t: float | None = None
        self._tuned: tuple[str, str] | None = None  # (track, band) the dial is tuned to
        self._radio_from = self._radio_to = self._radio_freq = 0.0
        self._radio_t0 = -99.0

    @property  # type: ignore[override]
    def fps(self) -> float:  # type: ignore[override]
        if self.settings.rotate != "off":
            return 10.0
        return 10.0 if self._cur_layout in FAST_LAYOUTS else 6.0

    # ------------------------------------------------------------------ lifecycle / scheduling
    def _candidates(self) -> tuple[str, ...]:
        s = self.settings
        return ROTATE_SETS.get(s.rotate_set, (s.layout,)) if s.rotate != "off" else (s.layout,)

    def _needs_audio(self) -> bool:
        c = self._candidates()
        return any(k in AUDIO_LAYOUTS for k in c) or ("live_art" in c and self.settings.beat_sync)

    def _sync_audio(self) -> None:
        want = self._visible and self._needs_audio()
        if want == self._audio_held:
            return
        try:
            p = self.ctx.provider("audio")
        except Exception:
            return
        (p.acquire if want else p.release)()
        self._audio_held = want

    def on_start(self) -> None:
        self._visible = True
        self._art_t0 = -99.0
        self._reset_motion()
        self._sync_audio()

    def on_stop(self) -> None:
        self._visible = False
        self._sync_audio()

    def on_settings(self) -> None:
        self._rows.clear()
        self._lyr = None
        self._cur_layout = self.settings.layout
        self._sync_audio()

    def watches_focus(self) -> bool:
        return self.settings.take_over

    def wants_focus(self) -> bool:
        m = self.ctx.provider("media").value
        return bool(m and m.get("active") and m.get("playing"))

    def relevant(self) -> bool:
        if not self.supported_here():
            return False
        m = self.ctx.provider("media").value
        return m is None or bool(m.get("active"))

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        return await self.ctx.provider("media").control(name)

    # ------------------------------------------------------------------ data helpers
    def _media(self) -> Any:
        return self.ctx.provider("media")

    def _pos(self) -> float:
        return float(getattr(self._media(), "position", 0.0) or 0.0)

    @staticmethod
    def _track(m: dict[str, Any]) -> str:
        return str(m.get("track") or f"{m.get('title', '')}\x1f{m.get('artist', '')}")

    def _update_art(self) -> None:
        s = self.settings
        mp = self._media()
        aid = getattr(mp, "art_id", None)
        cfg = (s.art_style, s.art_colors, s.dither, round(s.art_contrast, 3), round(s.art_saturation, 3))
        if aid == self._art_id and cfg == self._art_cfg:
            return
        new_cover = aid != self._art_id
        self._art_id, self._art_cfg = aid, cfg
        self._art = None
        img = getattr(mp, "art_image", None)
        if img is None and getattr(mp, "art", None):
            img = decode_art(mp.art)
        if img is not None:
            pal = getattr(mp, "palette", None) if getattr(mp, "art_image", None) is not None else None
            try:
                self._art = build_art(
                    img, list(pal) if pal else None, style=s.art_style, colors=s.art_colors, dither=s.dither,
                    contrast=s.art_contrast, saturation=s.art_saturation,
                )  # fmt: skip
            except Exception:
                self._art = None
        if self._art is not None:
            if new_cover:
                # a cover replacing another one is revealed (Mosaic); the first one of a visit shows at once
                self._art_t0 = self._t if self._last_art is not None else -99.0
                self._remember(str(aid), self._art)
            self._last_art = self._art

    def _remember(self, aid: str, art: ArtSet) -> None:
        c = art.cover32.astype(np.float32)
        c16 = c.reshape(16, 2, 16, 2, 3).mean(axis=(1, 3)).astype(np.uint8)
        c8 = c.reshape(8, 4, 8, 4, 3).mean(axis=(1, 3)).astype(np.uint8)
        self._recent = [(aid, c16, c8), *[r for r in self._recent if r[0] != aid]][:16]

    def _pal(self) -> list[RGB]:
        if self._art is not None:
            return self._art.palette
        pal = getattr(self._media(), "palette", None)
        return [to_rgb(c) for c in pal] if pal else [(255, 72, 24), (255, 170, 0), (255, 0, 190)]

    def _accent(self) -> RGB:
        s = self.settings
        return (
            _lift(self._pal()[0], READABLE)
            if s.theme_from_art and self._art is not None
            else to_rgb(s.accent)
        )

    def _sung(self) -> RGB:
        s = self.settings
        if s.theme_from_art and self._art is not None:
            return _lift(_vivid(self._pal()[0], 0.6), READABLE)  # a dark cover colour would vanish as text
        return to_rgb(s.karaoke_color)

    def _byline(self, m: dict[str, Any]) -> str:
        """Artist, plus the album when "Show album" is on."""
        artist = clean(_artist(m))
        album = clean(str(m.get("album") or ""))
        if self.settings.show_album and album and album != clean(_title(m)):
            return f"{artist} · {album}" if artist else album
        return artist

    def _glyph(self, f: Frame, m: dict[str, Any], x: int, y: int, color: Any) -> bool:
        """The source as a small generic glyph (never a brand logo). False when "Show where it plays" is off."""
        if not self.settings.show_source:
            return False
        kit.draw_glyph(f, kit.source_kind(str(m.get("source") or "")), x, y, color)
        return True

    def _lyrics(self, m: dict[str, Any]) -> Any:
        lp = self.ctx.provider("lyrics")
        try:
            lyr = lp.get(
                m.get("title", ""), m.get("artist", ""), m.get("album", ""), m.get("duration") or 0.0
            )
        except TypeError:  # an older / stub provider without the album & duration arguments
            lyr = lp.get(m.get("title", ""), m.get("artist", ""))
        if lyr is not self._lyr:
            self._lyr = lyr
            self._rows.clear()
        return lyr

    def _font(self) -> str:
        f = self.settings.font
        return f

    def _line_rows(self, lyr: Any, i: int, font: str) -> list[Row]:
        key = (i, font)
        rows = self._rows.get(key)
        if rows is None:
            rows = layout_line(lyr.entries[i], i, font) if 0 <= i < len(lyr.entries) else []
            self._rows[key] = rows
        return rows

    def _scroll(self, t: float) -> tuple[float, float]:
        """(time snapped to whole frames, speed as a whole number of px per frame): a marquee that moves the
        same number of pixels every frame (12 px/s at 10 fps stepped 1-1-1-1-2 and read as stutter)."""
        fps = self.fps
        step = max(1, round(self.settings.scroll_speed / fps))
        return (math.floor(t * fps + 1e-6) + 0.01) / fps, float(step * fps)

    def _marquee(
        self, f: Frame, text: str, t: float, x: int, y: int, color: Any, font: str = "tiny", w: int = 30
    ) -> None:
        """Content text in the box [x, x+w): centred when it fits, else Marquee / Bounce / Pages."""
        tq, speed = self._scroll(t)
        style = self.settings.scroll_style
        tw = measure(text, font)
        if tw <= w or style == "marquee":
            draw_marquee(f, text, tq, x, y, w, color, font=font, speed=speed)
            return
        clip = (x, y, x + w - 1, y + FONTS[font].height - 1)
        if style == "bounce":
            f.text(x - kit.bounce_offset(tw - w, tq, speed), y, text, color, font, clip=clip)
            return
        pg = kit.pages(text, font, w)
        p = pg[int(tq / PAGE_S) % len(pg)]
        f.text(x + (w - measure(p, font)) // 2, y, p, color, font, clip=clip)

    def _scroll_mask(self, f: Frame, text: str, font: str, k: int, t: float, y: int, col: RGB) -> None:
        """`text` drawn k× big in the box x 1..30, scrolled with the chosen long-text style."""
        x, w = 1, 30
        mask = kit.scaled_mask((text, font), k)
        tw = mask.shape[1]
        clip = (x, 0, x + w - 1, 31)
        if tw <= w:
            paint(f.px, mask, x + (w - tw) // 2, y, col, clip)
            return
        tq, speed = self._scroll(t)
        style = self.settings.scroll_style
        if style == "bounce":
            paint(f.px, mask, x - kit.bounce_offset(tw - w, tq, speed), y, col, clip)
            return
        if style == "page":
            pg = kit.pages(text, font, w // k)
            pm = kit.scaled_mask((pg[int(tq / PAGE_S) % len(pg)], font), k)
            paint(f.px, pm, x + (w - pm.shape[1]) // 2, y, col, clip)
            return
        travel = tw + 16
        ph = tq % (1.2 + travel / speed)
        off = 0 if ph < 1.2 else int((ph - 1.2) * speed)
        paint(f.px, mask, x - off, y, col, clip)
        paint(f.px, mask, x - off + travel, y, col, clip)

    # ------------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        self._t = t
        s = self.settings
        mp = self._media()
        m = mp.value
        if m is None:
            if not self.supported_here():
                unsupported(f, "MUSIC")
            elif getattr(mp, "error", None):
                offline(f, "MUSIC", "NO PLAYER")
            else:
                loading(f, t, "MUSIC", s.accent)
            self._last = self._key = None
            return
        if not m.get("active"):
            self._idle(f, t)
            self._last = self._key = None
            self._paused_at = None
            return
        self._update_art()
        track = self._track(m)
        if self._key is not None and self._key[0] != track:
            self._frozen = None
        layout = self._effective_layout(t, track)
        self._cur_layout = layout
        playing = bool(m.get("playing"))
        if playing:
            self._paused_at = None
        elif self._paused_at is None or t < self._paused_at:
            self._paused_at = t
        ps = s.pause_style
        if (
            not playing
            and ps == "idle"
            and self._paused_at is not None
            and t - self._paused_at >= PAUSE_IDLE_S
        ):
            self._idle(f, t)
            self._last = self._key = None
            return
        if not playing and ps == "freeze" and self._frozen is not None:
            f.px[:] = self._frozen
            self._pause_mark(f)
        else:
            self._draw(f, t, m, layout)
            if playing:
                if ps == "freeze":
                    self._frozen = f.px.copy()
            elif ps == "dim":
                f.px[:] = (f.px.astype(np.float32) * 0.45).astype(np.uint8)
            elif ps == "badge":
                self._pause_badge(f)
        self._transition(f, t, (track, layout, self._art is not None))

    def _effective_layout(self, t: float, track: str) -> str:
        """The layout to draw now: the chosen one, or the next one of the rotation set."""
        s = self.settings
        if s.rotate == "off":
            return str(s.layout)
        seq = ROTATE_SETS.get(s.rotate_set) or (s.layout,)
        base = seq.index(s.layout) if s.layout in seq else 0
        if s.rotate == "song":
            if track != self._rot_track:
                if self._rot_track is not None:
                    self._rot_n += 1
                self._rot_track = track
            return seq[(base + self._rot_n) % len(seq)]
        return seq[(base + int(t // max(1, s.rotate_every))) % len(seq)]

    def _draw(self, f: Frame, t: float, m: dict[str, Any], layout: str) -> None:
        s = self.settings
        if layout in LYRIC_LAYOUTS:
            lyr = self._lyrics(m)
            if lyr is not None and len(lyr.entries):
                if layout == "wordpop":
                    self._wordpop(f, t, m, lyr)
                else:
                    self._lyric_layout(f, t, m, lyr, layout)
                return
            layout = "cover_text" if s.fallback_cover and self._art is not None else "minimal"
        getattr(self, "_palette_layout" if layout == "palette" else f"_{layout}")(f, t, m)
        if not m.get("playing") and s.pause_style == "auto" and layout in BADGE_LAYOUTS:
            self._pause_badge(f)

    def _transition(self, f: Frame, t: float, key: tuple[str, str, bool]) -> None:
        """Song change (or a rotation step): blend from the last frame shown. A cover arriving after the song
        started dissolves in instead of popping."""
        s = self.settings
        prev, self._key = self._key, key
        if prev is not None and self._last is not None and s.transition != "cut":
            kind = None
            if prev[0] != key[0] or prev[1] != key[1]:
                kind = s.transition
            elif key[2] and not prev[2] and key[1] != "mosaic":  # Mosaic reveals its tiles itself
                kind = "dissolve"
            if kind:
                self._tr_from, self._tr_t0, self._tr_kind = self._last, t, kind
        if self._tr_from is not None:
            p = (t - self._tr_t0) / TRANSITION_S
            if 0 <= p < 1:
                f.px[:] = kit.transition(self._tr_from, f.px, self._tr_kind, p)
            else:
                self._tr_from = None
        self._last = f.px.copy()

    # ------------------------------------------------------------------ shared pieces
    def _progress(self, f: Frame, m: dict[str, Any], y: int = 31, color: RGB | None = None) -> None:
        dur = m.get("duration") or 0
        if dur > 0 and self.settings.show_progress:
            c = color or self._accent()
            if not m.get("playing"):
                c = scale(c, 0.45)
            f.bar(0, y, 32, 1, self._pos() / dur, c, track=TRACK)

    def _time_text(self, m: dict[str, Any]) -> str:
        dur = m.get("duration") or 0
        pos = self._pos()
        if self.settings.time_mode == "remaining" and dur > 0:
            return "-" + fmt_time(dur - pos)
        return fmt_time(pos)

    def _pause_badge(self, f: Frame) -> None:
        f.px[:] = (f.px.astype(np.float32) * 0.45).astype(np.uint8)
        f.rect(12, 11, 3, 10, (255, 255, 255))
        f.rect(17, 11, 3, 10, (255, 255, 255))

    def _pause_mark(self, f: Frame) -> None:
        """Small pause sign in the top-right corner (Freeze keeps the picture itself untouched)."""
        f.rect(25, 0, 7, 7, (0, 0, 0))
        f.rect(27, 1, 1, 5, (230, 230, 240))
        f.rect(29, 1, 1, 5, (230, 230, 240))

    def _art_px(self, k: float = 1.0) -> np.ndarray | None:
        if self._art is None:
            return None
        k *= self.settings.art_brightness
        return (
            self._art.cover32 if k >= 0.999 else (self._art.cover32.astype(np.float32) * k).astype(np.uint8)
        )

    def _no_art(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        """Procedural cover when a track has no art: palette gradient with a big note."""
        pal = self._pal()
        top, bot = _arr(scale(pal[0], 0.35)), _arr(scale(pal[1 % len(pal)], 0.12))
        k = ((_X + _Y) / 64.0)[..., None]
        f.px[:] = (top * (1 - k) + bot * k).astype(np.uint8)
        c = scale(pal[0], 0.9)
        f.circle(12, 22, 3, c)  # a big hand-drawn eighth note
        f.rect(14, 8, 2, 14, c)
        f.line(15, 8, 20, 13, c)
        f.line(15, 9, 20, 14, c)
        f.rect(20, 13, 1, 4, c)

    # ------------------------------------------------------------------ idle
    def _idle(self, f: Frame, t: float) -> None:
        s = self.settings
        mode = s.idle_screen
        if mode == "nothing":
            return
        if mode == "last_art" and self._last_art is not None:
            f.px[:] = (self._last_art.cover32.astype(np.float32) * 0.3 * s.art_brightness).astype(np.uint8)
            return
        if mode == "covers" and self._recent:
            big = s.wall_size == "4"
            kit.idle_wall(f, [r[1] if big else r[2] for r in self._recent], t, 0.6 * s.art_brightness)
            return
        if mode == "waves":
            kit.idle_waves(f, t, to_rgb(s.accent), to_rgb(s.karaoke_color))
            return
        if mode == "silence":
            kit.idle_silence(f, t, to_rgb(s.accent))
            return
        if mode == "clock":
            now = datetime.now()
            f.text_center(9, f"{now.hour:02d}:{now.minute:02d}", scale(s.accent, 0.85), font="big")
            f.text_center(23, "♪", scale(s.accent, 0.35))
            return
        f.text_center(10, "♪", scale(s.accent, 0.6), font="small")
        f.text_center(20, "NO MUSIC", (90, 90, 110))

    # ------------------------------------------------------------------ lyrics
    def _lyric_layout(self, f: Frame, t: float, m: dict[str, Any], lyr: Any, layout: str) -> None:
        s = self.settings
        pos = self._pos() + s.offset
        over_art = layout == "lyrics_art"
        if over_art:
            if self._art is not None:
                f.px[:] = np.clip(self._art.blur32 * s.art_dim, 0, 255).astype(np.uint8)
            else:
                pal = self._pal()
                k = (_Y / 32.0)[..., None]
                f.px[:] = (
                    _arr(scale(pal[0], 0.16)) * (1 - k) + _arr(scale(pal[1 % len(pal)], 0.08)) * k
                ).astype(np.uint8)
        fill = layout != "lyrics" and bool(lyr.synced)
        sung = self._sung()
        unsung: RGB = (190, 190, 205) if over_art else to_rgb(s.karaoke_dim)
        current = sung if fill or over_art else to_rgb(s.color)
        playing = bool(m.get("playing"))
        tr = ""
        if s.translation:
            i = lyr.index(pos)
            if 0 <= i < len(lyr.entries):
                tr = clean(getattr(lyr.entries[i], "translation", "") or "")
        self._stream(
            f, t, m, lyr, pos, fill=fill, shadow=over_art, sung=current, unsung=unsung, cap=20 if tr else None
        )
        if tr:  # the translation sits in its own band above the progress bar
            f.px[21:30] = (f.px[21:30].astype(np.float32) * 0.15).astype(np.uint8)
            self._marquee(f, tr, t, 1, 23, _lift(scale(current, 0.75), 150))
        if not playing and s.pause_style == "auto":
            n = 30 if s.show_progress else 32
            f.px[:n] = (f.px[:n] * 0.55).astype(np.uint8)
        self._progress(f, m)

    def _stream(
        self,
        f: Frame,
        t: float,
        m: dict[str, Any],
        lyr: Any,
        pos: float,
        *,
        fill: bool,
        shadow: bool,
        sung: RGB,
        unsung: RGB,
        cap: int | None = None,
    ) -> None:
        """The lyric row stream: focus row pinned near the top, upcoming rows below, eased row scroll."""
        s = self.settings
        font = self._font()
        fh = FONTS["tiny" if font == "tiny" else "small"].height
        big = font != "tiny"
        pitch = fh + (3 if big else 2) + SPACING.get(s.line_spacing, 0)
        top = 1 if big else 2
        bottom = 29 if s.show_progress and (m.get("duration") or 0) > 0 else 31
        if cap is not None:
            bottom = min(bottom, cap)
        entries = lyr.entries
        n = len(entries)
        i = lyr.index(pos)

        # instrumental intro / break / outro -> breathing dots toward the next line
        gap: tuple[float, float] | None = None
        if i < 0:
            gap = (0.0, entries[0].start)
        elif not entries[i].text:
            gap = (entries[i].start, entries[i + 1].start if i + 1 < n else entries[i].start + 8)
        elif i + 1 < n and entries[i + 1].start - entries[i].end > 5.0 and pos > entries[i].end + 1.2:
            gap = (entries[i].end + 1.2, entries[i + 1].start)
        elif i == n - 1 and pos > entries[i].end + 3.0:
            self._outro(f, t, m, shadow)
            return
        if gap is not None:
            nxt = i + 1 if i + 1 < n else n
            while nxt < n and not entries[nxt].text:
                nxt += 1
            self._gap(f, t, pos, gap, lyr, nxt, font, top, pitch, bottom, sung, unsung, shadow)
            return

        # rows: one line of context above, then enough lines to fill the panel
        rows: list[Row] = []
        j = max(0, i - 1)
        while j < n and (j <= i or len(rows) < 12):
            if entries[j].text:
                rows += self._line_rows(lyr, j, font)
            j += 1
        cur = [k for k, r in enumerate(rows) if r.line == i]
        if not cur:
            return
        focus = cur[0]
        for k in cur:
            if rows[k].start <= pos:
                focus = k
        # rows slide up one pitch when the focus row changes
        since = pos - rows[focus].start
        slide = (1 - _ease(since / SCROLL_S)) * pitch if focus > 0 else 0.0
        clip = (0, 0, 31, bottom)
        sung_a, unsung_a = _arr(sung), _arr(unsung)
        underline = fill and s.highlight == "underline"
        for k, r in enumerate(rows):
            y = round(top + (k - focus) * pitch + slide)
            if y > bottom or y + fh < 0 or (cap is not None and y + r.dy + r.mask.shape[0] - 1 > bottom):
                continue  # above a translation band only whole rows show
            w = r.w
            if r.line < i or (r.line == i and k < focus):
                fx = float(w)
            elif r.line == i and k == focus:
                fx = (r.fill_word(pos) if s.highlight == "word" else r.fill_x(pos)) if fill else float(w)
            else:
                fx = 0.0
            # horizontal: centre/left; long rows scroll to keep the fill in view
            if w <= 30:
                x = 1 if s.lyric_align == "left" else 1 + (30 - w) // 2
            else:
                x = (
                    1 - int(max(0.0, min(w - 30.0, fx - 20.0)))
                    if k == focus
                    else (1 - (w - 30) if fx >= w else 1)
                )
            if r.line < i:
                col: Any = _arr(_lift(scale(sung, 0.35), FLOOR))
            elif r.line == i:
                if underline:
                    col = _arr(_lift(unsung, 200))
                elif fill:
                    kk = np.clip(fx - np.arange(w, dtype=np.float32), 0.0, 1.0)[:, None]
                    col = (unsung_a + (sung_a - unsung_a) * kk).astype(np.uint8)
                else:
                    col = sung_a
            else:
                dist = r.line - i
                col = _arr(_lift(scale(unsung, 0.8 if dist == 1 else 0.55), FLOOR))
            if shadow:
                paint(f.px, r.mask, x + 1, y + r.dy + 1, (0, 0, 0), clip)
            paint(f.px, r.mask, x, y + r.dy, col, clip)
            if underline and r.line == i and k == focus and fx > 0:
                uy = y + r.dy + r.mask.shape[0] + (1 if pitch - fh >= 4 else 0)
                if 0 <= uy <= bottom:
                    x0, x1 = max(0, x), min(31, x + round(fx) - 1)
                    if x1 >= x0:
                        f.hline(x0, uy, x1 - x0 + 1, sung)

    def _gap(
        self,
        f: Frame,
        t: float,
        pos: float,
        gap: tuple[float, float],
        lyr: Any,
        nxt: int,
        font: str,
        top: int,
        pitch: int,
        bottom: int,
        sung: RGB,
        unsung: RGB,
        shadow: bool,
    ) -> None:
        g0, g1 = gap
        p = max(0.0, min(1.0, (pos - g0) / max(0.5, g1 - g0)))
        base = "tiny" if font == "tiny" else "small"
        size = 3 if base == "small" else 2
        y = top + (FONTS[base].height - size) // 2
        breathe = 0.8 + 0.2 * math.sin(t * 4.0)
        xs = [16 - size // 2 - (size + 3), 16 - size // 2, 16 - size // 2 + size + 3]
        for k, x in enumerate(xs):
            lit = max(0.0, min(1.0, p * 3 - k))
            c = mix(scale(unsung, 0.4), sung, lit)
            if shadow:
                f.rect(x + 1, y + 1, size, size, (0, 0, 0))
            f.rect(x, y, size, size, scale(c, breathe))
        if nxt >= len(lyr.entries):
            return
        rows = self._line_rows(lyr, nxt, font)
        if nxt + 1 < len(lyr.entries) and lyr.entries[nxt + 1].text:
            rows = rows + self._line_rows(lyr, nxt + 1, font)
        clip = (0, 0, 31, bottom)
        for k, r in enumerate(rows):
            yy = top + (k + 1) * pitch
            if yy > bottom:
                break
            x = 1 if r.w > 30 or self.settings.lyric_align == "left" else 1 + (30 - r.w) // 2
            col = _lift(scale(unsung, 0.8 if r.line == nxt else 0.55), FLOOR)
            if shadow:
                paint(f.px, r.mask, x + 1, yy + r.dy + 1, (0, 0, 0), clip)
            paint(f.px, r.mask, x, yy + r.dy, col, clip)

    def _outro(self, f: Frame, t: float, m: dict[str, Any], shadow: bool) -> None:
        title = clean(_title(m), "small")
        artist = self._byline(m)
        if shadow:
            self._marquee(f, title, t, 2, 10, (0, 0, 0), font="small")
        self._marquee(f, title, t, 1, 9, (255, 255, 255), font="small")
        self._marquee(f, artist, t + 0.6, 1, 20, scale(self._accent(), 0.85))

    def _wordpop(self, f: Frame, t: float, m: dict[str, Any], lyr: Any) -> None:
        """One word at a time, as big as it fits, dropping in on its beat; the word before above, the next below."""
        s = self.settings
        pos = self._pos() + s.offset
        shadow = self._art is not None
        if shadow:
            f.px[:] = np.clip(self._art.blur32 * (s.art_dim * 0.6), 0, 255).astype(np.uint8)  # type: ignore[union-attr]
        sung, unsung = self._sung(), to_rgb(s.karaoke_dim)
        entries = lyr.entries
        n = len(entries)
        i = lyr.index(pos)
        line = entries[i] if 0 <= i < n else None
        wa = lyr.words_at(pos)
        words: list[Any] = list(wa.words)
        singing = (
            line is not None
            and bool(line.text)
            and wa.index >= 0
            and pos <= max(line.end, words[-1].end) + 0.8
        )

        def tiny(text: str, y: int, col: RGB) -> None:
            text = clean(text)
            if not text:
                return
            if shadow:
                self._marquee(f, text, t, 2, y + 1, (0, 0, 0))
            self._marquee(f, text, t, 1, y, col)

        def first_word(j: int) -> str:
            while j < n and not entries[j].text:
                j += 1
            return entries[j].words[0].text if j < n and entries[j].words else ""

        if not singing:
            if line is not None and line.text and i == n - 1 and pos > line.end + 3.0:
                self._outro(f, t, m, shadow)
                self._progress(f, m)
                return
            # waiting for the next word: breathing dots, the word to come below
            g0 = line.end if line is not None and line.text else (line.start if line is not None else 0.0)
            j = i + 1 if wa.index >= 0 or line is None or not line.text else i
            nxt_t = entries[j].start if 0 <= j < n else g0 + 4.0
            p = max(0.0, min(1.0, (pos - g0) / max(0.5, nxt_t - g0)))
            breathe = 0.8 + 0.2 * math.sin(t * 4.0)
            for k, x in enumerate((9, 15, 21)):
                c = mix(scale(unsung, 0.4), sung, max(0.0, min(1.0, p * 3 - k)))
                f.rect(x, 13, 3, 3, scale(c, breathe))
            tiny(first_word(j if j >= 0 else 0), 24, _lift(scale(unsung, 0.8), FLOOR))
        else:
            word = words[wa.index]
            age = pos - word.start
            text = clean(word.text, "small")
            pick = None
            for font, k in (("small", 2), ("tiny", 2), ("small", 1)):
                mk = kit.scaled_mask((clean(word.text, font), font), k)
                if mk.shape[1] <= 30:
                    pick = mk
                    break
            drop = round(-2 * (1 - _ease(age / 0.18)))  # drops in from 2 px above
            col = scale(sung, 0.55 + 0.45 * _ease(age / 0.12))
            if pick is not None:
                h, w = pick.shape
                x = 1 + (30 - w) // 2
                y = 8 + (14 - h) // 2 + drop
                if shadow:
                    paint(f.px, pick, x + 1, y + 1, (0, 0, 0))
                paint(f.px, pick, x, y, col)
                under = round(w * wa.progress)
                if under > 0:
                    f.hline(x, 23, under, scale(sung, 0.45))
            else:  # a word too long even for 5 px type scrolls while it's sung
                self._marquee(f, clean(text), t, 1, 13 + drop, col)
            prev = words[wa.index - 1].text if wa.index > 0 else ""
            if not prev and i > 0:
                j = i - 1
                while j >= 0 and not entries[j].text:
                    j -= 1
                prev = entries[j].words[-1].text if j >= 0 and entries[j].words else ""
            nxt = words[wa.index + 1].text if wa.index + 1 < len(words) else first_word(i + 1)
            tiny(prev, 1, _lift(scale(sung, 0.35), FLOOR))
            tiny(nxt, 25, _lift(scale(unsung, 0.8), FLOOR))
        if not m.get("playing") and s.pause_style == "auto":
            n_ = 30 if s.show_progress else 32
            f.px[:n_] = (f.px[:n_] * 0.55).astype(np.uint8)
        self._progress(f, m)

    # ------------------------------------------------------------------ art layouts
    def _cover(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        art = self._art_px()
        if art is None:
            self._no_art(f, t, m)
        else:
            f.px[:] = art
        if self.settings.show_progress and (m.get("duration") or 0) > 0:
            self._progress(f, m)

    def _cover_text(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        art = self._art_px()
        if art is None:
            self._no_art(f, t, m)
        else:
            f.px[:] = art
        # graded caption strip: fades from the art into near-black behind the text
        ramp = np.array([0.75, 0.5, 0.3, 0.18, 0.14, 0.14, 0.14, 0.14, 0.14, 0.14], dtype=np.float32)
        f.px[22:] = (f.px[22:].astype(np.float32) * ramp[:, None, None]).astype(np.uint8)
        text = f"{clean(_title(m))} · {self._byline(m)}".strip(" ·")
        if self._glyph(f, m, 1, 24, (150, 150, 170)):
            self._marquee(f, text, t, 8, 24, (255, 255, 255), w=23)
        else:
            self._marquee(f, text, t, 1, 24, (255, 255, 255))
        self._progress(f, m)
        if not m.get("playing") and self.settings.pause_style == "auto":
            f.rect(28, 1, 1, 4, (255, 255, 255))
            f.rect(30, 1, 1, 4, (255, 255, 255))

    def _beat(self) -> float | None:
        a = self._audio()
        if not a:
            return None
        if "beat" in a:
            try:
                return max(0.0, min(1.0, float(a["beat"])))
            except (TypeError, ValueError):
                return None
        bands = a.get("bands") or []
        return float(np.mean(bands[:4])) if len(bands) >= 4 else None

    def _audio(self) -> dict[str, Any] | None:
        if not self._audio_held:
            return None
        try:
            a = self.ctx.provider("audio").value
        except Exception:
            return None
        return a if isinstance(a, dict) and a else None

    def _live_art(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        if self._art is None:
            self._palette_wash(f, t, m, title=False)
            return
        src = self._art.big64
        z = 1.18 + 0.14 * math.sin(2 * math.pi * t / 26.0)  # zoom 1.04 … 1.32
        view = 64.0 / z
        span = (64.0 - view) / 2
        cx = 32.0 + span * 0.9 * math.sin(2 * math.pi * t / 34.0)
        cy = 32.0 + span * 0.9 * math.cos(2 * math.pi * t / 41.0)
        k = view / 32.0
        img = _bilinear(src, cx - view / 2 + _X * k - 0.5, cy - view / 2 + _Y * k - 0.5)
        beat = self._beat()
        breathe = 0.82 + 0.18 * beat if beat is not None else 0.88 + 0.12 * math.sin(2 * math.pi * t / 7.0)
        if not m.get("playing"):
            breathe = 0.9
        f.px[:] = np.clip(img * (breathe * s.art_brightness), 0, 255).astype(np.uint8)

    def _vinyl(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        pos = self._pos()
        # a third of 33 rpm: at the ~10 fps a stream reaches, 33 rpm turned the label 20 deg a frame and
        # its art strobed; 11 rpm (7 deg a frame) reads as a steady spin
        angle = pos * 2 * math.pi * (11.111 / 60.0)
        img = _VINYL.copy()
        if s.art_brightness < 1:
            img *= 0.6 + 0.4 * s.art_brightness
        # label: the art, rotated with the record (nearest-neighbour from the 16 px cover)
        r, th = _VR[_LABEL], _VTH[_LABEL] - angle
        if self._art is not None:
            # bilinear from the 32 px cover: nearest-neighbour from 16 px made the rotating art sparkle
            u = 16.0 + r * np.cos(th) * (16.0 / _LABEL_R) - 0.5
            v = 16.0 + r * np.sin(th) * (16.0 / _LABEL_R) - 0.5
            src = self._art.cover32.astype(np.float32)
            lab = _bilinear(src, u, v) * s.art_brightness
        else:
            pal = self._pal()
            half = np.cos(th) > 0
            lab = np.where(half[:, None], _arr(pal[0]), _arr(pal[1 % len(pal)]))[:, :] * 0.8
            lab = np.where((np.abs(r - 4.5) < 0.6)[:, None], lab * 0.4, lab)
        img[_LABEL] = lab
        img[_HOLE] = 0
        f.px[:] = np.clip(img, 0, 255).astype(np.uint8)
        # tonearm: the stylus moves from the outer groove to the label as the song plays
        dur = m.get("duration") or 0
        prog = max(0.0, min(1.0, pos / dur)) if dur > 0 else 0.3
        beta = _ARM_OUT + (_ARM_IN - _ARM_OUT) * prog
        if not m.get("playing"):
            beta = _ARM_OUT + 0.12  # lifted and parked at the rim
        px0, py0 = _ARM_PIVOT
        sx, sy = px0 + _ARM_LEN * math.cos(beta), py0 + _ARM_LEN * math.sin(beta)
        hx, hy = round(sx), round(sy)
        arm = (170, 170, 188)
        f.line(round(px0) + 1, round(py0), hx + 1, hy, (40, 40, 48))  # shadow on the record
        f.line(round(px0), round(py0), hx, hy, arm)
        f.rect(hx - 1, hy - 1, 3, 2, (225, 225, 240))  # headshell
        f.set(hx - 1, hy + 1, (255, 80, 60) if m.get("playing") else (90, 90, 100))  # stylus light
        f.circle(30, 30, 2, (70, 70, 84))
        f.set(30, 30, (200, 200, 215))

    def _cd(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        # 14 rpm: ~8 deg a frame at 10 fps, a steady spin without the printed art strobing
        angle = self._pos() * 2 * math.pi * (14.0 / 60.0)
        art = self._art.cover32.astype(np.float32) if self._art is not None else None
        kit.cd(f, art, self._pal(), angle, t, s.cd_shine, s.art_brightness)
        self._progress(f, m)

    def _cassette(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        pal = self._pal()
        dur = m.get("duration") or 0
        pos = self._pos()
        prog = max(0.0, min(1.0, pos / dur)) if dur > 0 else 0.5
        if s.cassette_shell == "art":
            shell = _lift(scale(_vivid(pal[0], 0.5), 0.3), 58)
        else:
            shell = kit.SHELLS.get(s.cassette_shell, kit.SHELLS["classic"])
        label = scale(mix(pal[0], (255, 236, 200), 0.62), 0.6)
        ink = (14, 12, 18)
        side = scale(_vivid(pal[0], 0.9), 0.5)

        def marquee(f_: Frame, text: str, tt: float, x: int, y: int, c: Any, w: int) -> None:
            self._marquee(f_, text, tt, x, y, c, w=w)

        # reels turn with the song (they stop when it pauses); 0.45 turns/s reads as a turn, not a flicker
        kit.cassette(f, clean(_title(m)), t, pos * 2 * math.pi * 0.45, prog, shell, label, ink, side, marquee)
        self._progress(f, m)

    def _mosaic(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        g = int(s.mosaic_grid)
        if self._art is not None:
            tiles = art_tiles(self._art, g, s.art_colors, s.dither).astype(np.float32)
            # near-black tiles would read as holes in the wall: keep every tile lit (hue kept)
            mx = tiles.max(axis=-1, keepdims=True)
            tiles = np.where(mx < 40, np.where(mx > 0, tiles * (40 / np.maximum(mx, 1)), 40.0), tiles)
            tiles = tiles * s.art_brightness
            reveal = (t - self._art_t0) / ART_REVEAL_S
        else:  # no cover: a calm two-colour mosaic from the palette
            pal = self._pal()
            yy, xx = np.mgrid[0:g, 0:g]
            pick = ((xx + yy * 2) // max(1, g // 4)) % 2
            c0, c1 = _arr(scale(pal[0], 0.55)), _arr(scale(pal[1 % len(pal)], 0.35))
            tiles = np.where(pick[..., None] == 0, c0, c1) * (0.8 + 0.2 * ((xx + yy) % 2))[..., None]
            reveal = 1.0
        kit.mosaic(f, tiles, t, max(0.0, min(1.0, reveal)), glint=bool(m.get("playing")))
        self._progress(f, m)

    # ------------------------------------------------------------------ info layouts
    def _eq(
        self, f: Frame, pos: float, x: int, y_bottom: int, n: int, w: int, gap: int, h: int, playing: bool
    ) -> None:
        acc = self._accent()
        for i in range(n):
            if playing:
                v = (
                    0.35
                    + 0.3 * math.sin(pos * (6.1 + i * 1.7) + i * 1.9)
                    + 0.25 * math.sin(pos * 2.3 + i * 0.8)
                )
                v += 0.3 * math.exp(-((pos * 2.0) % 1.0) * 5.0) * (1.0 - i / n)
            else:
                v = 0.12
            bh = max(1, min(h, round(v * h)))
            f.rect(x + i * (w + gap), y_bottom - bh + 1, w, bh, scale(acc, 0.55 + 0.45 * (i % 2)))

    def _split(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        if self._art is not None:
            f.px[0:16, 0:16] = (self._art.cover16.astype(np.float32) * s.art_brightness).astype(np.uint8)
        else:
            pal = self._pal()
            f.rect(0, 0, 16, 16, scale(pal[0], 0.25))
            f.text(5, 4, "♪", pal[0], font="small")
        playing = bool(m.get("playing"))
        self._eq(f, self._pos(), 18, 9, 4, 2, 1, 9, playing)
        if s.show_time:
            tt = self._time_text(m)
            f.text_right(30, 11, tt, (150, 150, 170) if measure(tt) <= 14 else (120, 120, 140))
        self._marquee(f, clean(_title(m), "small"), t, 1, 18, (255, 255, 255), font="small")
        self._marquee(f, self._byline(m), t + 0.7, 1, 26, (140, 140, 160))
        self._progress(f, m, y=16 if s.show_time else 31)

    def _minimal(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        acc = self._accent()
        label = str(m.get("source_label") or "") if m.get("playing") else "PAUSED"
        if self._glyph(f, m, 1, 1, scale(acc, 0.55)):
            if label:
                f.text(8, 1, fit(clean(label), 23), scale(acc, 0.55))
        elif label:
            f.text_center(1, clean(label)[:8], scale(acc, 0.55))
        self._marquee(f, clean(_title(m), "small"), t, 1, 8, (255, 255, 255), font="small")
        self._marquee(f, self._byline(m), t + 0.7, 1, 17, (150, 150, 170))
        dur = m.get("duration") or 0
        pos = self._pos()
        if dur > 0:
            c = acc if m.get("playing") else scale(acc, 0.45)
            if s.show_progress:
                f.bar(1, 23, 30, 2, pos / dur, c, track=TRACK)
            if s.show_time:
                if s.time_mode == "remaining":
                    f.text_center(26, "-" + fmt_time(dur - pos), (120, 120, 140))
                else:
                    f.text(1, 26, fmt_time(pos), (140, 140, 160))
                    f.text_right(30, 26, fmt_time(dur), (80, 80, 100))
        elif s.show_time:
            f.text_center(25, fmt_time(pos), (120, 120, 140))

    def _big_title(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        """The song name huge (each font pixel a 2×2 block), artist and time underneath."""
        s = self.settings
        acc = self._accent()
        font = "small" if s.title_size == "huge" else "tiny"
        h = FONTS[font].height * 2
        self._glyph(f, m, 1, 1, scale(acc, 0.6))
        if not m.get("playing"):
            f.rect(28, 1, 1, 5, scale(acc, 0.7))
            f.rect(30, 1, 1, 5, scale(acc, 0.7))
        elif s.show_time:
            f.text_right(30, 1, self._time_text(m), (110, 110, 130))
        title = clean(_title(m), font)
        self._scroll_mask(f, title, font, 2, t, 8 + (14 - h) // 2, self._sung())
        self._marquee(f, self._byline(m), t + 0.7, 1, 24, (150, 150, 170))
        self._progress(f, m)

    def _radio(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        """A backlit dial: each song gets its own station; the needle sweeps there when the song changes."""
        s = self.settings
        band = s.radio_band
        track = self._track(m)
        if self._tuned != (track, band):
            lo = (kit.AM if band == "am" else kit.FM)[0]
            same_band = self._tuned is not None and self._tuned[1] == band
            self._radio_from = self._radio_freq if same_band else lo
            self._radio_to = kit.station(track, band)
            self._radio_t0 = t if self._tuned is not None else t - RADIO_SWEEP_S  # first visit: already tuned
            self._tuned = (track, band)
        p = (t - self._radio_t0) / RADIO_SWEEP_S
        self._radio_freq = self._radio_from + (self._radio_to - self._radio_from) * kit.ease_io(p)
        playing = bool(m.get("playing"))
        lamp = to_rgb(PALETTE["amber"])
        kit.radio_dial(f, self._radio_freq, band, p, playing, lamp, (255, 40, 24))
        text = clean(f"{_title(m)} - {_artist(m)}".strip(" -"), "small")
        self._marquee(f, text, t, 1, 22, (235, 225, 210) if playing else (130, 125, 115), font="small")
        self._progress(f, m, color=lamp)

    def _palette_wash(self, f: Frame, t: float, m: dict[str, Any], title: bool = True) -> None:
        pal = self._pal()
        vivid = [c for c in pal if max(c) - min(c) > 40] or pal
        cols = np.array([_vivid(c) for c in (vivid * 4)[:4]], dtype=np.float32)
        tt = self._pos() if m.get("playing") else self._pos() + t * 0.15
        acc = np.zeros((32, 32, 3), dtype=np.float32)
        tot = np.full((32, 32), 0.04, dtype=np.float32)
        for k in range(4):
            cx = 16 + 12 * math.sin(tt * (0.21 + 0.07 * k) + k * 1.7)
            cy = 16 + 12 * math.cos(tt * (0.17 + 0.05 * k) + k * 2.3)
            wgt = np.exp(-((_X - cx) ** 2 + (_Y - cy) ** 2) / (9.0 + 2 * k) ** 2)
            acc += wgt[..., None] * cols[k]
            tot += wgt
        img = acc / tot[..., None] * (0.6 * self.settings.art_brightness)
        f.px[:] = np.clip(img, 0, 255).astype(np.uint8)
        if title:
            ti = clean(_title(m), "small")
            self._marquee(f, ti, t, 2, 10, (0, 0, 0), font="small")
            self._marquee(f, ti, t, 1, 9, (255, 255, 255), font="small")
            ar = self._byline(m)
            self._marquee(f, ar, t + 0.7, 2, 20, (0, 0, 0))
            self._marquee(f, ar, t + 0.7, 1, 19, (230, 230, 240))
            self._progress(f, m, color=(255, 255, 255))

    def _palette_layout(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        self._palette_wash(f, t, m)

    def _smooth_bars(self, vals: list[float], t: float) -> np.ndarray:
        """Instant attack, even fall: bars glide down instead of dropping whole rows between frames."""
        v = np.asarray(vals, np.float32)
        prev, t0 = getattr(self, "_bars", None), getattr(self, "_bars_t", None)
        if prev is None or t0 is None or prev.shape != v.shape or not 0 < t - t0 < 0.5:
            out = v
        else:
            out = np.maximum(v, prev - FALL * (t - t0))
        self._bars, self._bars_t = out, t
        return out

    def _spectrum_art(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        pal = self._pal()
        art = self._art_px(0.16)
        if art is not None:
            f.px[:] = art
        playing = bool(m.get("playing"))
        bars = 10
        audio = self._audio()
        pos = self._pos()
        if audio and audio.get("bands"):
            groups = np.array_split(np.asarray(audio["bands"], dtype=np.float32), bars)
            vals = [float(g.mean()) if len(g) else 0.0 for g in groups]
            pk = audio.get("peaks") or []
            pgroups = np.array_split(np.asarray(pk, dtype=np.float32), bars) if len(pk) else []
            peaks = [float(g.max()) if len(g) else 0.0 for g in pgroups] if len(pgroups) else vals
        else:
            vals = []
            for b in range(bars):
                v = (
                    0.3
                    + 0.22 * math.sin(pos * (3.1 + b * 0.9) + b * 1.3)
                    + 0.14 * math.sin(pos * 7.7 + b * 2.1)
                )
                v += 0.45 * math.exp(-((pos * 2.0) % 1.0) * 6.0) * max(0.0, 1.0 - b / 4)
                vals.append(max(0.05, min(1.0, v)) if playing else 0.06)
            peaks = [min(1.0, v + 0.08) for v in vals]
        hmax = 21
        base_y = 29
        c0, c1 = _arr(_lift(pal[0], 120)), _arr(_lift(pal[1 % len(pal)], 120))
        cap = mix(pal[2 % len(pal)], (255, 255, 255), 0.4)
        sm = self._smooth_bars(vals, t)
        for b in range(bars):
            x = 1 + b * 3
            hf = max(1.0, float(sm[b]) * hmax)
            h = int(hf)
            for yy in range(h):
                k = yy / max(1, hmax - 1)
                f.rect(x, base_y - yy, 2, 1, tuple(int(v) for v in (c0 * (1 - k) + c1 * k)))
            part = round((hf - h) * 4) / 4  # sub-pixel top: the next row lights in proportion (4 levels)
            if part > 0 and h < hmax:
                k = h / max(1, hmax - 1)
                f.rect(x, base_y - h, 2, 1, tuple(int(v * part) for v in (c0 * (1 - k) + c1 * k)))
            ph = round(max(peaks[b], float(sm[b])) * hmax)
            if ph > h + (1 if part > 0 else 0):
                f.rect(x, base_y - ph, 2, 1, cap)
        self._marquee(f, clean(_title(m)), t, 1, 1, (255, 255, 255))
        self._progress(f, m)

    # ------------------------------------------------------------------ meters
    def _levels(self, pos: float, playing: bool) -> np.ndarray:
        """(left, right) loudness 0..1: system audio when it's captured, else a lively synthetic pair."""
        if not playing:
            return np.zeros(2, np.float32)
        a = self._audio()
        bands = (a or {}).get("bands") or []
        if len(bands) >= 4:
            b = np.asarray(bands, np.float32)
            half = len(b) // 2
            lv = np.array([b[:half].mean(), b[half:].mean() * 1.3], np.float32) * 1.5
            return np.clip(lv, 0.0, 1.0)
        kick = 0.22 * math.exp(-((pos * 2.0) % 1.0) * 5.0)
        out = []
        for ch in (0, 1):
            v = 0.5 + 0.14 * math.sin(pos * 1.7 + ch * 0.9) + 0.1 * math.sin(pos * 5.3 + ch * 2.1)
            v += 0.06 * math.sin(pos * 13.1 + ch) + kick
            out.append(v)
        return np.clip(np.array(out, np.float32), 0.0, 1.0)

    def _vu(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        """Twin VU needles with real ballistics (quick rise, slow fall), or LED ladders with peak hold."""
        s = self.settings
        playing = bool(m.get("playing"))
        tgt = self._levels(self._pos(), playing)
        dt = t - self._vu_t if self._vu_t is not None else -1.0
        if not 0 < dt < 0.5:
            self._vu_lv = tgt.copy()
            self._vu_pk = tgt.copy()
        else:
            k = np.where(tgt > self._vu_lv, 1 - math.exp(-dt * 9.0), 1 - math.exp(-dt * 3.5))
            self._vu_lv = self._vu_lv + (tgt - self._vu_lv) * k
            self._vu_pk = np.maximum(tgt, self._vu_pk - dt * 0.5)
        self._vu_t = t
        lv = (float(self._vu_lv[0]), float(self._vu_lv[1]))
        if s.vu_style == "ladders":
            pk = (float(self._vu_pk[0]), float(self._vu_pk[1]))
            kit.vu_ladders(
                f, lv, pk, (to_rgb(PALETTE["lime"]), to_rgb(PALETTE["amber"]), to_rgb(PALETTE["red"]))
            )
        else:
            kit.vu_needles(f, lv, (150, 98, 22) if playing else (90, 60, 14), (lv[0] > 0.9, lv[1] > 0.9))
        self._marquee(f, clean(_title(m)), t, 1, 24, (215, 215, 228) if playing else (120, 120, 135))
        self._progress(f, m)

    def _waveform(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        """The music as a scrolling waveform: one column per 0.1 s, newest on the right."""
        s = self.settings
        playing = bool(m.get("playing"))
        pos = self._pos()
        a = self._audio()
        bands = (a or {}).get("bands") or []
        if len(bands) >= 4:  # live: keep a history of loudness
            amp = float(np.clip(np.mean(bands) * 1.8, 0.0, 1.0))
            if self._wave_t is None or not 0 <= t - self._wave_t < 1.0:
                self._wave_t = t
            while t - self._wave_t >= 0.1:
                if playing:
                    self._wave = np.roll(self._wave, -1)
                    self._wave[-1] = amp
                self._wave_t += 0.1
            amps = self._wave
        else:  # synthetic: a pure function of the song position, so it scrolls exactly 1 px per 0.1 s
            base = math.floor(pos * 10) / 10
            amps = np.array([_synth_amp(base - (29 - i) * 0.1) for i in range(30)], np.float32)
            if not playing:
                amps = amps * 0.35
        pal = self._pal()
        cols = [_lift(_vivid(pal[0], 0.7), 170), _lift(_vivid(pal[1 % len(pal)], 0.7), 130)]
        kit.waveform(f, amps, cols, s.wave_style)
        self._marquee(f, clean(_title(m)), t, 1, 1, (225, 225, 238) if playing else (120, 120, 135))
        self._progress(f, m)

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        m = self._media().value or {}
        if not m.get("active"):
            return {"active": False, "layout": self._cur_layout, "actions": []}
        lp = self.ctx.provider("lyrics")
        out: dict[str, Any] = {
            "active": True,
            "title": m.get("title"),
            "artist": m.get("artist"),
            "playing": m.get("playing"),
            "album": m.get("album"),
            "source": m.get("source"),
            "source_label": m.get("source_label"),
            "lyrics": lp.status(m.get("title", ""), m.get("artist", "")),
            "art_id": m.get("art_id"),
            "layout": self._cur_layout,
            # the transport buttons the studio shows: hidden where the player can't be controlled
            "actions": ["prev", "toggle", "next"] if m.get("controls", True) else [],
        }
        lyr = self._lyr
        if lyr is not None and len(lyr.entries):
            _, cur, _, _ = lyr.at(self._pos() + self.settings.offset)
            out["line"] = cur
            out["word_synced"] = bool(getattr(lyr, "word_synced", False))
        return out


def _synth_amp(p: float) -> float:
    """A believable loudness envelope for a song position (no audio captured)."""
    v = 0.42 + 0.18 * math.sin(p * 2.3) + 0.12 * math.sin(p * 6.7 + 1.0) + 0.08 * math.sin(p * 17.3)
    v += 0.3 * math.exp(-((p * 2.0) % 1.0) * 5.0)
    return max(0.04, min(1.0, v))


# ------------------------------------------------------------------------------------------------ demo
DEMO_LRC = """[01:08.00]<01:08.00> Golden <01:08.60> hour <01:09.30> on <01:09.60> the <01:09.90> radio <01:11.00>
[01:08.00]Heure dorée à la radio
[01:11.50]Hold me close and turn it up
[01:15.00]We are the song tonight
"""
DEMO_POS = 68.65  # the lyric clock (+0.3 s offset) lands inside "hour"


@lru_cache(maxsize=1)
def demo_art() -> Image.Image:
    """A procedural sunset cover (128²) for previews and layout thumbnails: no files, no network."""
    yy, xx = np.mgrid[0:128, 0:128].astype(np.float32)
    k = (yy / 127.0)[..., None]
    sky = np.array([255, 120, 40], np.float32) * (1 - k) + np.array([150, 20, 120], np.float32) * k
    sun = np.hypot(xx - 64, yy - 70) < 26
    img = np.where(sun[..., None], np.array([255, 214, 90], np.float32), sky)
    hills = yy > 92 + 8 * np.sin(xx / 13.0)
    img = np.where(hills[..., None], np.array([40, 14, 70], np.float32), img)
    for i in range(5):  # sun stripes
        band = (np.abs(yy - (78 + i * 5)) < 1.2) & sun
        img = np.where(band[..., None], sky, img)
    return Image.fromarray(img.clip(0, 255).astype(np.uint8))


class _DemoMedia:
    def __init__(self, art: bool = True, playing: bool = True) -> None:
        self.value: dict[str, Any] = {
            "active": True, "title": "Golden Hour", "artist": "Demo Band", "album": "Summer Tapes",
            "playing": playing, "duration": 214.0, "source": "spotify", "source_label": "MUSIC",
            "track": "Golden Hour\x1fDemo Band", "art_id": "demo" if art else None, "controls": True,
        }  # fmt: skip
        self.position = DEMO_POS
        self.error = None
        self.art = None
        self.art_image = demo_art() if art else None
        self.art_id = "demo" if art else None
        self.palette = extract_palette(self.art_image) if art else None


class _DemoCtx:
    data: ClassVar[dict[str, Any]] = {}
    library = None
    page_theme = None

    def __init__(self, media: _DemoMedia) -> None:
        from ..providers.lyrics import Lyrics, clean_lines, parse_lrc_lines

        lyr = Lyrics(clean_lines(parse_lrc_lines(DEMO_LRC)))

        class _L:
            def get(self, *_: Any, **__: Any) -> Any:
                return lyr

            def status(self, *_: Any) -> str:
                return "found"

        class _A:
            value = None

            def acquire(self) -> None: ...
            def release(self) -> None: ...

        self._p = {"media": media, "lyrics": _L(), "audio": _A()}

    def provider(self, name: str) -> Any:
        return self._p[name]

    def save(self) -> None: ...
    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...


def demo_frame(
    layout: str, t: float = 4.0, *, art: bool = True, playing: bool = True, **settings: Any
) -> Frame:
    """`layout` drawn for the demo song (procedural cover, demo lyrics): previews, thumbnails, tests."""
    media = _DemoMedia(art=art, playing=playing)
    app = NowPlaying(_DemoCtx(media), NowPlayingSettings(layout=layout, **settings))  # type: ignore[arg-type]
    app.render(Frame(), t - 3.0)  # warm up: art, dial and meters settle
    for k in range(5, 0, -1):
        media.position = DEMO_POS - k * 0.1
        app.render(Frame(), t - k * 0.1)
    media.position = DEMO_POS
    f = Frame()
    app.render(f, t)
    return f


@lru_cache(maxsize=64)
def demo_png(layout: str, scale_: int = 4) -> bytes:
    """PNG thumbnail of a layout with the demo song (`GET /api/nowplaying/layouts/{layout}.png`)."""
    return demo_frame(layout).to_png(scale_)

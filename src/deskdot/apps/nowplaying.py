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
========== ===================================================================================

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
from typing import Any

import numpy as np
from PIL import Image, ImageFilter
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Color, register
from ..gfx import Frame, calibrate, mix, scale, to_rgb
from ..gfx.font import FONTS, draw_marquee, measure
from ..platforms import DESKTOP
from ..providers.lyrics import normalize_track
from ..providers.media import decode_art, extract_palette
from ._kit import loading, offline, unsupported

RGB = tuple[int, int, int]
LYRIC_LAYOUTS = ("karaoke", "lyrics", "lyrics_art")
FAST_LAYOUTS = ("karaoke", "lyrics", "lyrics_art", "live_art", "vinyl", "palette", "spectrum_art")
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


def build_art(img: Image.Image, palette: list[RGB] | None = None) -> ArtSet:
    img = img.convert("RGB")
    c32 = np.asarray(calibrate(img.resize((32, 32), Image.Resampling.LANCZOS), "vibrant"), dtype=np.uint8)
    c16 = np.asarray(calibrate(img.resize((16, 16), Image.Resampling.LANCZOS), "vibrant"), dtype=np.uint8)
    b64 = np.asarray(calibrate(img.resize((64, 64), Image.Resampling.LANCZOS), "vibrant"), dtype=np.float32)
    small = img.resize((32, 32), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(2.2))
    blur = np.asarray(calibrate(small, "natural"), dtype=np.float32)
    return ArtSet(c32, c16, b64, blur, palette or extract_palette(img))


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
class NowPlayingSettings(AppSettings):
    layout: str = Choice(
        "karaoke",
        {
            "karaoke": "Karaoke",
            "lyrics": "Synced lyrics",
            "lyrics_art": "Lyrics over art",
            "cover": "Album art",
            "cover_text": "Art + title",
            "live_art": "Living art",
            "vinyl": "Vinyl",
            "split": "Art + info",
            "minimal": "Minimal",
            "palette": "Colour wash",
            "spectrum_art": "Spectrum",
        },
        title="Layout",
    )
    take_over: bool = Field(True, title="Take over while music plays", description="In the playlist")
    offset: float = Field(
        0.3,
        ge=-5,
        le=5,
        title="Lyric offset (s)",
        description="Positive = earlier",
        json_schema_extra={"group": "Lyrics"},
    )
    color: Color = Field(
        "#ffd600", title="Lyric colour", description="Current line in the Synced lyrics layout"
    )
    accent: Color = Field(
        "#00ff8c", title="Accent", description="Progress and equaliser (unless themed from art)"
    )
    fallback_cover: bool = Field(True, title="Show art when no lyrics")
    karaoke_color: Color = Field("#ffd600", title="Sung colour", json_schema_extra={"group": "Lyrics"})
    karaoke_dim: Color = Field("#5a5a78", title="Unsung colour", json_schema_extra={"group": "Lyrics"})
    font: str = Choice(
        "auto",
        {"auto": "Auto (big when it fits)", "small": "Big 7 px", "tiny": "Compact 5 px"},
        title="Lyric size",
        group="Lyrics",
    )
    lyric_align: str = Choice(
        "center", {"center": "Centre", "left": "Left"}, title="Lyric alignment", group="Lyrics"
    )
    show_progress: bool = Field(True, title="Progress bar", json_schema_extra={"group": "Display"})
    show_time: bool = Field(True, title="Show time", json_schema_extra={"group": "Display"})
    time_mode: str = Choice(
        "elapsed", {"elapsed": "Elapsed", "remaining": "Remaining"}, title="Time", group="Display"
    )
    scroll_speed: float = Field(
        12.0, ge=6, le=24, title="Scroll speed (px/s)", json_schema_extra={"group": "Display"}
    )
    idle_screen: str = Choice(
        "no_music",
        {"no_music": "NO MUSIC", "clock": "Clock", "last_art": "Last album art", "nothing": "Nothing"},
        title="When nothing plays",
        group="Display",
    )
    art_brightness: float = Field(
        1.0, ge=0.2, le=1.0, title="Art brightness", json_schema_extra={"group": "Art"}
    )
    art_dim: float = Field(
        0.3, ge=0.05, le=0.7, title="Art behind lyrics", description="Background level for Lyrics over art",
        json_schema_extra={"group": "Art"},
    )  # fmt: skip
    theme_from_art: bool = Field(
        True, title="Colours from album art", description="Sung colour and accent follow the cover's palette",
        json_schema_extra={"group": "Art"},
    )  # fmt: skip
    beat_sync: bool = Field(
        False, title="Pulse with the beat", description="Living art breathes with system audio (starts audio capture)",
        json_schema_extra={"group": "Art"},
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ app
@register
class NowPlaying(App):
    id = "nowplaying"
    name = "Now Playing"
    description = "Spotify / YouTube Music / any player: album art, karaoke lyrics, vinyl, spectrum and more."
    icon = "music"
    category = "media"
    Settings = NowPlayingSettings
    uses = ("media", "lyrics")  # "audio" is acquired on demand (spectrum / beat-synced layouts only)
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
        self._art: ArtSet | None = None
        self._last_art: ArtSet | None = None
        self._lyr: Any = None
        self._rows: dict[tuple[int, str], list[Row]] = {}
        self._audio_held = False
        self._visible = False

    @property  # type: ignore[override]
    def fps(self) -> float:  # type: ignore[override]
        return 10.0 if self.settings.layout in FAST_LAYOUTS else 6.0

    # ------------------------------------------------------------------ lifecycle / scheduling
    def _needs_audio(self) -> bool:
        s = self.settings
        return s.layout == "spectrum_art" or (s.layout == "live_art" and s.beat_sync)

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
        self._sync_audio()

    def on_stop(self) -> None:
        self._visible = False
        self._sync_audio()

    def on_settings(self) -> None:
        self._rows.clear()
        self._lyr = None
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

    def _update_art(self) -> None:
        mp = self._media()
        aid = getattr(mp, "art_id", None)
        if aid == self._art_id:
            return
        self._art_id = aid
        self._art = None
        img = getattr(mp, "art_image", None)
        if img is None and getattr(mp, "art", None):
            img = decode_art(mp.art)
        if img is not None:
            pal = getattr(mp, "palette", None) if getattr(mp, "art_image", None) is not None else None
            try:
                self._art = build_art(img, list(pal) if pal else None)
            except Exception:
                self._art = None
        if self._art is not None:
            self._last_art = self._art

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

    def _marquee(self, f: Frame, text: str, t: float, x: int, y: int, color: Any, font: str = "tiny") -> None:
        """A marquee that moves a whole number of pixels every frame (12 px/s at 10 fps stepped 1-1-1-1-2
        and read as stutter): the speed snaps to a multiple of the frame rate and time to whole frames."""
        fps = self.fps
        step = max(1, round(self.settings.scroll_speed / fps))
        tq = (math.floor(t * fps + 1e-6) + 0.01) / fps
        draw_marquee(f, text, tq, x, y, 30, color, font=font, speed=step * fps)

    # ------------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        mp = self._media()
        m = mp.value
        if m is None:
            if not self.supported_here():
                unsupported(f, "MUSIC")
            elif getattr(mp, "error", None):
                offline(f, "MUSIC", "NO PLAYER")
            else:
                loading(f, t, "MUSIC", self.settings.accent)
            return
        if not m.get("active"):
            self._idle(f, t)
            return
        self._update_art()
        layout = self.settings.layout
        if layout in LYRIC_LAYOUTS:
            lyr = self._lyrics(m)
            if lyr is not None and len(lyr.entries):
                self._lyric_layout(f, t, m, lyr, layout)
                return
            layout = "cover_text" if self.settings.fallback_cover and self._art is not None else "minimal"
        getattr(self, "_palette_layout" if layout == "palette" else f"_{layout}")(f, t, m)
        if not m.get("playing") and layout in ("cover", "live_art", "palette"):
            self._pause_badge(f)

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
        self._stream(f, t, m, lyr, pos, fill=fill, shadow=over_art, sung=current, unsung=unsung)
        if not playing:
            f.px[: 30 if s.show_progress else 32] = (f.px[: 30 if s.show_progress else 32] * 0.55).astype(
                np.uint8
            )
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
    ) -> None:
        """The lyric row stream: focus row pinned near the top, upcoming rows below, eased row scroll."""
        s = self.settings
        font = self._font()
        fh = FONTS["tiny" if font == "tiny" else "small"].height
        big = font != "tiny"
        pitch = fh + (3 if big else 2)
        top = 1 if big else 2
        bottom = 29 if s.show_progress and (m.get("duration") or 0) > 0 else 31
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
        for k, r in enumerate(rows):
            y = round(top + (k - focus) * pitch + slide)
            if y > bottom or y + fh < 0:
                continue
            w = r.w
            if r.line < i or (r.line == i and k < focus):
                fx = float(w)
            elif r.line == i and k == focus:
                fx = r.fill_x(pos) if fill else float(w)
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
                if fill:
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
        artist = clean(_artist(m), "tiny")
        if shadow:
            self._marquee(f, title, t, 2, 10, (0, 0, 0), font="small")
        self._marquee(f, title, t, 1, 9, (255, 255, 255), font="small")
        self._marquee(f, artist, t + 0.6, 1, 20, scale(self._accent(), 0.85))

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
        text = f"{clean(_title(m))} · {clean(_artist(m))}".strip(" ·")
        self._marquee(f, text, t, 1, 24, (255, 255, 255))
        self._progress(f, m)
        if not m.get("playing"):
            f.rect(28, 1, 1, 4, (255, 255, 255))
            f.rect(30, 1, 1, 4, (255, 255, 255))

    def _beat(self) -> float | None:
        if not self._audio_held:
            return None
        try:
            a = self.ctx.provider("audio").value
        except Exception:
            return None
        if not a:
            return None
        if "beat" in a:
            try:
                return max(0.0, min(1.0, float(a["beat"])))
            except (TypeError, ValueError):
                return None
        bands = a.get("bands") or []
        return float(np.mean(bands[:4])) if len(bands) >= 4 else None

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
        self._marquee(f, clean(_artist(m)), t + 0.7, 1, 26, (140, 140, 160))
        self._progress(f, m, y=16 if s.show_time else 31)

    def _minimal(self, f: Frame, t: float, m: dict[str, Any]) -> None:
        s = self.settings
        acc = self._accent()
        label = str(m.get("source_label") or "") if m.get("playing") else "PAUSED"
        if label:
            f.text_center(1, clean(label)[:8], scale(acc, 0.55))
        self._marquee(f, clean(_title(m), "small"), t, 1, 8, (255, 255, 255), font="small")
        self._marquee(f, clean(_artist(m)), t + 0.7, 1, 17, (150, 150, 170))
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
            ar = clean(_artist(m))
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
        audio = None
        if self._audio_held:
            try:
                audio = self.ctx.provider("audio").value
            except Exception:
                audio = None
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

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        m = self._media().value or {}
        if not m.get("active"):
            return {"active": False}
        lp = self.ctx.provider("lyrics")
        out: dict[str, Any] = {
            "active": True,
            "title": m.get("title"),
            "artist": m.get("artist"),
            "playing": m.get("playing"),
            "source": m.get("source"),
            "source_label": m.get("source_label"),
            "lyrics": lp.status(m.get("title", ""), m.get("artist", "")),
            "art_id": m.get("art_id"),
        }
        lyr = self._lyr
        if lyr is not None and len(lyr.entries):
            _, cur, _, _ = lyr.at(self._pos() + self.settings.offset)
            out["line"] = cur
            out["word_synced"] = bool(getattr(lyr, "word_synced", False))
        return out

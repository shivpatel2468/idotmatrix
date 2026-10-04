"""Pet — one character from the sprite library, living on the panel.

"Alive" mode runs a small seeded behaviour loop (idle, wander, sit, nap, snack, wave, hop...) that is
deterministic for a given time but never repeats robotically. With music sync on, the pet dances on the beat
whenever the audio provider hears music.
"""

from __future__ import annotations

import bisect
import math
import random
import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, register
from ..gfx import Frame, measure, mix, scale
from ..gfx.characters import ACCESSORIES, ANIMS, CHARACTERS, draw_character, foot_gap, step_anim_time
from ..platforms import current as current_platform
from ..platforms import only_on

SCENES = {
    "none": "None",
    "grass": "Meadow",
    "room": "Cosy room",
    "night": "Night sky",
    "beach": "Beach",
    "space": "Space",
    "stage": "Stage",
    "snow": "Snow",
}

_CHAR_OPTS = {c.id: c.name for c in CHARACTERS.values()}
_ANIM_OPTS = {"alive": "Alive (auto behaviour)", **{a: a.title() for a in ANIMS}}


CHUNK_SECONDS = 30.0  # baked loop length (240 frames at 8 fps — verified on the panel)
CLIP_FPS = 8.0


class PetSettings(AppSettings):
    character: str = Choice("clawd", _CHAR_OPTS, title="Character")
    animation: str = Choice("alive", _ANIM_OPTS, title="Animation")
    scale: str = Choice("2", {"1": "Small", "2": "Large (2x)"}, title="Size")
    scene: str = Choice("none", SCENES, title="Scene")
    accessory: str = Choice("none", ACCESSORIES, title="Accessory")
    speed: float = Field(1.0, ge=0.25, le=3.0, title="Speed")
    flip: bool = Field(False, title="Face left")
    music_sync: bool = Field(
        False,
        title="Dance to music",
        description="Dance on the beat when music is playing.",
        json_schema_extra=only_on(feature="audio"),
    )
    name: str = Field("", max_length=10, title="Name tag")
    use_custom_colors: bool = Field(False, title="Custom colours", json_schema_extra={"group": "Colours"})
    primary: Color = Field("#ff6024", title="Primary", json_schema_extra={"group": "Colours"})
    secondary: Color = Field("#ffe0b4", title="Secondary", json_schema_extra={"group": "Colours"})
    accent: Color = Field("#1e8cff", title="Accent", json_schema_extra={"group": "Colours"})


# --------------------------------------------------------------------------------------------- behaviour
# (action, weight, min seconds, max seconds)
_ACTIONS: list[tuple[str, float, float, float]] = [
    ("idle", 5.0, 2.5, 5.5),
    ("walk", 5.0, 2.0, 5.0),
    ("run", 0.8, 1.2, 2.2),
    ("sit", 2.0, 3.0, 7.0),
    ("sleep", 1.0, 7.0, 13.0),
    ("eat", 1.2, 3.0, 4.5),
    ("wave", 1.0, 1.6, 2.4),
    ("jump", 1.0, 1.15, 2.3),
    ("happy", 1.0, 1.4, 2.8),
    ("dance", 0.6, 2.5, 4.5),
    ("work", 0.6, 3.0, 6.0),
    ("kick", 0.5, 2.0, 2.0),
]
_W = [a[1] for a in _ACTIONS]


class _Plan:
    """Lazily generated schedule of behaviour segments: (start, end, anim, x0, x1, flip)."""

    def __init__(self, seed: int, lo: float, hi: float) -> None:
        self.rng = random.Random(seed)
        self.lo, self.hi = lo, hi
        self.starts: list[float] = []
        self.segs: list[tuple[float, float, str, float, float, bool]] = []
        self.x = (lo + hi) / 2
        self.flip = False
        self.prev = "idle"

    def _next(self) -> None:
        r = self.rng
        t0 = self.segs[-1][1] if self.segs else 0.0
        while True:
            act, _, a, b = r.choices(_ACTIONS, weights=_W)[0]
            if act != self.prev or act in ("idle", "walk"):
                break
        if act == "sleep" and self.prev not in ("sit", "sleep"):
            act, a, b = "sit", 1.5, 3.0  # settle down before napping
        dur = r.uniform(a, b)
        x0 = x1 = self.x
        if act in ("walk", "run"):
            speed = 5.0 if act == "walk" else 11.0
            span = self.hi - self.lo
            target = r.uniform(self.lo, self.hi)
            if abs(target - self.x) < span * 0.25:  # go somewhere worth walking to
                target = self.lo if self.x > (self.lo + self.hi) / 2 else self.hi
            dur = max(0.8, abs(target - self.x) / speed)
            x1 = target
            self.flip = target < self.x
        elif act == "idle" and r.random() < 0.3:
            self.flip = not self.flip  # look the other way
        self.segs.append((t0, t0 + dur, act, x0, x1, self.flip))
        self.starts.append(t0)
        self.x = x1
        self.prev = act

    def at(self, t: float) -> tuple[str, float, float, bool]:
        """-> (anim, local time, x, flip) at time t."""
        while not self.segs or self.segs[-1][1] <= t:
            self._next()
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        s0, s1, act, x0, x1, fl = self.segs[i]
        u = (t - s0) / max(1e-6, s1 - s0)
        return act, t - s0, x0 + (x1 - x0) * min(1.0, max(0.0, u)), fl


# --------------------------------------------------------------------------------------------- scenes
_RND = [[random.Random(k * 1000 + i).random() for i in range(64)] for k in range(10)]


def _hash(i: int, k: int = 0) -> float:
    """Stable pseudo-random 0..1 for scene details (precomputed, uncorrelated between k)."""
    return _RND[k % 10][i % 64]


def _stars(f: Frame, t: float, n: int, y1: int, bright: int = 200) -> None:
    for i in range(n):
        x, y = int(_hash(i, 1) * 32), int(_hash(i, 2) * y1)
        tw = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * (1.5 + _hash(i, 3) * 2) + i))
        c = round(bright * tw)
        f.set(x, y, (c, c, min(255, c + 30)))


def draw_scene(f: Frame, scene: str, t: float) -> int:
    """Paint the background; returns the ground y (feet line) for the character."""
    if scene == "grass":
        f.gradient_v((8, 22, 60), (40, 90, 150), 0, 26)
        cx = int(t * 1.5) % 44 - 8
        for dx, dy in ((0, 1), (1, 0), (2, 0), (3, 1), (1, 1), (2, 1)):
            f.set(cx + dx, 5 + dy, (150, 170, 200))
        f.rect(0, 26, 32, 6, (20, 100, 28))
        f.hline(0, 26, 32, (60, 170, 50))
        for i in range(7):
            x = int(_hash(i, 5) * 32)
            f.set(x, 25, (60, 170, 50))
            if i % 3 == 0:
                f.set(x + 2, 28 + i % 2, (255, 220, 60))
        return 30
    if scene == "room":
        f.rect(0, 0, 32, 25, (36, 22, 46))
        f.rect(20, 4, 9, 8, (60, 44, 70))
        f.rect(21, 5, 7, 6, (10, 16, 44))
        f.vline(24, 5, 6, (60, 44, 70))
        f.set(22, 6, (200, 200, 230))
        f.rect(0, 25, 32, 7, (80, 44, 20))
        f.hline(0, 25, 32, (120, 70, 30))
        for x in (5, 14, 23):
            f.vline(x, 26, 6, (60, 32, 14))
        f.rect(2, 20, 3, 5, (150, 80, 40))
        f.rect(1, 17, 5, 3, (40, 160, 60))
        return 30
    if scene == "night":
        f.gradient_v((0, 0, 12), (10, 12, 40), 0, 26)
        _stars(f, t, 14, 22)
        f.circle(26, 5, 3, (240, 235, 200))
        f.circle(28, 4, 3, (2, 2, 16))  # bite out of it: a crescent
        f.rect(0, 27, 32, 5, (10, 24, 20))
        f.hline(0, 27, 32, (20, 46, 34))
        return 30
    if scene == "beach":
        f.gradient_v((20, 70, 150), (90, 150, 210), 0, 20)
        f.circle(5, 5, 3, (255, 210, 60))
        f.rect(0, 20, 32, 6, (0, 70, 170))
        for i in range(6):
            x = int((i * 7 + t * 4) % 34) - 1
            f.hline(x, 21 + (i % 3), 3, (120, 200, 255))
        f.rect(0, 26, 32, 6, (220, 180, 100))
        f.hline(0, 26, 32, (240, 220, 160))
        return 30
    if scene == "space":
        _stars(f, t, 22, 32, 230)
        f.circle(27, 5, 4, (140, 60, 200))
        f.hline(22, 5, 11, (220, 140, 255))
        f.rect(0, 27, 32, 5, (70, 70, 85))
        f.hline(0, 27, 32, (120, 120, 140))
        f.set(6, 29, (40, 40, 50))
        f.set(7, 29, (40, 40, 50))
        f.set(20, 30, (40, 40, 50))
        return 30
    if scene == "stage":
        f.clear((8, 4, 14))
        hues = ((255, 40, 120), (40, 160, 255), (255, 200, 0), (60, 255, 120))
        for i in range(4):
            on = (int(t * 2) + i) % 4
            f.rect(3 + i * 8, 0, 3, 2, scale(hues[on], 0.9))
        for y in range(2, 27):
            w = 2 + y // 2
            c = scale((255, 240, 200), 0.16)
            f.hline(16 - w // 2, y, w, c)
        f.rect(0, 27, 32, 5, (50, 26, 14))
        f.hline(0, 27, 32, (150, 90, 40))
        return 30
    if scene == "snow":
        f.gradient_v((6, 10, 40), (30, 40, 90), 0, 27)
        for i in range(16):
            x = int(_hash(i, 7) * 32 + math.sin(t + i) * 1.5) % 32
            y = int((_hash(i, 8) * 32 + t * (4 + _hash(i, 9) * 4)) % 28)
            f.set(x, y, (230, 235, 255))
        f.rect(0, 27, 32, 5, (200, 210, 235))
        f.hline(0, 27, 32, (255, 255, 255))
        return 30
    return 31


# --------------------------------------------------------------------------------------------- the app
@register
class Pet(App):
    id = "pet"
    name = "Pet"
    description = (
        "A pixel pet or character that lives on the panel: wanders, naps, snacks and dances to music."
    )
    icon = "paw-print"
    category = "pets"
    Settings = PetSettings
    fps = 10.0
    # desktop: the pet always holds the audio provider. The web app: audio is acquired only while "Dance to music"
    # is on and the app is visible (like Pet World) — there, holding it asks the browser for the microphone
    uses = ("audio",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._plan: _Plan | None = None
        self._plan_key: tuple = ()
        self._state: dict[str, Any] = {}
        self._clock: tuple[str, str, float, float] | None = None  # (char, anim, anim t, last t)
        self._visible = False
        self._audio_held = False
        if current_platform() == "web":
            self.uses = ()  # acquired by _sync_audio instead

    def _sync_audio(self) -> None:
        if current_platform() != "web":
            return  # desktop / Android: held for the whole run through `uses`
        want = self._visible and self.settings.music_sync
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
        self._plan = None
        self._sync_audio()

    # ------------------------------------------------------------ playback: native loops, live only for music
    def kind(self) -> str:  # type: ignore[override]
        """Baked loops the panel plays natively (smooth, not limited by Bluetooth); stream only while dancing to
        live music, which has to follow the beat in real time."""
        return "stream" if self.settings.music_sync and self._audio()[0] else "clip"

    clip_refresh = 90.0  # see petworld: frequent GIF uploads freeze the panel

    def clip_chunk(self) -> str:
        return str(int(time.time() // CHUNK_SECONDS))

    def clip_frames(self) -> Clip:
        twin = type(self)(self.ctx, self.settings)  # own plan and clocks; the live instance is untouched
        t0 = (time.time() // CHUNK_SECONDS) * CHUNK_SECONDS
        n = round(CHUNK_SECONDS * CLIP_FPS)
        frames = []
        for i in range(n):
            f = Frame()
            twin.render(f, t0 + i / CLIP_FPS)
            frames.append(f)
        return Clip(frames, [round(1000 / CLIP_FPS)] * n)

    # ----------------------------------------------------------- audio
    def _audio(self) -> tuple[bool, float, float | None]:
        """-> (music playing, beat pulse 0..1, bpm or None)."""
        try:
            val = self.ctx.provider("audio").value
        except Exception:
            val = None
        if not isinstance(val, dict):
            return False, 0.0, None
        bands = val.get("bands") or []
        bass = sum(bands[:4]) / 4 if len(bands) >= 4 else 0.0
        beat = val.get("beat")
        pulse = float(beat) if isinstance(beat, (int, float)) else max(0.0, min(1.0, (bass - 0.25) / 0.6))
        level = float(val.get("level") or 0.0)
        bpm = val.get("bpm")
        playing = level > 0.02 or bass > 0.35
        return (
            playing,
            max(0.0, min(1.0, pulse)),
            float(bpm) if isinstance(bpm, (int, float)) and bpm > 0 else None,
        )

    def _colors(self, cid: str) -> dict[str, str] | None:
        s = self.settings
        if not s.use_custom_colors:
            return None
        slots = list(CHARACTERS[cid].slots)
        return dict(zip(slots[:3], (s.primary, s.secondary, s.accent), strict=False))

    # ----------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        cid = s.character if s.character in CHARACTERS else "clawd"
        ch = CHARACTERS[cid]
        sc = 2 if s.scale == "2" else 1
        tt = t * s.speed
        ground = draw_scene(f, s.scene, t)
        box = ch.w * sc
        base_x = (32 - box) // 2
        # small: feet on the scene's ground line; large: the sprite fills the panel, feet on the bottom row
        base_y = ((ground + 1 - ch.h * sc) if sc == 1 else 32 - ch.h * sc) + foot_gap(
            cid
        ) * sc  # feet on the floor

        anim, at, flip, dx = s.animation, tt, s.flip, 0.0
        beat = 0.0
        music = False
        if s.music_sync:
            music, beat, bpm = self._audio()
            if music:
                anim = "dance"
                at = tt * (max(0.5, min(2.0, 1.44 * bpm / 240)) if bpm else 1.0)
        if anim == "alive" and not music:
            span = 8.0 if sc == 1 else 5.0
            key = (cid, sc)
            if self._plan is None or self._plan_key != key:
                self._plan = _Plan(sum(map(ord, cid)) * 7919 + sc, -span, span)
                self._plan_key = key
            anim, at, dx, pflip = self._plan.at(tt % 3600.0)  # the plan repeats hourly; bounded memory
            flip = pflip != s.flip
        if anim not in ch.anims:
            anim = "idle"
        self._state = {"character": ch.name, "animation": anim, "music": music}
        c = self._clock  # pose-stepped: never skip a pose when frames arrive slower than poses change
        if c is not None and c[0] == cid and c[1] == anim and 0 < at - c[3] < 1.0:
            at_pose = step_anim_time(cid, anim, c[2], at - c[3])
        else:
            at_pose = at
        self._clock = (cid, anim, at_pose, at)
        at = at_pose
        draw_character(
            f,
            cid,
            anim,
            at,
            base_x + round(dx),
            base_y,
            colors=self._colors(cid),
            flip=flip,
            scale=sc,
            beat=beat,
            accessory=s.accessory,
        )
        if s.name.strip():
            label = s.name.strip().upper()
            w = measure(label)
            x = (32 - w) // 2
            x0, x1 = max(0, x - 2), min(32, x + w + 2)  # dark pill behind the tag (bounded slice)
            f.px[25:32, x0:x1] = (f.px[25:32, x0:x1] * 0.25).astype("uint8")
            f.text(x, 26, label, mix((255, 255, 255), (255, 214, 0), 0.25))

    def status(self) -> dict[str, Any]:
        return dict(self._state)

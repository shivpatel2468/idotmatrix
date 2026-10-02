"""Pet World — lofi pets living in a little world that scrolls past the panel.

The world is wider than the panel (128 px). Your pet walks between the *stations* of a map (a desk to work
at, a sofa, a food bowl, a bed, a football pitch…) on a seeded itinerary, and the camera follows it. The
clock drives day/night (pets go to bed at night), weather can rain or snow on outdoor maps, and when music
plays every character stops what it's doing and dances to the beat.

Everything is a pure function of `t` (plus the wall clock and provider values), so previews and the panel
agree and nothing accumulates between frames.
"""

from __future__ import annotations

import bisect
import math
import random
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, register
from ..gfx import Frame, mix, scale
from ..gfx.characters import ACCESSORIES, CHARACTERS, GROUPS, draw_character, foot_gap, step_anim_time
from ..platforms import only_on

WORLD_W = 128
GROUND = 27  # y of the floor line: characters' feet stand on it
SPRITE = 16
WALK_SPEED = 6.0  # px/s at pace 1 — exactly 1 px per frame at FPS, so scrolling is even
SHOT_SECONDS = 2.4  # one shot at goal
FPS = 6.0
CHUNK_SECONDS = 24.0  # baked loop length: 192 frames at 8 fps keeps every map under the 40 KB budget
CLIP_FPS = 8.0  # native GIF playback isn't limited by Bluetooth, so loops are smoother than streaming
SLIDE_SECONDS = 0.5  # screen-to-screen slide of the "rooms" camera
RGB = tuple[int, int, int]


# ------------------------------------------------------------------------------------------------ maps
@dataclass(frozen=True)
class Station:
    x: int  # world x of the pet's left edge while here
    anim: str  # what the pet does here ("football" is a two-player mini-game)
    stay: tuple[float, float]  # seconds (min, max)
    face: int = 0  # 1 = look right, -1 = look left, 0 = either
    sleep: bool = False  # where the pet goes at night
    lift: int = 0  # px the pet is raised here, to sit ON furniture (nothing is ever drawn over a pet)


@dataclass(frozen=True)
class MapDef:
    label: str
    outdoor: bool
    stations: tuple[Station, ...]
    desk: bool = False  # "work" happens at furniture drawn in front of the pet


MAPS: dict[str, MapDef] = {
    "home": MapDef(
        "Cosy room",
        False,
        desk=True,
        stations=(
            Station(1, "work", (8, 14), 1, lift=4),  # on the stool, facing the laptop
            Station(51, "sit", (7, 12), 1, lift=3),  # on the sofa cushion
            Station(86, "eat", (4, 7), 1),
            Station(108, "sleep", (6, 10), 1, sleep=True, lift=4),  # on the mattress
            Station(32, "think", (3, 5), 1),
        ),
    ),
    "park": MapDef(
        "Park & pitch",
        True,
        (
            Station(2, "happy", (3, 5), 1),  # screen 0: by the tree
            Station(40, "sit", (6, 10), 1, lift=5, sleep=True),  # screen 1: on the bench
            Station(66, "think", (4, 7), 1),  # screen 2: gazing at the pond
            Station(96, "football", (12, 18)),  # screen 3: shooting practice (fixed screen)
        ),
    ),
    "beach": MapDef(
        "Beach",
        True,
        (
            Station(8, "sleep", (6, 10), 1, sleep=True),
            Station(38, "work", (6, 10), 1),
            Station(80, "football", (12, 16)),
            Station(60, "jump", (3, 5), 1),
        ),
    ),
    "space": MapDef(
        "Space station",
        False,
        (
            Station(8, "work", (8, 12), 1),
            Station(40, "think", (5, 8), 1),
            Station(70, "eat", (4, 7), 1),
            Station(104, "sleep", (6, 10), 0, sleep=True),
            Station(56, "jump", (3, 4), 1),
        ),
    ),
    "city": MapDef(
        "City street",
        True,
        (
            Station(12, "eat", (5, 8), 1),
            Station(44, "idle", (4, 7), -1),
            Station(78, "football", (12, 16)),
            Station(46, "sit", (5, 8), 1, sleep=True),
        ),
    ),
    "cafe": MapDef(
        "Lofi café",
        False,
        (
            Station(8, "work", (8, 12), 1),
            Station(40, "eat", (6, 9), 1),
            Station(66, "sit", (6, 10), 1, sleep=True),
            Station(100, "dance", (6, 9), -1),
        ),
    ),
}

PERIODS = {
    "auto": "Follow the clock",
    "day": "Always day",
    "sunset": "Always sunset",
    "night": "Always night",
}
WEATHER = {"auto": "Live weather", "none": "Clear", "rain": "Rain", "snow": "Snow"}
CHAR_OPTIONS = {k: f"{GROUPS.get(c.group, c.group)} · {c.name}" for k, c in CHARACTERS.items()}
BUDDY_OPTIONS = {"none": "Nobody", **CHAR_OPTIONS}


class PetWorldSettings(AppSettings):
    character: str = Choice("clawd", CHAR_OPTIONS, title="Pet")
    buddy: str = Choice("shiba", BUDDY_OPTIONS, title="Buddy", description="Follows your pet around")
    world: str = Choice("home", {k: m.label for k, m in MAPS.items()}, title="World")
    accessory: str = Choice("none", dict(ACCESSORIES), title="Accessory")
    speed: float = Field(1.0, ge=0.3, le=3.0, title="Pace")
    time_of_day: str = Choice("auto", PERIODS, title="Time of day", group="Mood")
    sleep_at_night: bool = Field(True, title="Sleep at night", json_schema_extra={"group": "Mood"})
    weather: str = Choice("auto", WEATHER, title="Weather", group="Mood")
    lofi: bool = Field(
        True, title="Lofi warmth", description="Warm, soft colours", json_schema_extra={"group": "Mood"}
    )
    music_sync: bool = Field(
        True, title="Dance to music", json_schema_extra=only_on(feature="audio", group="Music")
    )
    show_clock: bool = Field(False, title="Show the time", json_schema_extra={"group": "Mood"})
    wall: Color = Field(
        "#1e4650", title="Wall colour", description="Cosy room", json_schema_extra={"group": "Mood"}
    )
    outline: bool = Field(False, title="Outline characters", description="Easier to see on busy scenery")
    camera: str = Choice(
        "rooms",
        {"rooms": "Screens (scenery stays still)", "follow": "Follow the pet (scrolls)"},
        title="Camera",
        description="Screens look smoother on the LEDs: the world only slides when the pet walks off-screen",
    )


# ---------------------------------------------------------------------------------------------- itinerary
@dataclass(frozen=True)
class Seg:
    t0: float
    t1: float
    x0: float
    x1: float
    anim: str  # "walk" for travel
    face: int


def build_itinerary(world: str, seed: int, visits: int = 24) -> tuple[list[Seg], float]:
    """A seeded loop of walk -> stay -> walk -> stay… through the map's stations."""
    rng = random.Random(seed)
    st = MAPS[world].stations
    segs: list[Seg] = []
    t, x = 0.0, float(st[0].x)
    prev = -1
    for _ in range(visits):
        i = rng.randrange(len(st))
        if i == prev:
            i = (i + 1) % len(st)
        prev = i
        s = st[i]
        if abs(s.x - x) > 0.5:
            dt = abs(s.x - x) / WALK_SPEED
            segs.append(Seg(t, t + dt, x, float(s.x), "walk", 1 if s.x > x else -1))
            t += dt
        stay = rng.uniform(*s.stay)
        face = s.face or rng.choice((1, -1))
        segs.append(Seg(t, t + stay, float(s.x), float(s.x), s.anim, face))
        t += stay
        x = float(s.x)
    # walk home to the first station so the loop is seamless
    if abs(st[0].x - x) > 0.5:
        dt = abs(st[0].x - x) / WALK_SPEED
        segs.append(Seg(t, t + dt, x, float(st[0].x), "walk", 1 if st[0].x > x else -1))
        t += dt
    return segs, t


# ------------------------------------------------------------------------------------------------- sky
SKY: dict[str, tuple[RGB, RGB]] = {
    "day": ((70, 150, 255), (170, 215, 255)),
    "sunset": ((70, 40, 120), (255, 120, 60)),
    "night": ((4, 6, 24), (18, 20, 60)),
}


def period_now(setting: str) -> str:
    if setting != "auto":
        return setting
    h = time.localtime().tm_hour
    if 7 <= h < 17:
        return "day"
    if 17 <= h < 20 or 5 <= h < 7:
        return "sunset"
    return "night"


def _h(k: int) -> float:
    """Stable pseudo-random 0..1."""
    v = math.sin(k * 12.9898 + 78.233) * 43758.5453
    return v - math.floor(v)


# ---------------------------------------------------------------------------------------------- the app
@register
class PetWorld(App):
    id = "petworld"
    name = "Pet World"
    description = "Lofi pets living in a scrolling little world — working, snacking, football, naps, dancing."
    icon = "trees"
    category = "pets"
    Settings = PetWorldSettings
    fps = FPS  # matched to what the BLE link sustains for full-scene frames (~6–7 fps)
    uses = ("weather",)  # audio is acquired only while music sync is on and the app is visible

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._itin: tuple[list[Seg], float, list[float]] | None = None
        self._visible = False
        self._audio_held = False
        self._state: dict[str, Any] = {}
        self._clocks: dict[str, tuple[str, str, float, float]] = {}  # role -> (char, anim, anim t, last t)
        self._n: int | None = None  # frame counter of the frame-stepped clock
        self._baking = False  # True on the twin that renders a loop chunk (plain time, no frame counter)
        self._room = -1  # current screen (world x // 32) for the "rooms" camera
        self._slide: tuple[int, int, float] | None = None  # (from cam, to cam, start t) while sliding

    # ------------------------------------------------------------ lifecycle
    def _sync_audio(self) -> None:
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

    # ------------------------------------------------------------ playback: native loops, live only for music
    def kind(self) -> str:  # type: ignore[override]
        """Baked loops by default: the panel plays GIFs natively and smoothly, while streaming full scenes over
        Bluetooth tops out at ~6 fps. Dancing to live music has to react in real time, so that streams."""
        return "stream" if self.settings.music_sync and self._audio()[0] else "clip"

    # a fresh slice of the day at most every 90 s (the 24 s loop repeats meanwhile): frequent GIF uploads make
    # the panel stop acking and freeze (docs/HARDWARE_PROTOCOL.md #16)
    clip_refresh = 90.0

    def clip_key(self) -> str:
        return f"{super().clip_key()}|{period_now(self.settings.time_of_day)}"

    def clip_chunk(self) -> str:
        return str(int(time.time() // CHUNK_SECONDS))  # a new slice of the pets' day every CHUNK_SECONDS

    def clip_frames(self) -> Clip:
        """Render the next CHUNK_SECONDS of the world on a twin (the live instance keeps its own clocks)."""
        twin = type(self)(self.ctx, self.settings)
        twin._baking = True
        t0 = (time.time() // CHUNK_SECONDS) * CHUNK_SECONDS
        n = round(CHUNK_SECONDS * CLIP_FPS)
        frames = []
        for i in range(n):
            f = Frame()
            twin.render(f, t0 + i / CLIP_FPS)
            frames.append(f)
        return Clip(frames, [round(1000 / CLIP_FPS)] * n)

    def on_stop(self) -> None:
        self._visible = False
        self._sync_audio()

    def on_settings(self) -> None:
        self._itin = None
        self._sync_audio()

    # ------------------------------------------------------------ inputs
    def _itinerary(self) -> tuple[list[Seg], float, list[float]]:
        if self._itin is None:
            s = self.settings
            seed = sum(map(ord, s.character + s.world)) * 7919
            segs, total = build_itinerary(s.world, seed)
            self._itin = (segs, total, [g.t0 for g in segs])
        return self._itin

    def _where(self, t: float) -> tuple[float, str, int, float]:
        """-> (x, anim, face, seconds into this segment)."""
        segs, total, starts = self._itinerary()
        tt = t % total
        i = max(0, bisect.bisect_right(starts, tt) - 1)
        g = segs[i]
        k = (tt - g.t0) / max(1e-6, g.t1 - g.t0)
        return g.x0 + (g.x1 - g.x0) * k, g.anim, g.face, tt - g.t0

    def _audio(self) -> tuple[bool, float]:
        if not self.settings.music_sync:
            return False, 0.0
        try:
            v = self.ctx.provider("audio").value
        except Exception:
            return False, 0.0
        if not isinstance(v, dict):
            return False, 0.0
        bands = v.get("bands") or []
        bass = sum(bands[:4]) / 4 if len(bands) >= 4 else float(v.get("bass") or 0.0)
        beat = v.get("beat")
        pulse = float(beat) if isinstance(beat, (int, float)) else max(0.0, min(1.0, (bass - 0.25) / 0.6))
        music = bool(v.get("music")) if "music" in v else (float(v.get("level") or 0) > 0.03 or bass > 0.35)
        return music, max(0.0, min(1.0, pulse))

    def _weather(self) -> str:
        s = self.settings
        if s.weather != "auto":
            return s.weather
        try:
            v = self.ctx.provider("weather").value
        except Exception:
            return "none"
        code = int((v or {}).get("code") or 0) if isinstance(v, dict) else 0
        if code in (71, 73, 75, 77, 85, 86):
            return "snow"
        if 51 <= code <= 67 or 80 <= code <= 82 or code >= 95:
            return "rain"
        return "none"

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        m = MAPS[s.world]
        # frame-stepped clock: every rendered frame advances the world by exactly one step (even motion on
        # the panel even when the render timer jitters); resync to real time if it drifts by > 0.5 s
        if self._baking:
            tt = t * s.speed
        else:
            n = round(t * FPS) if self._n is None else self._n + 1
            if abs(n / FPS - t) > 0.5:
                n = round(t * FPS)
            self._n = n
            tt = n / FPS * s.speed
        period = period_now(s.time_of_day)
        music, beat = self._audio()
        asleep = s.sleep_at_night and period == "night" and not music

        x, anim, face, into = self._where(tt)
        if asleep:
            bed = next((st for st in m.stations if st.sleep), m.stations[0])
            x, anim, face, into = float(bed.x), "sleep", 1, tt
        football = anim == "football" and not music
        using = None if football or music else anim  # the activity (and furniture) the pet is using right now
        # camera: follow the pet (or frame the whole pitch), clamped to the world
        focus = x + SPRITE / 2
        if football:  # shooting practice happens on one still screen
            cam = int(max(0, min(WORLD_W - 32, (x // 32) * 32)))
            self._room, self._slide = cam // 32, None
        elif s.camera == "follow":
            cam = int(max(0, min(WORLD_W - 32, round(focus - 16))))
            self._room, self._slide = -1, None
        else:
            cam = self._room_camera(focus, tt)

        self._draw_world(f, s.world, cam, tt, period, beat if music else 0.0)
        if s.lofi:  # tint the scenery only; characters stay crisp and true-coloured
            self._lofi(f, period)

        buddy = s.buddy if s.buddy in CHARACTERS else None
        pet = s.character if s.character in CHARACTERS else "clawd"
        y = GROUND - SPRITE + 1
        if football:
            self._football(f, pet, buddy or "footballer", x, cam, into, y, s.accessory)
        else:
            if music:
                anim = "dance"
            elif anim == "work" and m.desk:
                anim = "sit"  # the map draws a real desk + laptop in front; the rig's lap-laptop would cover the face
            pet_anim = anim if anim != "walk" or s.speed < 1.8 else "run"
            if buddy:
                # The buddy rests on the edge of the current screen away from the pet, facing it. A buddy trailing
                # the pet doubled the loop size (its own walk cycle every frame) and cluttered the objects.
                room_x = cam
                pet_mid = x + SPRITE / 2 - room_x
                left_side = pet_mid >= 16
                bx = room_x + (-3 if left_side else 32 - SPRITE + 3)  # peek in from the screen edge
                bface = 1 if left_side else -1
                banim = "sleep" if asleep else "sit"
                if music:
                    banim = "dance"
                bt = self._at("buddy", buddy, banim, tt + 0.37)
                self._char(f, buddy, banim, bt, round(bx) - cam, y, flip=bface < 0, beat=beat)
            pt = self._at("pet", pet, pet_anim, tt)
            seat = self._lift(tt) if using and not asleep else (self._bed_lift() if asleep else 0)
            self._char(
                f,
                pet,
                pet_anim,
                pt,
                round(x) - cam,
                y - seat,
                flip=face < 0,
                beat=beat,
                accessory=s.accessory,
            )

        if m.outdoor:
            self._weather_fx(f, self._weather(), tt)
        if music:
            self._notes(f, tt, beat)
        if s.show_clock:
            now = time.strftime("%H:%M")
            f.rect(31 - 4 * len(now) - 1, 0, 4 * len(now) + 2, 7, (0, 0, 0))
            f.text(31 - 4 * len(now), 1, now, (255, 220, 170))
        self._state = {
            "world": m.label,
            "doing": "dancing" if music else ("sleeping" if asleep else anim),
            "period": period,
            "x": round(x),
        }

    def _char(self, f: Frame, cid: str, anim: str, t: float, x: int, y: int, **kw: Any) -> None:
        """Draw a character standing exactly on the floor (optionally with a 1 px dark outline)."""
        y += foot_gap(cid)  # sprites leave different empty rows under their feet; close that gap
        if not self.settings.outline:
            draw_character(f, cid, anim, t, x, y, **kw)
            return
        layer = Frame()
        draw_character(layer, cid, anim, t, x, y, **kw)
        m = layer.px.any(axis=2)
        if not m.any():
            return
        ring = np.zeros_like(m)
        ring[1:] |= m[:-1]
        ring[:-1] |= m[1:]
        ring[:, 1:] |= m[:, :-1]
        ring[:, :-1] |= m[:, 1:]
        ring &= ~m
        f.px[ring] = (f.px[ring] * 0.25).astype(np.uint8)  # darken, don't paint black: keeps the scene
        f.px[m] = layer.px[m]

    def _lift(self, t: float) -> int:
        """How far the current station raises the pet (onto a stool / cushion / mattress)."""
        segs, total, starts = self._itinerary()
        tt = t % total
        i = max(0, bisect.bisect_right(starts, tt) - 1)
        g = segs[i]
        if g.anim == "walk":
            return 0
        st = next(
            (st for st in MAPS[self.settings.world].stations if st.x == round(g.x0) and st.anim == g.anim),
            None,
        )
        return st.lift if st else 0

    def _bed_lift(self) -> int:
        bed = next((st for st in MAPS[self.settings.world].stations if st.sleep), None)
        return bed.lift if bed else 0

    def _at(self, role: str, cid: str, anim: str, t: float) -> float:
        """Pose-stepped animation time for one character (no skipped poses at the link's frame rate)."""
        prev = self._clocks.get(role)
        if prev is None or prev[0] != cid or prev[1] != anim or not 0 < t - prev[3] < 0.5:
            at = t  # new character/animation, or a jump in time: start in phase with the world clock
        else:
            at = step_anim_time(cid, anim, prev[2], t - prev[3])
        self._clocks[role] = (cid, anim, at, t)
        return at

    def _room_camera(self, focus: float, t: float) -> int:
        """Fixed 32 px screens; a quick eased slide when the pet crosses into the next one."""
        rooms = WORLD_W // 32
        room = int(max(0, min(rooms - 1, focus // 32)))
        if self._room < 0 or abs(t - (self._slide[2] if self._slide else t)) > 30:
            self._room, self._slide = room, None  # first frame / a jump in time: no slide
        elif room != self._room and self._slide is None:
            self._slide = (self._room * 32, room * 32, t)
            self._room = room
        if self._slide is not None:
            a, b, t0 = self._slide
            k = (t - t0) / SLIDE_SECONDS
            if 0 <= k < 1:
                e = k * k * (3 - 2 * k)  # smoothstep
                return round(a + (b - a) * e)
            self._slide = None
        return self._room * 32

    # ------------------------------------------------------------ football mini-game
    def _football(
        self, f: Frame, pet: str, _buddy: str, x: float, cam: int, into: float, y: int, acc: str
    ) -> None:
        """Shooting practice on ONE still screen (a scrolling camera made loops huge and juddery on the panel):
        the pet shoots from the left, the ball arcs into the goal on the right, the net flashes."""
        sx = 1  # pet stands at the left of the screen
        _, ph = divmod(into, SHOT_SECONDS)
        ph /= SHOT_SECONDS
        kick = ph < 0.18
        flight = min(1.0, max(0.0, (ph - 0.12) / 0.5))
        scored = flight >= 1.0
        pet_anim = "kick" if kick else ("happy" if scored and ph < 0.85 else "idle")
        self._char(f, pet, pet_anim, self._at("pet", pet, pet_anim, into), sx, y, accessory=acc)
        # the ball: from the pet's foot to the back of the net, a clean parabola
        bx0, bx1 = sx + 14, 28
        bx = bx0 + (bx1 - bx0) * flight
        by = GROUND - 1 - round(8 * math.sin(math.pi * flight))
        if scored:
            bx, by = bx1, GROUND - 1
        ball = (250, 250, 250)
        f.rect(round(bx) - 1, by - 1, 2, 2, ball)
        f.set(round(bx) - 1, by - 1, (40, 40, 40))
        if not scored:
            f.hline(round(bx) - 1, GROUND + 1, 2, (20, 70, 25))  # shadow
        if scored and ph < 0.85:
            self._goal(f, 120 - cam, "day", flash=0.5 + 0.5 * math.sin(ph * 40))

    # ------------------------------------------------------------ world drawing
    def _draw_world(self, f: Frame, world: str, cam: int, t: float, period: str, pulse: float) -> None:
        getattr(self, f"_w_{world}")(f, cam, t, period, pulse)

    def _sky(self, f: Frame, period: str, t: float, h: int = GROUND, sun_x: int = 24) -> None:
        top, bot = SKY[period]
        # Four flat bands instead of a smooth gradient: classic pixel-art sky, and flat runs compress far better
        # in the changed-rectangle of each GIF frame (a gradient made outdoor loops ~2x bigger than indoor).
        bands = 4
        for k in range(bands):
            y0, y1 = round(k * h / bands), round((k + 1) * h / bands)
            f.rect(0, y0, 32, y1 - y0, mix(top, bot, k / (bands - 1)))
        if period == "night":
            for k in range(22):
                sx, sy = int(_h(k) * 32), int(_h(k + 50) * (h - 6))
                tw = 0.5 + 0.5 * math.sin(t * (1 + _h(k + 9) * 2) + k)
                f.set(sx, sy, scale((255, 255, 230), 0.35 + 0.65 * tw))
            f.circle(25, 5, 2, (240, 240, 210))
            f.circle(26, 4, 2, top)
        elif period == "day":
            f.circle(sun_x, 5, 2, (255, 230, 80))
        else:
            f.circle(sun_x, h - 8, 3, (255, 170, 60))

    def _clouds(self, f: Frame, cam: int, t: float, period: str) -> None:
        col = (255, 255, 255) if period == "day" else (230, 150, 150) if period == "sunset" else (40, 44, 80)
        for k in range(4):
            cx = int((k * 41 + t * (1.5 + k * 0.4)) % 170) - 20 - cam // 4
            cy = 3 + k % 3 * 3
            f.rect(cx, cy, 7, 2, col)
            f.rect(cx + 2, cy - 1, 4, 1, col)

    def _w_home(self, f: Frame, cam: int, t: float, period: str, pulse: float) -> None:
        """The room. Nothing is ever drawn over a pet: stations lift it onto the stool, sofa cushion or mattress."""
        dark = period == "night"
        wall = self.settings.wall if not dark else scale(self.settings.wall, 0.55)
        f.rect(0, 0, 32, GROUND + 1, wall)
        f.rect(0, GROUND - 4, 32, 1, mix(wall, (255, 255, 255), 0.18))  # skirting
        floor = (110, 70, 40) if not dark else (60, 38, 24)
        f.rect(0, GROUND + 1, 32, 5, floor)
        for xx in range(-cam % 8, 32, 8):
            f.vline(xx, GROUND + 1, 5, mix(floor, (0, 0, 0), 0.2))
        o = -cam
        # window onto the sky
        top, bot = SKY[period]
        for yy in range(5, 15):
            f.hline(o + 33, yy, 12, mix(top, bot, (yy - 5) / 9))
        f.rect(o + 32, 4, 14, 12, (200, 170, 130), fill=False)
        f.vline(o + 39, 5, 10, (200, 170, 130))
        f.hline(o + 33, 10, 12, (200, 170, 130))
        if dark:
            f.set(o + 36, 7, (240, 240, 210))
        # TV
        f.rect(o + 74, GROUND - 14, 9, 7, (30, 30, 36))
        glow = mix((60, 120, 220), (220, 120, 60), 0.5 + 0.5 * math.sin(t * 1.3))
        f.rect(o + 75, GROUND - 13, 7, 5, glow)
        f.vline(o + 78, GROUND - 7, 7, (50, 50, 56))
        # lamp
        f.vline(o + 90, GROUND - 16, 16, (80, 80, 90))
        f.rect(o + 88, GROUND - 18, 5, 3, (255, 210, 120) if dark else (230, 200, 150))
        if dark or pulse:
            for dy in range(4):
                for dx in range(-4, 6):
                    f.blend(o + 90 + dx, GROUND - 15 + dy + abs(dx) // 2, (255, 200, 120), 0.12 + 0.2 * pulse)
        # food bowl
        f.rect(o + 103, GROUND - 1, 6, 2, (220, 60, 60))
        f.hline(o + 104, GROUND - 2, 4, (200, 140, 60))
        self._home_desk(f, o, t)
        self._home_sofa(f, o)
        self._home_bed(f, o)

    def _home_desk(self, f: Frame, o: int, t: float) -> None:
        """A stool on the left (the pet sits on it) and the desk to its right with a laptop showing code."""
        f.rect(o + 3, GROUND - 3, 11, 1, (120, 80, 50))  # stool seat
        f.vline(o + 4, GROUND - 2, 3, (90, 60, 38))
        f.vline(o + 12, GROUND - 2, 3, (90, 60, 38))
        wood, edge = (150, 100, 60), (185, 130, 80)
        f.rect(o + 17, GROUND - 8, 15, 2, edge)  # desk top
        f.vline(o + 18, GROUND - 6, 7, wood)  # legs
        f.vline(o + 30, GROUND - 6, 7, wood)
        f.rect(o + 22, GROUND - 16, 8, 7, (60, 64, 76))  # laptop screen, facing the pet
        f.rect(o + 23, GROUND - 15, 6, 5, (20, 40, 70))
        for k in range(3):  # scrolling code lines
            w = 1 + int(_h(k + int(t * 2)) * 4)
            f.hline(o + 24, GROUND - 14 + k * 2, w, (110, 220, 255) if k != 1 else (255, 190, 90))
        f.rect(o + 19, GROUND - 9, 12, 1, (170, 175, 190))  # keyboard deck
        f.rect(o + 18, GROUND - 11, 2, 2, (240, 240, 240))  # coffee mug
        f.set(o + 20, GROUND - 10, (240, 240, 240))

    def _home_sofa(self, f: Frame, o: int) -> None:
        f.rect(o + 47, GROUND - 12, 22, 7, (130, 45, 55))  # back
        f.hline(o + 47, GROUND - 12, 22, (160, 60, 70))
        f.rect(o + 47, GROUND - 5, 22, 3, (175, 70, 80))  # seat cushion (the pet sits on top of it)
        f.rect(o + 47, GROUND - 2, 22, 3, (130, 45, 55))
        f.rect(o + 45, GROUND - 9, 3, 10, (150, 55, 65))  # arms
        f.rect(o + 68, GROUND - 9, 3, 10, (150, 55, 65))

    def _home_bed(self, f: Frame, o: int) -> None:
        f.rect(o + 102, GROUND - 12, 2, 13, (110, 70, 40))  # headboard
        f.rect(o + 104, GROUND - 4, 23, 2, (230, 230, 240))  # mattress (the pet lies on top)
        f.rect(o + 104, GROUND - 2, 23, 3, (90, 110, 200))  # bedspread hanging down the side
        for k in range(0, 23, 4):
            f.set(o + 106 + k, GROUND - 1, (255, 214, 0))
        f.rect(o + 104, GROUND - 6, 5, 2, (250, 250, 255))  # pillow

    def _grass(self, f: Frame, cam: int, period: str) -> None:
        """One clean grass strip for outdoor park-like maps: flat colour, a few tufts, no stray lines."""
        night = period == "night"
        g = (56, 150, 60) if not night else (22, 64, 30)
        f.rect(0, GROUND + 1, 32, 5, g)
        for k in range(0, 128, 7):
            x = k - cam
            if 0 <= x < 32:
                f.set(x, GROUND + 1, mix(g, (255, 255, 255), 0.25))

    def _w_park(self, f: Frame, cam: int, t: float, period: str, pulse: float) -> None:
        """Four still screens: tree, bench, pond, goal. Each object is big, simple and never overlaps a pet."""
        night = period == "night"
        self._sky(f, period, t)
        self._clouds(f, cam, t, period)
        hill = (70, 150, 80) if not night else (18, 44, 28)
        for xx in range(32):  # soft far hills, lighter than the grass so the floor line stays crisp
            hh = 3 + round(2 * math.sin((xx + cam) / 9))
            f.vline(xx, GROUND - hh, hh + 1, mix(hill, SKY[period][1], 0.35))
        self._grass(f, cam, period)
        o = -cam
        leaf = (40, 140, 55) if not night else (20, 60, 30)
        leaf_hi = mix(leaf, (255, 255, 180), 0.25)
        # screen 0: a big tree on the right, pet plays beside it on the left
        f.rect(o + 24, GROUND - 9, 3, 10, (120, 78, 42))  # trunk
        f.circle(o + 25, GROUND - 15, 6, leaf)
        f.circle(o + 23, GROUND - 17, 3, leaf_hi)
        for k in range(3):  # apples
            f.set(o + 21 + k * 3, GROUND - 14 + (k % 2), (230, 50, 50))
        # screen 1: a side-view bench the pet sits ON (lift 5 puts its bottom on the seat)
        wood = (170, 112, 62)
        f.rect(o + 38, GROUND - 5, 20, 2, wood)  # seat
        f.rect(o + 38, GROUND - 11, 20, 2, mix(wood, (0, 0, 0), 0.15))  # backrest
        for lx in (39, 56):
            f.vline(o + lx, GROUND - 3, 4, (70, 70, 78))  # legs
            f.vline(o + lx, GROUND - 11, 6, (70, 70, 78))  # backrest posts
        # screen 2: a round pond in front of the pet, with a lily pad and ripples
        water = (60, 130, 230) if not night else (20, 40, 90)
        for dx in range(-8, 9):
            half = round(2.2 * math.sqrt(max(0.0, 1 - (dx / 8.6) ** 2)))
            f.vline(o + 88 + dx, GROUND + 1, half + 1, water)
        rip = int(t * 2) % 6
        f.hline(o + 85 - rip // 2, GROUND + 2, 3 + rip, mix(water, (255, 255, 255), 0.5))
        f.rect(o + 91, GROUND + 1, 2, 1, (60, 170, 70))  # lily pad
        # screen 3: a goal with a net on the right edge of the last screen
        self._goal(f, o + 120, period)

    def _goal(self, f: Frame, gx: int, period: str, flash: float = 0.0) -> None:
        post = (240, 240, 240) if period != "night" else (150, 150, 160)
        net = mix(post, (0, 0, 0), 0.55)
        for yy in range(GROUND - 9, GROUND + 1, 2):  # net mesh
            f.hline(gx + 1, yy, 6, net)
        for xx in range(gx + 1, gx + 7, 2):
            f.vline(xx, GROUND - 9, 10, net)
        f.vline(gx, GROUND - 10, 11, post)  # front post
        f.hline(gx, GROUND - 10, 7, post)  # crossbar
        if flash:
            for yy in range(GROUND - 9, GROUND + 1):
                for xx in range(gx + 1, gx + 7):
                    f.blend(xx, yy, (255, 214, 0), 0.5 * flash)

    def _pitch(self, f: Frame, o: int, period: str) -> None:
        """Goal for maps whose football station is on the third screen (world x 64..95)."""
        self._goal(f, o + 88, period)

    def _w_beach(self, f: Frame, cam: int, t: float, period: str, pulse: float) -> None:
        self._sky(f, period, t, h=GROUND - 6)
        self._clouds(f, cam, t, period)
        sea = (30, 110, 200) if period != "night" else (10, 30, 70)
        f.rect(0, GROUND - 6, 32, 5, sea)
        for xx in range(32):
            if (xx + cam // 2 + int(t * 4)) % 9 < 2:
                f.set(xx, GROUND - 6 + int(t * 2 + xx) % 2, (220, 240, 255))
        sand = (230, 200, 130) if period != "night" else (90, 80, 55)
        f.rect(0, GROUND - 1, 32, 7, sand)
        o = -cam
        f.vline(o + 18, GROUND - 14, 14, (200, 200, 200))  # umbrella
        for dx in range(-7, 8):
            f.vline(
                o + 18 + dx,
                GROUND - 16 + abs(dx) // 2,
                2,
                (230, 60, 60) if (dx // 3) % 2 else (255, 255, 255),
            )
        f.rect(o + 6, GROUND, 14, 1, (60, 170, 220))  # towel
        f.rect(o + 50, GROUND - 4, 6, 4, (210, 170, 100))  # sandcastle
        f.set(o + 50, GROUND - 5, (210, 170, 100))
        f.set(o + 55, GROUND - 5, (210, 170, 100))
        f.vline(o + 66, GROUND - 16, 16, (140, 90, 50))  # palm
        for dx in range(-5, 6):
            f.set(o + 66 + dx, GROUND - 16 + abs(dx) // 2, (40, 150, 60))
        cx = o + 30 + round(6 * math.sin(t * 0.7))  # crab
        f.rect(cx, GROUND, 3, 1, (230, 80, 50))
        f.set(cx - 1, GROUND - 1, (230, 80, 50))
        f.set(cx + 3, GROUND - 1, (230, 80, 50))
        self._pitch(f, o, period)

    def _w_space(self, f: Frame, cam: int, t: float, period: str, pulse: float) -> None:
        f.rect(0, 0, 32, 32, (22, 24, 34))
        o = -cam
        for wx in (30, 50, 86):  # portholes onto scrolling stars
            f.rect(o + wx, 5, 12, 10, (0, 0, 8))
            for k in range(8):
                sx = o + wx + int((_h(k + wx) * 12 + t * (1 + k % 3)) % 12)
                f.set(sx, 5 + int(_h(k * 3 + wx) * 10), (220, 220, 255))
            f.rect(o + wx, 5, 12, 10, (90, 95, 110), fill=False)
        if 0 <= o + 56 < 32:
            f.circle(o + 55, 11, 2, (80, 150, 255))
        f.rect(0, GROUND + 1, 32, 5, (60, 64, 78))
        for xx in range(-cam % 5, 32, 5):
            f.set(xx, GROUND + 2, (120, 255, 200) if (xx + cam + int(t * 4)) % 15 < 5 else (40, 44, 56))
        f.rect(o + 6, GROUND - 9, 14, 9, (70, 76, 92))  # console
        for k in range(5):
            f.set(o + 8 + k * 2, GROUND - 7, (255, 80, 80) if (k + int(t * 3)) % 4 == 0 else (80, 255, 160))
        f.rect(o + 70, GROUND - 12, 8, 12, (90, 96, 110))  # food dispenser
        f.rect(o + 72, GROUND - 9, 4, 3, (255, 200, 80))
        f.rect(o + 102, GROUND - 5, 22, 5, (60, 90, 140))  # bunk
        f.rect(o + 102, GROUND - 7, 5, 2, (200, 210, 230))

    def _w_city(self, f: Frame, cam: int, t: float, period: str, pulse: float) -> None:
        self._sky(f, period, t)
        night = period == "night"
        for k in range(10):  # parallax skyline
            bx = k * 14 - cam // 2
            bh = 8 + int(_h(k) * 12)
            col = (40, 44, 60) if night else (120, 130, 160)
            f.rect(bx, GROUND - bh, 12, bh, col)
            for wy in range(GROUND - bh + 2, GROUND - 3, 3):
                for wx in range(bx + 2, bx + 11, 3):
                    lit = _h(wx * 31 + wy + k) > (0.45 if night else 0.8)
                    f.set(wx, wy, (255, 210, 110) if lit and night else (200, 220, 240) if lit else col)
        f.rect(0, GROUND + 1, 32, 5, (60, 60, 66))
        for xx in range(-cam % 10, 32, 10):
            f.hline(xx, GROUND + 3, 4, (200, 200, 120))
        o = -cam
        f.rect(o + 6, GROUND - 14, 22, 14, (150, 70, 60))  # café front
        f.rect(o + 8, GROUND - 10, 8, 6, (255, 220, 150) if night else (180, 210, 230))
        for dx in range(0, 22, 2):
            f.set(o + 6 + dx, GROUND - 15, (255, 255, 255) if dx % 4 else (220, 60, 60))
        f.vline(o + 42, GROUND - 12, 13, (90, 90, 100))  # bus stop
        f.rect(o + 40, GROUND - 13, 5, 3, (60, 140, 220))
        f.vline(o + 64, GROUND - 18, 19, (70, 70, 80))  # streetlamp
        f.rect(o + 63, GROUND - 19, 3, 2, (255, 230, 150) if night else (200, 200, 200))
        if night:
            for dy in range(6):
                for dx in range(-3, 4):
                    f.blend(o + 64 + dx, GROUND - 16 + dy * 3, (255, 220, 140), 0.08)
        self._pitch(f, o, period)

    def _w_cafe(self, f: Frame, cam: int, t: float, period: str, pulse: float) -> None:
        wall = (60, 40, 32)
        f.rect(0, 0, 32, GROUND + 1, wall)
        f.rect(0, GROUND + 1, 32, 5, (40, 28, 22))
        for xx in range(-cam % 4, 32, 4):
            f.set(xx, GROUND + 3, (70, 48, 36))
        o = -cam
        for k in range(12):  # string lights
            lx = o + k * 11 + 3
            ly = 3 + (k % 2)
            on = (k + int(t * 2)) % 3 or pulse > 0.6
            f.set(lx, ly, (255, 200, 100) if on else (120, 80, 40))
        f.hline(0, 2, 32, (40, 28, 22))
        f.rect(o + 4, GROUND - 8, 20, 8, (120, 80, 50))  # counter + machine
        f.rect(o + 8, GROUND - 13, 6, 5, (180, 180, 190))
        f.set(o + 10, GROUND - 14 - int(t * 3) % 3, (200, 200, 200))  # steam
        for tx in (38, 52):  # tables
            f.rect(o + tx, GROUND - 6, 8, 1, (150, 100, 60))
            f.vline(o + tx + 4, GROUND - 5, 6, (100, 70, 40))
            f.set(o + tx + 2, GROUND - 7, (240, 240, 240))
        f.rect(o + 64, GROUND - 5, 18, 5, (70, 110, 90))  # sofa
        f.rect(o + 64, GROUND - 9, 18, 4, (55, 90, 72))
        f.rect(o + 94, GROUND - 3, 30, 3, (90, 60, 40))  # stage + mic
        f.vline(o + 118, GROUND - 12, 9, (160, 160, 170))
        f.rect(o + 117, GROUND - 14, 3, 2, (60, 60, 60))
        if pulse:
            for dx in range(-6, 7):
                f.blend(o + 108 + dx, GROUND - 4 - abs(dx), (255, 60, 160), 0.3 * pulse)

    # ------------------------------------------------------------ effects
    def _weather_fx(self, f: Frame, kind: str, t: float) -> None:
        if kind == "rain":
            for k in range(14):
                x = int(_h(k) * 32 + t * 6) % 32
                y = int(_h(k + 20) * 32 + t * 30) % 30
                f.blend(x, y, (150, 180, 255), 0.7)
                f.blend(x, y + 1, (150, 180, 255), 0.4)
        elif kind == "snow":
            for k in range(16):
                x = int(_h(k) * 32 + 2 * math.sin(t + k)) % 32
                y = int(_h(k + 20) * 32 + t * 5) % 30
                f.set(x, y, (240, 240, 255))

    def _notes(self, f: Frame, t: float, beat: float) -> None:
        for k in range(3):
            ph = (t * 0.6 + k / 3) % 1
            x = 4 + k * 10 + round(2 * math.sin(t * 2 + k))
            y = 12 - round(ph * 10)
            col = scale(((255, 90, 200), (0, 220, 255), (255, 214, 0))[k], 0.6 + 0.4 * beat)
            f.vline(x + 1, y - 3, 3, col)
            f.set(x, y, col)
            f.set(x + 2, y - 3, col)

    def _lofi(self, f: Frame, period: str) -> None:
        tint = {"day": (255, 236, 210), "sunset": (255, 210, 190), "night": (200, 190, 255)}[period]
        px = f.px.astype("float32")
        px *= [c / 255 for c in tint]
        f.px[:] = px.clip(0, 255).astype("uint8")

    def status(self) -> dict[str, Any]:
        return dict(self._state)

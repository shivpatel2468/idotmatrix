"""Shared machinery for the self-playing games (see `games.py`).

Every game is an `App` that plays itself with a demo AI and hands control to a human the moment
`action("input", {"key": ...})` arrives, returning to the AI after `HUMAN_IDLE` seconds without input.

Simulation runs on wall time inside `render()` at a fixed step (`step_hz`) with a bounded catch-up, so the
game speed is independent of the stream fps. All game code and pixel art here is original.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
from pydantic import Field, create_model

from ..engine.app import Action, App, AppSettings, Choice
from ..gfx import RGB, Frame, measure, mix, scale
from ..gfx.avatars import AVATARS, draw_avatar
from ..gfx.font import fit

HUMAN_IDLE = 10.0  # seconds without input before the AI takes over again
KEYS = ("up", "down", "left", "right", "a", "b")
KEY_ALIASES = {
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "w": "up",
    "s": "down",
    " ": "a",
    "space": "a",
    "enter": "a",
    "shift": "b",
}
BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)


@dataclass(frozen=True)
class Theme:
    """Colour roles every game maps onto its own elements."""

    p: RGB  # player / primary
    e: RGB  # enemy / secondary
    x: RGB  # hot: projectiles, sparks, highlights
    w: RGB  # walls / structure
    hud: RGB  # score text
    bg: RGB  # background tint (near black)
    r: tuple[RGB, ...]  # 7 colours for bricks, pieces, tiles


THEMES: dict[str, Theme] = {
    "classic": Theme(
        p=(0, 220, 255),
        e=(255, 40, 80),
        x=(255, 214, 0),
        w=(40, 70, 255),
        hud=(255, 255, 255),
        bg=(4, 4, 12),
        r=(
            (255, 30, 30),
            (255, 120, 0),
            (255, 214, 0),
            (40, 230, 60),
            (0, 200, 255),
            (40, 80, 255),
            (170, 60, 255),
        ),
    ),
    "neon": Theme(
        p=(0, 255, 200),
        e=(255, 0, 190),
        x=(255, 255, 90),
        w=(140, 60, 255),
        hud=(120, 255, 240),
        bg=(6, 0, 14),
        r=(
            (255, 0, 190),
            (190, 0, 255),
            (90, 40, 255),
            (0, 150, 255),
            (0, 255, 230),
            (80, 255, 90),
            (255, 40, 110),
        ),
    ),
    "retro": Theme(
        p=(255, 170, 0),
        e=(255, 60, 20),
        x=(255, 236, 140),
        w=(150, 60, 10),
        hud=(255, 200, 90),
        bg=(10, 4, 0),
        r=(
            (255, 50, 20),
            (255, 110, 0),
            (255, 160, 0),
            (255, 210, 50),
            (210, 130, 40),
            (255, 90, 70),
            (240, 190, 110),
        ),
    ),
    "mono": Theme(
        p=(90, 255, 110),
        e=(40, 190, 70),
        x=(210, 255, 210),
        w=(20, 110, 40),
        hud=(140, 255, 150),
        bg=(0, 6, 0),
        r=(
            (40, 255, 80),
            (20, 170, 50),
            (120, 255, 140),
            (60, 210, 90),
            (170, 255, 180),
            (30, 130, 50),
            (90, 230, 110),
        ),
    ),
}
THEME_LABELS = {"classic": "Classic", "neon": "Neon", "retro": "Retro", "mono": "Mono"}


SEAT_RGB: dict[int, RGB] = {1: (0, 200, 255), 2: (255, 60, 90), 3: (80, 255, 120), 4: (255, 200, 0)}
TEAM_RGB: dict[int, RGB] = {0: (0, 200, 255), 1: (255, 60, 90)}  # team A (left), team B (right)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex_rgb(v: Any) -> RGB | None:
    """'#rrggbb' → RGB; anything else → None (phone profiles are already validated; this is a second guard)."""
    if not isinstance(v, str) or not _HEX.match(v):
        return None
    n = int(v[1:], 16)
    return (n >> 16, (n >> 8) & 255, n & 255)


def _hex(c: RGB) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


@dataclass(frozen=True)
class Mode:
    """A way to play a game. `teams`: "solo" (1 player), "coop" (everyone together), "ffa" (every player for
    themselves), "versus" (two teams, picked on the side-select screen — 1v1, 2v1, 2v2…)."""

    id: str
    name: str
    min_players: int = 1
    max_players: int = 1
    teams: str = "solo"
    hint: str = ""


SOLO = Mode("solo", "Solo", 1, 1, "solo")


def _short(n: int) -> str:
    """Score text for the results row: 1234 → 1.2K, 25000 → 25K."""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}K" if n < 10_000 else f"{n // 1000}K"


class GameSettings(AppSettings):
    speed: int = Field(5, ge=1, le=10, title="Speed")
    theme: str = Choice("classic", THEME_LABELS, title="Colours")
    skill: float = Field(0.8, ge=0.0, le=1.0, title="AI skill", description="How well the demo AI plays")
    show_score: bool = Field(True, title="Show score")
    effects: str = Choice(
        "full",
        {
            "full": "Full (particles, shake, flashes)",
            "calm": "Calm (no shake or flashes)",
            "minimal": "Minimal",
        },
        title="Effects",
        group="Graphics",
    )
    intro_outro: bool = Field(True, title="Intro & results screens", json_schema_extra={"group": "Game flow"})
    attract: bool = Field(
        True,
        title="Play itself when idle",
        description="The AI plays while nobody does (great in a playlist)",
        json_schema_extra={"group": "Game flow"},
    )
    pilot: str = Choice(
        "ai",
        {
            "ai": "Built-in AI",
            "fly": "Fruit-fly brain (sees only the pixels; docs/FLY_BRAIN.md)",
        },
        title="Plays itself with",
        group="Game flow",
    )


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def approach(v: float, target: float, step: float) -> float:
    """Move `v` towards `target` by at most `step`."""
    if v < target:
        return min(target, v + step)
    return max(target, v - step)


class Particles:
    """Cheap sparks: position, velocity, life. Drawn as fading single pixels."""

    __slots__ = ("items", "limit")

    def __init__(self, limit: int = 90) -> None:
        self.items: list[list[Any]] = []
        self.limit = limit

    def clear(self) -> None:
        self.items.clear()

    def burst(
        self,
        rng: random.Random,
        x: float,
        y: float,
        color: RGB,
        n: int = 8,
        speed: float = 12.0,
        life: float = 0.6,
        vx: float = 0.0,
        vy: float = 0.0,
        gravity: float = 0.0,
    ) -> None:
        for _ in range(n):
            if len(self.items) >= self.limit:
                self.items.pop(0)
            a = rng.uniform(-1, 1)
            b = rng.uniform(-1, 1)
            k = speed * rng.uniform(0.3, 1.0) / max(0.3, (a * a + b * b) ** 0.5)
            lf = life * rng.uniform(0.6, 1.0)
            self.items.append([x, y, vx + a * k, vy + b * k, lf, lf, color, gravity])

    def emit(self, x: float, y: float, vx: float, vy: float, color: RGB, life: float) -> None:
        if len(self.items) >= self.limit:
            self.items.pop(0)
        self.items.append([x, y, vx, vy, life, life, color, 0.0])

    def update(self, dt: float) -> None:
        keep = []
        for p in self.items:
            p[4] -= dt
            if p[4] <= 0:
                continue
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += p[7] * dt
            keep.append(p)
        self.items = keep

    def draw(self, f: Frame, dx: float = 0.0) -> None:
        for x, y, _vx, _vy, life, total, color, _g in self.items:
            f.set(int(x + dx), int(y), scale(color, 0.25 + 0.75 * life / total))


def shadow_text(f: Frame, x: int, y: int, text: str, color: RGB, font: str = "tiny") -> None:
    """Text with a 1 px black outline so it reads over a busy playfield."""
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        f.text(x + ox, y + oy, text, BLACK, font)
    f.text(x, y, text, color, font)


class GameApp(App):
    """Base class: fixed-step wall-clock simulation, AI/human hand-over, score, best, game-over card."""

    category = "games"
    icon = "gamepad-2"
    fps = 12.0
    Settings = GameSettings
    actions = (Action("restart", "Restart", "rotate-ccw"), Action("demo", "Autoplay", "bot"))
    step_hz: ClassVar[float] = 30.0
    over_hold: ClassVar[float] = 1.8  # seconds the game-over card shows in demo mode
    fx_on_top: ClassVar[bool] = True  # False: the game draws its particles itself (e.g. under the player)
    #: seats a game supports. Seat 1 is the host (keyboard / studio); seats 2..max_players join from phones via the
    #: local-Wi-Fi lobby (deskdot.multiplayer). Any seat without a human is played by the game's AI.
    max_players: ClassVar[int] = 1
    #: controllers that suit this game, best first — the phone controller and Play mode pick the first by default.
    #: "dpad" (4-way buttons + A/B), "joystick" (analog stick), "swipe", "tap" (left/right halves), "gamepad".
    controls: ClassVar[tuple[str, ...]] = ("dpad", "joystick", "swipe", "gamepad")
    #: ways to play (first = default). Single-player games keep the implicit SOLO mode.
    modes: ClassVar[tuple[Mode, ...]] = (SOLO,)
    #: arenas / levels / tracks picked on the home screen: {id: label}. Empty = the game has one map.
    maps: ClassVar[dict[str, str]] = {}
    #: extra colour themes for this game (genre-specific), merged with the shared THEMES. Keep the gameplay
    #: roles (p/e/x) far from `bg`/`w` so nothing camouflages into the background.
    game_themes: ClassVar[dict[str, Theme]] = {}
    game_theme_labels: ClassVar[dict[str, str]] = {}
    _clock: Callable[[], float] = staticmethod(time.monotonic)
    #: the fruit-fly pilot's keys mapped onto this game's (e.g. {"up": "a"}: steering forward fires). See `fly_key`.
    fly_keys: ClassVar[dict[str, str]] = {}
    #: True: standing on the lure triggers the fly's proboscis (feeding) reflex, pressed as "a" (place, drop, open)
    fly_feeds: ClassVar[bool] = False

    def __init_subclass__(cls, **kw: Any) -> None:
        """Give every game a settings form that includes its own modes, maps and themes."""
        super().__init_subclass__(**kw)
        base = cls.__dict__.get("Settings") or cls.Settings
        fields: dict[str, Any] = {}
        if len(cls.modes) > 1:
            fields["mode"] = (
                str,
                Choice(cls.modes[0].id, {m.id: m.name for m in cls.modes}, title="Mode", group="Game"),
            )
        if cls.maps:
            fields["map"] = (str, Choice(next(iter(cls.maps)), cls.maps, title="Map", group="Game"))
        if cls.game_themes:
            labels = {
                **THEME_LABELS,
                **{k: cls.game_theme_labels.get(k, k.replace("_", " ").title()) for k in cls.game_themes},
            }
            default = next(iter(cls.game_themes))
            fields["theme"] = (str, Choice(default, labels, title="Theme"))
        top = max((m.max_players for m in cls.modes), default=1)
        if top > 1:
            fields["players"] = (
                int,
                Field(1, ge=1, le=top, title="Players", json_schema_extra={"group": "Game"}),
            )
        if fields:
            cls.Settings = create_model(f"{cls.__name__}Settings", __base__=base, **fields)  # type: ignore[call-overload]

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        # game flow: attract (AI plays) → home (menu) → teams (side select) → intro → play → outro (results)
        self.flow = "attract"
        self.flow_t = 0.0
        self.menu_row = 0
        s = self.settings
        self.sel: dict[str, Any] = {
            "mode": getattr(s, "mode", self.modes[0].id),
            "players": int(getattr(s, "players", 1)),
            "map": getattr(s, "map", next(iter(self.maps), "")),
            "theme": s.theme,
        }
        self.roster: dict[
            int, dict[str, Any]
        ] = {}  # seat -> {"team": 0|1|None, "human": bool, "ready": bool}
        self.outcome: dict[str, Any] | None = None
        self.hurt_t = 0.0
        self.shake_t = 0.0
        self.rng = random.Random()
        self.fx = Particles()
        self.human_at = -1e9
        self.best = 0
        try:
            self.best = int(self.ctx.data.get("best", 0))
        except Exception:
            self.best = 0
        self.score = 0
        self.over_at: float | None = None
        self.flash = 0.0
        # seat (2..max) -> {"name", "at", "color" (RGB | None), "avatar", "team", "ready"} for phones that joined
        self.seats: dict[int, dict[str, Any]] = {}
        self.lobby_url: str | None = None  # while a lobby is open, the panel shows this as a QR code
        self.join_card: tuple[int, float, str] | None = (
            None  # (seat, since, "JOINED" | "READY") on the QR screen
        )
        self.reset()

    # ------------------------------------------------------------- hooks
    def new_game(self) -> None:
        """Set up a fresh game (score is already 0)."""

    def update(self, dt: float) -> None:
        """Advance the simulation by `dt` game seconds (already scaled by the speed setting)."""

    def draw(self, f: Frame, now: float) -> None:
        """Paint the playfield."""

    def key(self, k: str) -> None:
        """A human key press while the game is running (seat 1, the host)."""

    def key_p(self, k: str, player: int) -> None:
        """A key press from `player` (1 = host, 2..max_players = phones). Single-player games only use seat 1."""
        if player == 1:
            self.key(k)

    def is_human(self, player: int) -> bool:
        """Is `player` controlled by a person right now? Seat 1: recent keys; phones: joined and connected;
        extra players on the host computer (2nd keyboard half / gamepad): recent input, like seat 1."""
        if self.flow == "play" and self.roster:
            r = self.roster.get(player)
            if r is None:
                return False
            if not r["human"]:
                return False
        if player == 1:
            return self.human if self.flow == "attract" or not self.roster else True
        seat = self.seats.get(player)
        if seat is None:
            return False
        if seat.get("local"):
            return self._clock() - seat.get("at", -1e9) < HUMAN_IDLE
        return True

    def lobby_waiting(self) -> bool:
        """True while the lobby is open and seats are still free — the panel shows the join QR code."""
        return self.lobby_url is not None and len(self.seats) < self.max_players - 1

    def best_candidate(self) -> int:
        return self.score

    # ------------------------------------------------------------ helpers
    @property
    def theme(self) -> Theme:
        tid = self.sel.get("theme", self.settings.theme) if hasattr(self, "sel") else self.settings.theme
        return self.game_themes.get(tid) or THEMES.get(tid) or THEMES["classic"]

    # ------------------------------------------------------------ modes / roster (for game code)
    @property
    def play_mode(self) -> Mode:
        mid = self.sel.get("mode") if hasattr(self, "sel") else None
        return next((m for m in self.modes if m.id == mid), self.modes[0])

    @property
    def map_id(self) -> str:
        return str(self.sel.get("map", "")) if hasattr(self, "sel") else ""

    @property
    def n_players(self) -> int:
        """Seats in the current match (humans + AI)."""
        m = self.play_mode
        want = int(self.sel.get("players", 1)) if hasattr(self, "sel") else 1
        return max(m.min_players, min(m.max_players, max(want, len(self.roster))))

    def team_of(self, seat: int) -> int | None:
        r = self.roster.get(seat)
        return None if r is None else r.get("team")

    def seat_colour(self, seat: int) -> RGB:
        """The player's own colour: what a phone player picked, else the seat's default."""
        s = self.seats.get(seat)
        return (s.get("color") if s else None) or SEAT_RGB.get(seat, WHITE)

    def seat_name(self, seat: int) -> str:
        s = self.seats.get(seat)
        return str(s.get("name") or f"P{seat}") if s else f"P{seat}"

    def colour_of(self, seat: int) -> RGB:
        """Seat colour; in team modes the team colour (tinted per seat so teammates stay distinguishable)."""
        t = self.team_of(seat)
        if self.play_mode.teams == "versus" and t is not None:
            rank = sorted(k for k, r in self.roster.items() if r.get("team") == t).index(seat)
            return mix(TEAM_RGB[t], WHITE, 0.45 * rank) if rank else TEAM_RGB[t]
        return self.seat_colour(seat)

    def result(
        self,
        winner_seat: int | None = None,
        winner_team: int | None = None,
        scores: dict[int, int] | None = None,
        text: str | None = None,
    ) -> None:
        """End the match and show the results screen (games call this instead of game_over when they know
        who won). Solo games may keep calling game_over(): the outro then shows score and best."""
        self.outcome = {"seat": winner_seat, "team": winner_team, "scores": scores or {}, "text": text}
        self.game_over()

    def damage(self, strength: float = 1.0) -> None:
        """Damage feedback: a red flash that fades, plus a short screen shake (respects the Effects setting)."""
        fx = self.settings.effects
        if fx == "minimal":
            return
        self.hurt_t = max(self.hurt_t, 0.5 * strength)
        if fx == "full":
            self.shake_t = max(self.shake_t, 0.18 * strength)

    @property
    def mul(self) -> float:
        return 0.5 + 0.1 * self.settings.speed  # speed 5 → 1.0×

    @property
    def skill(self) -> float:
        return float(self.settings.skill)

    @property
    def human(self) -> bool:
        return self._clock() - self.human_at < HUMAN_IDLE

    @property
    def over(self) -> bool:
        return self.over_at is not None

    def reset(self) -> None:
        self.score = 0
        self.over_at = None
        self.flash = 0.0
        self.fx.clear()
        self._last = self._clock()
        self.new_game()

    def game_over(self) -> None:
        if self.over_at is not None:
            return
        self.over_at = self._clock()
        self.record()

    def record(self) -> None:
        cand = int(self.best_candidate())
        if cand > self.best:
            self.best = cand
            try:
                self.ctx.data["best"] = self.best
                self.ctx.save()
            except Exception:
                pass

    def hud(self, f: Frame, text: str, x: int | None = None, y: int = 1, color: RGB | None = None) -> None:
        """Small shadowed score; `x=None` → right-aligned at x 30."""
        if not self.settings.show_score:
            return
        c = color or self.theme.hud
        if x is None:
            x = 31 - measure(text, "tiny")
        shadow_text(f, x, y, text, c)

    # ------------------------------------------------------------ engine
    def advance(self, now: float) -> None:
        dt = 1.0 / self.step_hz
        steps = 0
        max_steps = int(self.step_hz * 0.25) + 1
        while now - self._last >= dt and steps < max_steps:
            self._last += dt
            steps += 1
            self.fx.update(dt)
            self.flash = max(0.0, self.flash - dt)
            if self.over_at is None:
                self.update(dt * self.mul)
        if now - self._last > 0.5:
            self._last = now

    def render(self, f: Frame, t: float) -> None:
        now = self._clock()
        if self.lobby_waiting():
            self.draw_lobby(f, now)
            return
        if self.flow in ("home", "teams", "intro", "outro"):
            self._flow_tick(now)
            if self.flow in ("home", "teams", "intro", "outro"):  # may have moved on to "play"
                getattr(self, f"draw_{self.flow}")(f, now)
                return
        if self.flow == "play":
            if self.over_at is not None and now - self.over_at > 0.9:
                if self.settings.intro_outro:
                    self.flow, self.flow_t = "outro", now
                    self.draw_outro(f, now)
                    return
                self.reset()
        elif self.over_at is not None and now - self.over_at > (3.0 if self.human else self.over_hold):
            self.reset()
        step = min(0.25, max(0.0, now - getattr(self, "_fx_prev", now)))
        self._fx_prev = now
        self.hurt_t = max(0.0, self.hurt_t - step)
        self.shake_t = max(0.0, self.shake_t - step)
        self.advance(now)
        self.draw(f, now)
        if self.fx_on_top:
            self.fx.draw(f)
        self._fly_pilot(f, now)
        self._damage_overlay(f, now)
        if self.flow != "play" and self.over_at is not None and now - self.over_at > 0.45:
            self.draw_card(f, now)

    # ---------------------------------------------------------------- the fruit-fly pilot
    def pilot_anchor(self) -> tuple[float, float] | None:
        """Where seat 1's character is on the panel (x, y), so the fly's eye is centred on its own body.
        Games override this; None = the fly looks at the whole panel."""
        return None

    def fly_lure(self) -> list[tuple[float, float, float]]:
        """Where seat 1's goal is, as smells for the fly: [(x, y, strength 0..1)] in panel pixels (may lie off
        the panel). A *sensory cue* (sugar, an odour plume), not a key press: the fly's brain still decides what
        to do with it, weighted by its `lure` setting (docs/FLY_BRAIN.md). Keep it cheap: called every frame."""
        return []

    def fly_key(self, k: str) -> str | None:
        """Map a key the fly's neurons pressed onto this game's controls (None = ignore it)."""
        return self.fly_keys.get(k, k)

    def _fly_driving(self, now: float) -> bool:
        return (
            getattr(self.settings, "pilot", "ai") == "fly"
            and self.flow == "attract"
            and self.over_at is None
            and now - getattr(self, "_real_human_at", -1e9) > HUMAN_IDLE
        )

    def _player_label(self) -> str:
        now = self._clock()
        fly_recent = now - getattr(self, "_fly_at", -1e9) < HUMAN_IDLE
        real_recent = now - getattr(self, "_real_human_at", -1e9) < HUMAN_IDLE
        flying = getattr(self.settings, "pilot", "ai") == "fly"
        if flying and fly_recent and not real_recent:
            return "fly"
        if not flying and fly_recent and not real_recent:
            return "ai"  # the fly was just taken off this game: the built-in AI is back, not "you"
        return "you" if self.human else "ai"

    def _fly_pilot(self, f: Frame, now: float) -> None:
        """When the fly is the pilot it sees the frame just drawn (pixels only, like a player) and its descending
        neurons press seat 1's keys; a real key press hands control straight back to the person."""
        if not self._fly_driving(now):
            return
        if getattr(self, "_fly", None) is None:
            from ..fly import FlyBrain

            self._fly = FlyBrain(seed=self.rng.randrange(1 << 30))
        try:
            anchor = self.pilot_anchor()
        except Exception:
            anchor = None
        try:
            lures = self.fly_lure() or []
        except Exception:
            lures = []
        fired = self._fly.step(f.px, anchor, lures, feed=self.fly_feeds)
        self._fly_at = now
        self.human_at = now  # the game's own AI stands down while the fly flies, even between spikes
        for k in fired:
            key = self.fly_key(k)
            if key:
                self.key_p(key, 1)

    def fly_telemetry(self, t: float) -> dict[str, Any] | None:
        fly = getattr(self, "_fly", None)
        if fly is None or getattr(self.settings, "pilot", "ai") != "fly":
            return None
        snap = fly.snapshot()
        snap["driving"] = self._fly_driving(self._clock())
        return snap

    def _damage_overlay(self, f: Frame, now: float) -> None:
        if self.hurt_t > 0:
            k = min(1.0, self.hurt_t / 0.5)
            for i in range(3):  # a red vignette, strongest at the edges, fading out
                a = 0.55 * k * (1 - i / 3)
                for x in range(i, 32 - i):
                    f.blend(x, i, (255, 20, 20), a)
                    f.blend(x, 31 - i, (255, 20, 20), a)
                for y in range(i + 1, 31 - i):
                    f.blend(i, y, (255, 20, 20), a)
                    f.blend(31 - i, y, (255, 20, 20), a)
        if self.shake_t > 0:
            dx = 1 if int(now * 60) % 2 else -1
            f.px[:] = np.roll(f.px, dx, axis=1)

    def draw_card(self, f: Frame, now: float) -> None:
        f.dim(0.25)
        f.rect(2, 8, 28, 17, BLACK)
        th = self.theme
        f.rect(2, 8, 28, 1, scale(th.p, 0.6))
        f.rect(2, 24, 28, 1, scale(th.p, 0.6))
        txt = str(self.score)
        f.text_center(10, txt, WHITE, font="small" if len(txt) <= 5 else "tiny")
        best = f"BEST {self.best}"
        f.text_center(18, best if measure(best) <= 30 else str(self.best), th.hud)

    def draw_lobby(self, f: Frame, now: float) -> None:
        """Full-screen join QR code (dark modules on white — what phone cameras scan best)."""
        from .qr import encode

        try:
            m = encode((self.lobby_url or "").encode(), "L")
        except ValueError:
            f.text_center(12, "URL TOO", WHITE)
            f.text_center(19, "LONG", WHITE)
            return
        n = len(m)
        off = (32 - n) // 2
        f.rect(0, 0, 32, 32, (235, 235, 235))
        for y, row in enumerate(m):
            for x, dark in enumerate(row):
                if dark:
                    f.set(off + x, off + y, (0, 0, 0))
        # joined seats blink as dots in the corners, in the colours they picked
        for seat in range(2, self.max_players + 1):
            if seat in self.seats and int(now * 2) % 2 == 0:
                cx, cy = ((31, 0), (0, 31), (31, 31))[(seat - 2) % 3]
                f.set(cx, cy, self.seat_colour(seat))
        card = self.join_card
        if card is not None and card[0] in self.seats and now - card[1] < 1.6:
            self.draw_join_card(f, card[0], card[2])

    def draw_join_card(self, f: Frame, seat: int, label: str) -> None:
        """A phone just joined or got ready: its avatar (the hero), name and state, in the colour it picked."""
        col = self.seat_colour(seat)
        f.clear(BLACK)
        f.rect(0, 0, 32, 1, scale(col, 0.5))
        draw_avatar(f, 8, 2, str(self.seats[seat].get("avatar") or ""), col, zoom=2)
        f.text_center(20, fit(self.seat_name(seat).upper(), 30), col)
        f.text_center(26, label, WHITE if label == "READY" else scale(WHITE, 0.6))

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "input":
            k = str(payload.get("key", "")).lower()
            k = KEY_ALIASES.get(k, k)
            player = int(payload.get("player", 1) or 1)
            if k in KEYS and 1 <= player <= max(1, self.max_players):
                now = self._clock()
                self._prev_human_at = self.human_at
                if player == 1:
                    self._real_human_at = now  # a person, not the fly
                if player == 1:
                    self.human_at = now
                    if self.lobby_waiting() and k == "a":
                        self.lobby_url = None  # start now; phones keep their seats, empty seats are AI
                        self.open_home()
                        return self.status()
                elif player in self.seats:
                    self.seats[player]["at"] = now
                elif payload.get("local"):  # a 2nd keyboard / gamepad on the host computer takes this seat
                    self.seats[player] = {"name": f"P{player}", "at": now, "local": True}
                else:
                    return self.status()  # a phone that isn't seated can't move anything
                if self.flow in ("home", "teams", "intro", "outro"):
                    self._flow_key(k, player, now)
                    return self.status()
                if self.flow == "attract" and player == 1 and k == "b" and not self._was_human(now):
                    self.open_home()  # B = menu: pick mode, players, map, theme
                    return self.status()
                if self.over_at is not None:
                    if now - self.over_at > 0.4:
                        self.reset()
                else:
                    self.key_p(k, player)
        elif name == "seat":  # the lobby seats / unseats a phone player (and carries its profile)
            player = int(payload.get("player", 0))
            if 2 <= player <= self.max_players:
                if payload.get("joined", True):
                    self._seat(player, payload)
                else:
                    self.seats.pop(player, None)
        elif name == "lobby":
            self.lobby_url = payload.get("url") or None
            if not self.lobby_url and not payload.get("keep_seats"):
                self.seats.clear()
        elif name == "restart":
            self.reset()
        elif name == "menu":
            self.open_home()
        elif name == "start":  # the studio can start a match directly with chosen options
            for k2 in ("mode", "players", "map", "theme"):
                if k2 in payload:
                    self.sel[k2] = payload[k2]
            self.begin()
        elif name == "demo":
            self.human_at = -1e9
        elif (
            name == "fly"
        ):  # the studio's roaming fly takes over now (pilot = fly is set by the settings PATCH)
            self.human_at = self._real_human_at = -1e9
            if self.flow != "attract" and not self.lobby_waiting():
                self.flow = "attract"
                self.reset()
        else:
            raise KeyError(name)
        return self.status()

    def _seat(self, player: int, payload: dict[str, Any]) -> None:
        """Store a phone's seat and profile: name, colour, avatar, preferred team, ready (all optional)."""
        now = self._clock()
        prev = self.seats.get(player)
        team = payload.get("team")
        avatar = payload.get("avatar")
        seat = {
            "name": str(payload.get("name") or f"P{player}")[:12],
            "at": now,
            "color": _hex_rgb(payload.get("color")),
            "avatar": avatar if isinstance(avatar, str) and avatar in AVATARS else None,
            "team": team if type(team) is int and team in (0, 1) else None,
            "ready": payload.get("ready") is True,
        }
        self.seats[player] = seat
        if prev is None or prev.get("local"):
            self.join_card = (player, now, "JOINED")
        elif seat["ready"] and not prev.get("ready"):
            self.join_card = (player, now, "READY")
        r = self.roster.get(player)
        if (
            self.flow == "teams"
            and r is not None
            and r["human"]
            and not r["ready"]
            and seat["team"] is not None
        ):
            r["team"] = seat[
                "team"
            ]  # the side picked on the phone moves the player on the side-select screen

    # ================================================================ game flow
    def _was_human(self, now: float) -> bool:
        """Seat 1 was playing just before this key (the key itself already refreshed human_at)."""
        return getattr(self, "_prev_human_at", -1e9) > now - HUMAN_IDLE

    def open_home(self) -> None:
        self.flow, self.flow_t, self.menu_row = "home", self._clock(), 0

    def _menu_rows(self) -> list[str]:
        rows = []
        if len(self.modes) > 1:
            rows.append("mode")
        if self.play_mode.max_players > 1:
            rows.append("players")
        if self.maps:
            rows.append("map")
        rows.append("theme")
        rows.append("start")
        return rows

    def _theme_ids(self) -> list[str]:
        return [*self.game_themes, *THEMES]

    def _cycle(self, key: str, d: int) -> None:
        if key == "mode":
            ids = [m.id for m in self.modes]
            self.sel["mode"] = ids[(ids.index(self.play_mode.id) + d) % len(ids)]
            m = self.play_mode
            self.sel["players"] = max(m.min_players, min(m.max_players, int(self.sel.get("players", 1))))
        elif key == "players":
            m = self.play_mode
            self.sel["players"] = max(m.min_players, min(m.max_players, int(self.sel.get("players", 1)) + d))
        elif key == "map" and self.maps:
            ids = list(self.maps)
            cur = self.map_id if self.map_id in ids else ids[0]
            self.sel["map"] = ids[(ids.index(cur) + d) % len(ids)]
        elif key == "theme":
            ids = self._theme_ids()
            cur = self.sel.get("theme") if self.sel.get("theme") in ids else ids[0]
            self.sel["theme"] = ids[(ids.index(cur) + d) % len(ids)]

    def _humans(self) -> list[int]:
        seats = [1, *sorted(self.seats)]
        return [s for s in seats if s <= max(1, self.play_mode.max_players)]

    def begin(self) -> None:
        """Start a match with the menu's choices: seat people, fill the rest with AI, then side select or intro."""
        m = self.play_mode
        humans = self._humans()
        n = max(m.min_players, min(m.max_players, max(int(self.sel.get("players", 1)), len(humans))))
        self.sel["players"] = n
        self.roster = {}
        for seat in range(1, n + 1):
            human = seat in humans
            team = 0 if m.teams == "coop" else None
            self.roster[seat] = {"team": team, "human": human, "ready": False}
        self.human_at = self._clock()
        if m.teams == "versus" and n > 1:
            # default sides: people alternate left/right (or take the side they picked on the phone), AI fills later
            for i, seat in enumerate([s for s in self.roster if self.roster[s]["human"]]):
                want = self.seats.get(seat, {}).get("team")
                self.roster[seat]["team"] = want if want in (0, 1) else i % 2
            self.flow, self.flow_t = "teams", self._clock()
        else:
            self._start_intro()

    def _fill_teams(self) -> None:
        """AI seats join whichever side is smaller, so a 1v1, 2v1 or 2v2 is always playable."""
        for r in self.roster.values():
            if not r["human"]:
                a = sum(1 for x in self.roster.values() if x["team"] == 0)
                b = sum(1 for x in self.roster.values() if x["team"] == 1)
                r["team"] = 0 if a <= b else 1
        teams = {r["team"] for r in self.roster.values()}
        if teams == {0} or teams == {1}:  # everyone picked the same side: move the last seat over
            last = max(self.roster)
            self.roster[last]["team"] = 1 - self.roster[last]["team"]

    def _start_intro(self) -> None:
        self.outcome = None
        self.reset()
        self.flow, self.flow_t = ("intro" if self.settings.intro_outro else "play"), self._clock()
        self.human_at = self._clock()

    def _flow_tick(self, now: float) -> None:
        el = now - self.flow_t
        if self.flow == "intro" and el > 2.6:
            self.flow, self.flow_t = "play", now
            self._last = now
        elif self.flow == "outro" and el > 8.0:
            self.flow = "home" if self._humans() != [1] or self.human else "attract"
            self.flow_t = now
            if self.flow == "attract":
                self.roster, self.outcome = {}, None
                self.reset()
        elif (
            self.flow in ("home", "teams")
            and now - max(self.human_at, self.flow_t) > 45
            and self.settings.attract
        ):
            self.flow, self.roster = "attract", {}  # nobody touched the menu: back to self-play
            self.reset()

    def _flow_key(self, k: str, player: int, now: float) -> None:
        if self.flow == "home":
            if player != 1:
                return
            rows = self._menu_rows()
            self.menu_row = min(self.menu_row, len(rows) - 1)
            row = rows[self.menu_row]
            if k == "up":
                self.menu_row = (self.menu_row - 1) % len(rows)
            elif k == "down":
                self.menu_row = (self.menu_row + 1) % len(rows)
            elif k in ("left", "right"):
                self._cycle(row, -1 if k == "left" else 1)
            elif k == "a":
                if row == "start":
                    self.begin()
                else:
                    self.menu_row = len(rows) - 1  # jump to START
            elif k == "b":
                self.flow, self.roster = "attract", {}
                self.reset()
        elif self.flow == "teams":
            r = self.roster.get(player)
            if r is None or not r["human"]:
                return
            if k in ("left", "right") and not r["ready"]:
                cur = r["team"]
                if k == "left":
                    r["team"] = 0 if cur in (None, 0) else None
                else:
                    r["team"] = 1 if cur in (None, 1) else None
            elif k == "a" and r["team"] is not None:
                r["ready"] = not r["ready"]
            elif k == "b":
                if r["ready"]:
                    r["ready"] = False
                elif player == 1:
                    self.flow = "home"
            people = [x for x in self.roster.values() if x["human"]]
            if people and all(x["ready"] for x in people):
                self._fill_teams()
                self._start_intro()
        elif self.flow == "intro":
            if k == "a" and now - self.flow_t > 0.6:
                self.flow, self.flow_t = "play", now
                self._last = now
        elif self.flow == "outro":
            if now - self.flow_t < 0.8:
                return
            if k == "a":
                self._start_intro()  # rematch, same sides
            elif k == "b" and player == 1:
                self.open_home()

    # ---------------------------------------------------------------- flow screens (32 × 32)
    def _title(self, f: Frame, y: int = 1) -> None:
        th = self.theme
        f.text_center(y, fit(self.name.upper(), 30), th.hud)
        f.hline(2, y + 7, 28, scale(th.p, 0.5))

    def draw_home(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        self._title(f)
        rows = self._menu_rows()
        vals = {
            "mode": self.play_mode.name.upper(),
            "players": f"{self.sel.get('players', 1)}P",
            "map": str(self.maps.get(self.map_id, next(iter(self.maps.values()), ""))).upper(),
            "theme": (
                self.game_theme_labels.get(self.sel.get("theme"), "")
                or THEME_LABELS.get(self.sel.get("theme"), "")
                or str(self.sel.get("theme", "")).replace("_", " ")
            ).upper(),
            "start": "START",
        }
        # show a window of up to 4 rows around the selection
        first = max(0, min(self.menu_row - 1, len(rows) - 3))
        for i, row in enumerate(rows[first : first + 3]):
            y = 11 + i * 7
            sel = first + i == self.menu_row
            txt = fit(vals[row], 24)
            col = WHITE if sel else scale(th.hud, 0.55)
            if row == "start":
                col = th.x if sel else scale(th.x, 0.5)
            f.text_center(y, txt, col)
            if sel and row != "start" and int(now * 3) % 3:
                f.text(0, y, "<", th.p)
                f.text(29, y, ">", th.p)

    def draw_teams(self, f: Frame, now: float) -> None:
        """FIFA-style side select: each controller moves left/right into a team, A = ready."""
        th = self.theme
        f.clear((0, 0, 0))
        f.rect(0, 0, 11, 32, scale(TEAM_RGB[0], 0.14))
        f.rect(21, 0, 11, 32, scale(TEAM_RGB[1], 0.14))
        f.text(2, 1, "A", TEAM_RGB[0])
        f.text(27, 1, "B", TEAM_RGB[1])
        f.text_center(1, "VS", scale(th.hud, 0.7))
        people = [s for s, r in self.roster.items() if r["human"]]
        for i, seat in enumerate(people[:4]):
            r = self.roster[seat]
            y = 8 + i * 6
            x = {0: 2, None: 12, 1: 22}[r["team"]]
            col = self.seat_colour(seat)
            # a tiny controller glyph: body + two grips, with the seat number
            f.rect(x + 1, y, 6, 3, col)
            f.set(x, y + 2, col)
            f.set(x + 7, y + 2, col)
            f.set(x + 2, y + 1, (0, 0, 0))
            f.set(x + 5, y + 1, (0, 0, 0))
            if r["ready"]:
                f.rect(x, y + 4, 8, 1, WHITE)
            elif int(now * 2) % 2:
                f.set(x - 1 if x > 1 else x + 8, y + 1, col)
        ai = sum(1 for r in self.roster.values() if not r["human"])
        if ai:
            f.text_center(27, f"+{ai} AI", scale(th.hud, 0.5))

    def draw_intro(self, f: Frame, now: float) -> None:
        th = self.theme
        el = now - self.flow_t
        f.clear(th.bg)
        self._title(f, 2)
        f.text_center(12, fit(self.play_mode.name.upper(), 30), scale(th.hud, 0.7))
        # who is playing: coloured dots per seat (team colours in versus)
        seats = sorted(self.roster) or [1]
        x0 = 16 - len(seats) * 2
        for i, seat in enumerate(seats):
            col = self.colour_of(seat)
            f.rect(
                x0 + i * 4, 18, 3, 3, col if self.roster.get(seat, {}).get("human", True) else scale(col, 0.4)
            )
        n = 3 - int(el / 0.6)
        txt = str(n) if n > 0 else "GO"
        c = th.x if n > 0 else (80, 255, 120)
        f.text_center(24, txt, c, font="small")

    def draw_outro(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        o = self.outcome or {}
        if o.get("team") is not None:
            col = TEAM_RGB[o["team"]]
            f.text_center(4, "TEAM " + ("A" if o["team"] == 0 else "B"), col)
            f.text_center(14, "WINS", WHITE)
        elif o.get("seat"):
            col = self.colour_of(o["seat"])
            who = (
                "YOU"
                if o["seat"] == 1 and len([r for r in self.roster.values() if r.get("human")]) <= 1
                else self.seat_name(o["seat"]).upper()
            )
            if measure(who, "small") <= 30:
                f.text_center(4, who, col, font="small")
            else:
                f.text_center(5, fit(who, 30), col)
            f.text_center(14, "WIN" if who == "YOU" else "WINS", WHITE)
        elif o.get("text"):
            f.text_center(8, fit(str(o["text"]).upper(), 30), th.x)
        else:
            f.text_center(4, str(int(self.score)), WHITE, font="small")
            best = f"BEST {self.best}"
            f.text_center(14, best if measure(best) <= 30 else str(self.best), th.hud)
        scores = o.get("scores") or {}
        rows: list[list[tuple[int, str]]] = []
        if scores:
            items = [(int(seat), _short(int(sc))) for seat, sc in sorted(scores.items())[:4]]
            # one row if it fits in 30 px (3 px gaps), otherwise two rows of two
            rows = (
                [items]
                if sum(measure(t) for _, t in items) + 3 * (len(items) - 1) <= 30
                else [items[:2], items[2:]]
            )
            for r, row in enumerate(rows):
                w = sum(measure(t) for _, t in row) + 3 * (len(row) - 1)
                x = 16 - w // 2
                for seat, txt in row:
                    f.text(x, 20 + r * 6, txt, self.colour_of(seat))
                    x += measure(txt) + 3
        if len(rows) < 2 and int(now * 2) % 2:
            f.text_center(26, "A AGAIN", scale(th.hud, 0.55))

    def status(self) -> dict[str, Any]:
        st: dict[str, Any] = {
            "score": int(self.score),
            "best": int(self.best),
            "player": self._player_label(),
        }
        st["flow"] = self.flow
        st["mode"] = self.play_mode.id
        if self.maps:
            st["map"] = self.map_id
        if self.roster:
            st["roster"] = {
                str(k): {"team": v["team"], "human": v["human"], "ready": v["ready"]}
                for k, v in self.roster.items()
            }
        if self.outcome:
            st["outcome"] = {k: v for k, v in self.outcome.items() if k != "scores"}
        if self.max_players > 1:
            st["max_players"] = self.max_players
            st["seats"] = [
                {
                    "seat": n,
                    "human": self.is_human(n),
                    "name": "YOU" if n == 1 else self.seats.get(n, {}).get("name", "AI"),
                    "color": _hex(self.seat_colour(n)),
                    "avatar": self.seats.get(n, {}).get("avatar"),
                    "ready": bool(self.seats.get(n, {}).get("ready")),
                }
                for n in range(1, self.max_players + 1)
            ]
            st["lobby"] = self.lobby_waiting()
        return st


def tint(c: RGB, k: float) -> RGB:
    """Brighten (k > 0 → towards white) or darken (k < 0) a colour."""
    return mix(c, WHITE, k) if k >= 0 else scale(c, 1 + k)

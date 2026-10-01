"""Pokédex — a Pokémon a day (or every few minutes): crisp sprite, number, types, stats and "Who's that?".

Data and sprites come from PokéAPI at runtime via the ``pokedex`` provider (nothing is bundled). One
Pokémon's pages form a deterministic loop, so the app is a *clip*: the whole cycle (portrait → info →
stats, or silhouette → reveal) is baked once into a GIF that the panel plays natively.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import time
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..providers.pokedex import GENERATIONS, Sprite32, normalize_key
from ._kit import loading, offline

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)
BAKE_FPS = 10.0  # the fastest GIF rate verified on the panel
MAX_CLIP_FRAMES = 160

# LED-tuned type colours (the official palette is too pastel for LEDs) and 3-letter badges
TYPES: dict[str, tuple[RGB, str]] = {
    "normal": ((190, 190, 140), "NOR"),
    "fire": ((255, 80, 0), "FIR"),
    "water": ((30, 110, 255), "WAT"),
    "electric": ((255, 214, 0), "ELE"),
    "grass": ((50, 220, 40), "GRA"),
    "ice": ((110, 230, 255), "ICE"),
    "fighting": ((210, 30, 20), "FIG"),
    "poison": ((170, 40, 220), "POI"),
    "ground": ((225, 160, 50), "GRO"),
    "flying": ((130, 140, 255), "FLY"),
    "psychic": ((255, 40, 140), "PSY"),
    "bug": ((150, 210, 0), "BUG"),
    "rock": ((180, 150, 50), "ROC"),
    "ghost": ((110, 60, 210), "GHO"),
    "dragon": ((90, 40, 255), "DRA"),
    "dark": ((120, 85, 60), "DAR"),
    "steel": ((150, 165, 200), "STE"),
    "fairy": ((255, 110, 210), "FAI"),
}
STATS: tuple[tuple[str, RGB], ...] = (
    ("HP", (255, 40, 40)),
    ("ATK", (255, 130, 0)),
    ("DEF", (255, 214, 0)),
    ("SPA", (40, 140, 255)),
    ("SPD", (90, 230, 40)),
    ("SPE", (255, 50, 190)),
)
STAT_FULL = 180  # a base stat that fills the bar (most are below; 255 max)
TRACK: RGB = (46, 46, 64)  # stat-bar track: bright enough to survive the panel's gamma 1.5
FADE_IN = 0.4  # seconds a page takes to fade in from black (pages cut through black, never pop)
FADE_OUT = 0.3
FLASH = 0.3  # the reveal flash (tinted gold, never full-panel white)


class PokedexSettings(AppSettings):
    mode: str = Choice(
        "daily",
        {"daily": "Pokémon of the day", "random": "Random", "specific": "Specific"},
        title="Which Pokémon",
        group="Pokémon",
    )
    pokemon: str = Field(
        "pikachu",
        max_length=30,
        title="Name or number",
        description="Used in Specific mode: pikachu, 25, mr-mime…",
        json_schema_extra={"group": "Pokémon"},
    )
    generation: str = Choice(
        "all",
        {k: ("All generations" if k == "all" else f"Gen {k}") for k in GENERATIONS},
        title="Generation",
        group="Pokémon",
    )
    every: int = Field(
        120, ge=10, le=3600, title="New random every (s)", json_schema_extra={"group": "Pokémon"}
    )
    shiny: str = Choice(
        "off",
        {"off": "Normal", "on": "Shiny", "rare": "Rare shiny (1 in 16)"},
        title="Colours",
        group="Pokémon",
    )
    view: str = Choice(
        "cycle",
        {
            "cycle": "Card → info → stats",
            "portrait": "Portrait",
            "info": "Info",
            "stats": "Stats",
            "who": "Who's that Pokémon?",
        },
        title="Show",
        group="Display",
    )
    page_seconds: int = Field(
        6, ge=2, le=60, title="Seconds per page", json_schema_extra={"group": "Display"}
    )
    guess_seconds: int = Field(
        6, ge=2, le=60, title="Who's that: seconds to guess", json_schema_extra={"group": "Display"}
    )
    units: str = Choice(
        "metric", {"metric": "Metric", "imperial": "Imperial"}, title="Units", group="Display"
    )


def pick_id(seed: str, generation: str) -> int:
    lo, hi = GENERATIONS.get(generation, GENERATIONS["all"])
    return random.Random(seed).randint(lo, hi)


def bake(app: App, seconds: float, fps: float = BAKE_FPS, limit: int = MAX_CLIP_FRAMES) -> Clip:
    """Sample `render()` over one loop and merge identical consecutive frames (a long hold costs one frame).

    If the loop still has more than `limit` distinct frames, it is re-sampled at a lower rate, so timing
    stays exact (holds keep their length; only fast motion gets coarser).
    """
    rate = fps
    while True:
        n = max(1, round(seconds * rate))
        ms = 1000 / rate
        frames: list[Frame] = []
        ends: list[float] = []
        for i in range(n):
            f = Frame()
            app.render(f, i / rate)
            if frames and f == frames[-1]:
                ends[-1] = (i + 1) * ms
            else:
                frames.append(f)
                ends.append((i + 1) * ms)
        if len(frames) <= limit or rate <= 1.0:
            break
        rate = max(1.0, rate * 0.7)
    frames, ends = frames[:limit], ends[:limit]
    ends[-1] = seconds * 1000
    starts = [0.0, *ends[:-1]]
    return Clip(frames, [max(20, round(e - s)) for s, e in zip(starts, ends, strict=True)])


def fade(f: Frame, t: float, length: float) -> None:
    """Fade a page in from black at its start and out at its end, in a few even steps (a small GIF palette)."""
    k = min(1.0, (t + 0.1) / FADE_IN, (length - t) / FADE_OUT)
    if k < 1.0:
        k = max(0.0, round(k * 4) / 4)
        f.px[:] = (f.px.astype(np.float32) * k).astype(np.uint8)


def draw_sprite(f: Frame, sp: Sprite32, x: int, y: int, color: RGB | None = None) -> None:
    """Blit a sprite; `color` paints the silhouette instead of its pixels."""
    if color is None:
        f.blit(sp.px, x, y, sp.mask)
    else:
        px = np.empty_like(sp.px)
        px[:] = color
        f.blit(px, x, y, sp.mask)


def type_badge(f: Frame, x: int, y: int, w: int, t: str) -> None:
    """A rounded pill: dark tint of the type colour with a bright label (full name when it fits)."""
    col, abbr = TYPES.get(t, ((140, 140, 160), t[:3].upper()))
    f.rect(x + 1, y, w - 2, 7, scale(col, 0.3))
    f.rect(x, y + 1, w, 5, scale(col, 0.3))
    label = t.upper() if measure(t.upper()) <= w - 4 else abbr
    f.text(x + (w - measure(label)) // 2, y + 1, label, mix(col, WHITE, 0.45))


@register
class Pokedex(App):
    id = "pokedex"
    name = "Pokédex"
    description = "Pokémon of the day or a random one: crisp sprite, types, stats and Who's that Pokémon."
    icon = "sparkles"
    category = "pets"
    Settings = PokedexSettings
    uses = ("pokedex",)
    fps = 4.0
    clip_fps = BAKE_FPS
    clip_colors = 64
    actions = (Action("next", "Another one", "shuffle"), Action("shiny", "Toggle shiny", "sparkles"))

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._clock = time.time
        self._bump = 0  # "next" presses
        self._shiny_flip = False
        yy, xx = np.mgrid[:32, :32]
        ang = np.arctan2(yy - 17.5, xx - 15.5)
        self._rays = (np.floor((ang + math.pi) / (2 * math.pi) * 14) % 2).astype(bool)
        self._dist = np.hypot(yy - 17.5, xx - 15.5)

    # ------------------------------------------------------------ which one
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("pokedex")
        except KeyError:
            return None

    def _period(self) -> int:
        return int(self._clock() // self.settings.every)

    def key(self, offset: int = 0) -> str:
        s = self.settings
        if s.mode == "specific" and not self._bump:
            return normalize_key(s.pokemon) or "25"
        if s.mode == "daily" and not self._bump:
            return str(pick_id(dt.date.today().isoformat(), s.generation))
        seed = f"{self._period() + offset}:{self._bump}" if s.mode == "random" else f"bump:{self._bump}"
        return str(pick_id(seed, s.generation))

    def is_shiny(self, e: dict[str, Any]) -> bool:
        s = self.settings.shiny
        on = s == "on" or (
            s == "rare" and random.Random(f"shiny:{e['id']}:{self._period()}").random() < 1 / 16
        )
        return on != self._shiny_flip

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            keys = [self.key()]
            if self.settings.mode == "random":
                keys.insert(0, self.key(1))  # prefetch the next one
            p.want(*keys)

    def on_settings(self) -> None:
        self._bump = 0
        self._shiny_flip = False
        self.on_start()

    def entry(self) -> dict[str, Any] | None:
        p = self._provider()
        if p is None:
            return None
        k = self.key()
        e = p.get(k)
        if e is None or (self.settings.mode == "random" and p.get(self.key(1)) is None):
            self.on_start()
        return e

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "next":
            self._bump += 1
        elif name == "shiny":
            self._shiny_flip = not self._shiny_flip
        else:
            raise KeyError(name)
        self.on_start()
        self.ctx.invalidate()
        return self.status()

    # ------------------------------------------------------------ output
    def _pages(self) -> list[str]:
        v = self.settings.view
        if v == "cycle":
            return ["portrait", "info", "stats1", "stats2"]
        if v == "stats":
            return ["stats1", "stats2"]
        return [v]

    def loop_seconds(self) -> float:
        s = self.settings
        if s.view == "who":
            return s.guess_seconds + s.page_seconds
        return s.page_seconds * len(self._pages())

    def kind(self) -> Kind:
        return "clip" if self.entry() is not None else "stream"

    def clip_key(self) -> str:
        e = self.entry()
        shiny = self.is_shiny(e) if e else False
        return super().clip_key() + f"#{e['id'] if e else self.key()}:{shiny}"

    def clip_frames(self) -> Clip:
        return bake(self, self.loop_seconds())

    def render(self, f: Frame, t: float) -> None:
        e = self.entry()
        if e is None:
            p = self._provider()
            if p is not None and (p.failed(self.key()) or (p.error and not p.value)):
                offline(f, "POKEDEX", "NOT FOUND" if p.failed(self.key()) else "OFFLINE")
            else:
                loading(f, t, "POKEDEX", PALETTE["red"])
            return
        s = self.settings
        tt = t % self.loop_seconds()
        if s.view == "who":
            self._who(f, e, tt)
            fade(f, tt, self.loop_seconds())
            return
        pages = self._pages()
        page = pages[int(tt // s.page_seconds) % len(pages)]
        pt = tt % s.page_seconds
        {"portrait": self._portrait, "info": self._info, "stats1": self._stats, "stats2": self._stats}[page](
            f, e, pt, page
        )
        if len(pages) > 1:
            fade(f, pt, float(s.page_seconds))

    # ------------------------------------------------------------ pages
    def _sprite(self, e: dict[str, Any], size: str) -> Sprite32 | None:
        sprites = e.get("shiny") if self.is_shiny(e) else e.get("sprites")
        sprites = sprites or e.get("sprites")
        return sprites.get(size) if sprites else None

    def _name(self, f: Frame, e: dict[str, Any], y: int, t: float, color: RGB = WHITE) -> None:
        draw_marquee(f, e["name"], t, 1, y, 30, color, speed=12.0)

    def _portrait(self, f: Frame, e: dict[str, Any], t: float, _page: str = "") -> None:
        sp = self._sprite(e, "hero")
        sx, sy = ((32 - sp.w) // 2, 24 - sp.h) if sp is not None else (0, 0)
        if sp is not None:
            draw_sprite(f, sp, sx, sy)

        def free(x0: int, x1: int, y1: int) -> bool:  # does the sprite leave this top corner empty?
            if sp is None:
                return True
            m = sp.mask[max(0, 0 - sy) : max(0, y1 + 1 - sy), max(0, x0 - sx) : max(0, x1 + 1 - sx)]
            return not m.any()

        # number + type pips in the top corners, only where the sprite leaves room (never cut the art)
        num = f"{e['id']}"
        if free(0, measure(num) + 1, 6):
            f.text(1, 1, num, PALETTE["mute"])
        n = len(e["types"][:2])
        if not free(30 - 4 * n, 31, 4):
            n = 0
        x = 30
        for ty in reversed(e["types"][:n]):
            col = TYPES.get(ty, ((140, 140, 160), ""))[0]
            f.rect(x - 2, 1, 3, 3, col)
            x -= 4
        if self.is_shiny(e) and n:
            f.set(x, 2, PALETTE["gold"])
            f.set(x - 1, 1, scale(PALETTE["gold"], 0.5))
        f.hline(0, 25, 32, BLACK)
        self._name(f, e, 26, t)

    def _info(self, f: Frame, e: dict[str, Any], t: float, _page: str = "") -> None:
        sp = self._sprite(e, "small")
        if sp is not None:
            draw_sprite(f, sp, (16 - sp.w) // 2, 1 + (15 - sp.h) // 2)
        types = e["types"][:2]
        for i, ty in enumerate(types):
            type_badge(f, 16, 1 + i * 8 if len(types) > 1 else 5, 15, ty)
        self._name(f, e, 18, t)
        genus = e.get("genus") or ""
        if genus:
            draw_marquee(f, genus, t, 1, 25, 30, PALETTE["mute"], speed=12.0)
        else:
            f.text_center(25, self._size_text(e), PALETTE["mute"])

    def _size_text(self, e: dict[str, Any]) -> str:
        h, w = e.get("height", 0) / 10, e.get("weight", 0) / 10  # m, kg
        if self.settings.units == "imperial":
            ft = h * 3.28084
            return f"{int(ft)}'{round((ft % 1) * 12)} {round(w * 2.20462)}LB"
        return f"{h:.1f}M {w:.0f}KG" if w >= 10 else f"{h:.1f}M {w:.1f}KG"

    def _stats(self, f: Frame, e: dict[str, Any], t: float, page: str = "stats1") -> None:
        base = 0 if page == "stats1" else 3
        vals = e.get("stats") or [0] * 6
        for row in range(3):
            label, col = STATS[base + row]
            v = int(vals[base + row])
            y = 1 + row * 11
            f.text(1, y, label, PALETTE["mute"])
            f.text_right(30, y, str(v), WHITE)
            k = min(1.0, v / STAT_FULL)
            # bars grow in over the first half second of the page
            grow = min(1.0, t / 0.5)
            f.rect(1, y + 7, 30, 2, TRACK)
            f.rect(1, y + 7, max(1, round(30 * k * grow)), 2, col)
        if page == "stats2":
            total = sum(int(v) for v in vals)
            f.set(31, 31, scale(WHITE, min(1.0, total / 720)))  # total hint in the corner

    def _burst(self, f: Frame, t: float, dim: float = 1.0) -> None:
        a = np.array((40, 120, 255), np.float32) * dim
        b = np.array((0, 40, 170), np.float32) * dim
        glow = np.clip(1.2 - self._dist / 22, 0.35, 1.0)[..., None]
        px = np.where(self._rays[..., None], a, b) * glow
        f.px[:] = px.astype(np.uint8)

    def _who(self, f: Frame, e: dict[str, Any], t: float) -> None:
        s = self.settings
        sp = self._sprite(e, "who")
        guess = s.guess_seconds
        revealed = t >= guess
        self._burst(f, t, 0.55 if revealed else 1.0)
        if sp is not None:
            x, y = (32 - sp.w) // 2, 28 - sp.h
            if revealed:
                draw_sprite(f, sp, x, y)
            else:
                draw_sprite(f, sp, x, y, BLACK)
        if not revealed:
            k = 0.5 + 0.5 * math.sin(t * 5)
            f.rect(25, 1, 6, 9, BLACK)
            f.text(26, 2, "?", mix(PALETTE["gold"], WHITE, k * 0.5), font="small")
            # countdown along the bottom edge, shrinking smoothly: the last pixel dims with the remainder
            w = 32 * max(0.0, 1 - t / guess)
            n = int(w)
            f.hline(0, 31, n, PALETTE["gold"])
            part = round((w - n) * 4) / 4
            if part > 0:
                f.set(n, 31, scale(PALETTE["gold"], part))
            return
        rt = t - guess
        if rt < FLASH:  # reveal flash, tinted towards gold (a full-panel white flash is blinding on LEDs)
            a = 0.5 * (1 - rt / FLASH)
            gold = np.array(PALETTE["gold"], np.float32)
            f.px[:] = (f.px.astype(np.float32) * (1 - a) + gold * a).astype(np.uint8)
        f.rect(0, 25, 32, 7, BLACK)
        self._name(f, e, 26, rt, PALETTE["gold"])

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        e = self.entry()
        if not e:
            return {"pokemon": self.key(), "loaded": False}
        return {"id": e["id"], "name": e["name"], "types": e["types"], "shiny": self.is_shiny(e)}

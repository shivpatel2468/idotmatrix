"""Space — next launch countdown, live ISS tracker, people in orbit and spaceflight news.

Screens (``mode``): ``launch`` · ``iss`` · ``people`` · ``news`` · ``rotate`` (cycles all four).

* Launch: the T-minus ticks locally from the cached NET (Launch Library 2 is polled at most every 15 min), with
  the provider and a GO/TBC/TBD/HOLD status light. The last minute shows the rocket venting on its pad; when T-0
  passes it lifts off (for 10 minutes, then the next launch takes over).
* ISS: a follow-cam half-globe (or the whole world) with the day/night terminator computed from the sun's
  position, the trailing ground track, the modelled track ahead, you, and a paged readout (altitude, speed,
  next pass over you, distance).
* People: how many humans are in orbit right now, one figure per person coloured by station, and who.
* News: Spaceflight News API headlines, wrapped and paged with their source and age.

Everything is drawn from provider values; the countdown and pages are functions of the wall clock and `t`.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale, to_rgb
from ..gfx.color import RGB
from ..gfx.frame import Sprite
from ..gfx.worldmap import land, project
from ..providers.sky import subsolar_point
from ..providers.space import LAUNCH_FILTERS
from ._kit import loading, offline

SCREENS = ("launch", "iss", "people", "news")
LIFTOFF_S = 600.0  # show the liftoff scene this long after T-0
FINAL_S = 60.0  # the pad scene for the last minute
EXACT = {"SEC", "MIN", ""}  # NET precisions a to-the-second countdown makes sense for
PAGE_S = 2.6  # dwell per caption page that fits
SCROLL = 10.0  # px/s for captions that don't fit (the app streams at 10 fps while one moves)
HOLD_S = 1.2
GAP = 12
TEXT_W = 30  # x = 1 .. 30

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
SHADE: RGB = PALETTE["shade"]

STATUS_COL: dict[str, RGB] = {
    "GO": PALETTE["ok"],
    "TBC": PALETTE["amber"],
    "TBD": PALETTE["mute"],
    "HOLD": PALETTE["bad"],
    "FLIGHT": PALETTE["cyan"],
    "SUCCESS": PALETTE["ok"],
    "FAILURE": PALETTE["bad"],
    "PARTIAL": PALETTE["amber"],
}
STATUS_WORD = {
    "GO": "GO FOR LAUNCH",
    "TBC": "TO BE CONFIRMED",
    "TBD": "DATE TBD",
    "HOLD": "ON HOLD",
    "FLIGHT": "IN FLIGHT",
    "SUCCESS": "SUCCESS",
    "FAILURE": "FAILURE",
    "PARTIAL": "PARTIAL FAILURE",
}
STATION_COL: dict[str, RGB] = {"ISS": PALETTE["cyan"], "TIANGONG": PALETTE["rose"]}

# header labels that fit next to the status light (<= 25 px)
HEADER_ABBR = {
    "ROCKETLAB": "RKTLAB",
    "ROSCOSMOS": "ROSCOS",
    "BLUE ORIGIN": "BLUE",
    "GALACTIC": "GALACT",
    "LANDSPACE": "LANDSP",
    "NORTHROP": "NG",
    "FIREFLY": "FIREFL",
    "RELATIVITY": "RELATIV",
    "SPACEPIONEER": "PIONEER",
    "ORIENSPACE": "ORIEN",
    "GILMOUR": "GILMOUR",
    "CAS SPACE": "CAS",
}

ROCKET = Sprite.parse(
    [
        "..w..",
        ".www.",
        ".wcw.",
        ".www.",
        ".www.",
        ".wew.",
        ".www.",
        "ewwwe",
        "e.g.e",
    ],
    {"w": (235, 235, 245), "c": PALETTE["cyan"], "e": PALETTE["ember"], "g": (90, 90, 110)},
)
ASTRONAUT = Sprite.parse(
    [
        "..www..",
        ".wwwww.",
        ".wgggw.",
        ".wgggw.",
        "..www..",
        ".wwwww.",
        "wwwwwww",
        "w.wbw.w",
        "..w.w..",
        "..w.w..",
    ],
    {"w": (225, 225, 235), "g": PALETTE["gold"], "b": PALETTE["sky"]},
)

# world grids (land mask, pixel-centre latitude and longitude in radians) per map size
_MAPS: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def _grid(w: int, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if (w, h) not in _MAPS:
        lon = (np.arange(w) + 0.5) / w * 360.0 - 180.0
        lat = 90.0 - (np.arange(h) + 0.5) / h * 180.0
        _MAPS[(w, h)] = (land(w, h), np.radians(lat)[:, None], np.radians(lon)[None, :])
    return _MAPS[(w, h)]


# ------------------------------------------------------------------ formatting
def split_hms(sec: float) -> tuple[int, int, int, int]:
    s = max(0, int(sec))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return d, h, m, s


def countdown_text(sec: float) -> str:
    """Compact T-minus for status/agents: '3D 04:12:09', '04:12:09', 'T+01:42'."""
    if sec < 0:
        _, h, m, s = split_hms(-sec)
        return f"T+{m:02d}:{s:02d}" if h < 1 else f"T+{h}:{m:02d}:{s:02d}"
    d, h, m, s = split_hms(sec)
    return f"{d}D {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


def age_label(sec: float) -> str:
    if sec < 3600:
        return f"{max(1, int(sec // 60))}M"
    if sec < 86400:
        return f"{int(sec // 3600)}H"
    return f"{int(sec // 86400)}D"


SITES = {
    "SPACEFLIGHT NOW": "SFN",
    "NASASPACEFLIGHT": "NSF",
    "SPACEPOLICYONLINE.COM": "SPACEPOLICY",
    "EUROPEAN SPACEFLIGHT": "EU SF",
    "ARSTECHNICA": "ARS",
    "ARS TECHNICA": "ARS",
    "THE SPACE REVIEW": "SPACE REVIEW",
    "NATIONAL GEOGRAPHIC": "NATGEO",
    "SPACE SCOUT": "SPACESCOUT",
}


def short_site(site: str) -> str:
    s = site.upper()
    return SITES.get(s, s)


def fit_text(text: str, width: int = TEXT_W) -> str:
    """Hard-trim (no ellipsis) so a label fits `width` px."""
    while measure(text) > width and len(text) > 1:
        text = text[:-1]
    return text


@lru_cache(maxsize=64)
def hyphen_wrap(text: str, width: int = TEXT_W) -> list[str]:
    """Greedy word wrap; words longer than a line are split with a hyphen."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        cand = f"{line} {word}" if line else word
        if measure(cand) <= width:
            line = cand
            continue
        if line:
            lines.append(line)
            line = ""
        while measure(word) > width:
            # prefer the word's own hyphen (TRANSPORTER-18), else split and add one
            dash = [i + 1 for i, ch in enumerate(word[:-1]) if ch == "-" and measure(word[: i + 1]) <= width]
            if dash:
                cut = dash[-1]
                lines.append(word[:cut])
            else:
                cut = len(word) - 1
                while cut > 2 and measure(word[:cut] + "-") > width:
                    cut -= 1
                lines.append(word[:cut] + "-")
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines


def page_len(text: str) -> float:
    """How long a caption page stays: a fixed dwell if it fits, else exactly one marquee pass."""
    w = measure(text)
    return PAGE_S if w <= TEXT_W else HOLD_S + (w + GAP) / SCROLL


def pick_page(items: list[tuple[str, RGB]], t: float) -> tuple[int, float]:
    """(index of the page showing at `t`, seconds into it)."""
    durs = [page_len(x[0]) for x in items]
    ph = t % sum(durs)
    for i, d in enumerate(durs):
        if ph < d:
            return i, ph
        ph -= d
    return len(items) - 1, 0.0


def _line_points(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return pts
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class SpaceSettings(AppSettings):
    mode: str = Choice(
        "rotate",
        {
            "launch": "Next launch",
            "iss": "ISS tracker",
            "people": "People in space",
            "news": "Space news",
            "rotate": "Rotate all",
        },
        title="Screen",
        group="Screen",
    )
    rotate_seconds: int = Field(
        15, ge=5, le=120, title="Seconds per screen", json_schema_extra={"group": "Screen"}
    )
    accent: Color = Field("#ff4818", title="Accent", json_schema_extra={"group": "Screen"})
    launch_filter: str = Choice(
        "any", {k: v[1] for k, v in LAUNCH_FILTERS.items()}, title="Launch provider", group="Launches"
    )
    hour24: bool = Field(True, title="24-hour times", json_schema_extra={"group": "Launches"})
    take_over: bool = Field(
        False,
        title="Take over for launches",
        description="Jump to the countdown for the final minute and the liftoff",
        json_schema_extra={"group": "Launches"},
    )
    iss_view: str = Choice(
        "follow",
        {"follow": "Follow-cam half globe", "world": "Whole world + readout"},
        title="ISS view",
        group="ISS",
    )
    iss_track: bool = Field(True, title="Ground track behind", json_schema_extra={"group": "ISS"})
    iss_ahead: bool = Field(True, title="Predicted track ahead", json_schema_extra={"group": "ISS"})
    iss_night: bool = Field(True, title="Day / night shading", json_schema_extra={"group": "ISS"})
    units: str = Choice("km", {"km": "Kilometres", "mi": "Miles"}, title="Units", group="ISS")
    news_seconds: int = Field(
        6, ge=3, le=30, title="Seconds per headline page", json_schema_extra={"group": "News"}
    )


@register
class Space(App):
    id = "space"
    name = "Space"
    description = "Next rocket launch countdown, live ISS tracker, people in orbit and spaceflight news."
    icon = "rocket"
    category = "data"
    Settings = SpaceSettings
    uses = ("space", "iss")
    actions = (Action("next", "Next screen", "skip-forward"),)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._skip = 0
        self._fast = False
        self.on_settings()

    # ------------------------------------------------------------ lifecycle
    def _prov(self, name: str) -> Any:
        try:
            return self.ctx.provider(name)
        except KeyError:
            return None

    def on_start(self) -> None:
        s = self.settings
        sp = self._prov("space")
        if sp is not None and hasattr(sp, "want"):
            parts = {"launch": ("launch",), "people": ("people",), "news": ("news",), "iss": ()}.get(
                s.mode, ("launch", "people", "news")
            )
            sp.want(parts, s.launch_filter)
        iss = self._prov("iss")
        if iss is not None and hasattr(iss, "fast"):
            iss.fast = s.mode in ("iss", "rotate")

    def on_settings(self) -> None:
        self.accent = to_rgb(self.settings.accent)
        self.on_start()

    @property  # type: ignore[override]
    def fps(self) -> float:  # type: ignore[override]
        return 10.0 if self._fast else 2.0

    # ------------------------------------------------------------------ data
    def _launches(self) -> tuple[Any, list[dict[str, Any]] | None]:
        p = self._prov("space")
        if p is None or not p.value:
            return p, None
        key = self.settings.launch_filter
        lists = p.value.get("launches") or {}
        if key in lists:
            return p, lists[key]["items"]
        if "any" in lists:  # the filtered list isn't fetched yet: filter the general one locally
            lsp = LAUNCH_FILTERS.get(key, (None, ""))[0]
            return p, [x for x in lists["any"]["items"] if not lsp or x["provider"] == lsp]
        return p, None

    def next_launch(self, now: float | None = None) -> dict[str, Any] | None:
        now = time.time() if now is None else now
        _, items = self._launches()
        for x in items or []:
            if x["net"] > now - LIFTOFF_S:
                return x
        return None

    def _part(self, name: str) -> tuple[Any, Any]:
        p = self._prov("space")
        v = (p.value or {}).get(name) if p is not None else None
        return p, v

    def _iss(self) -> tuple[Any, dict[str, Any] | None]:
        p = self._prov("iss")
        return p, (p.value if p is not None else None)

    # ---------------------------------------------------------------- render
    def screen(self, t: float, now: float | None = None) -> str:
        s = self.settings
        if s.mode != "rotate":
            return s.mode
        nl = self.next_launch(now)
        if nl is not None and nl["precision"] in EXACT:
            dt = nl["net"] - (time.time() if now is None else now)
            if -60.0 < dt <= FINAL_S:  # the last minute and the first minute of flight always show
                return "launch"
        return SCREENS[(int(t // s.rotate_seconds) + self._skip) % len(SCREENS)]

    def render(self, f: Frame, t: float) -> None:
        now = time.time()
        self._fast = False
        getattr(self, f"_render_{self.screen(t, now)}")(f, t, now)

    def _placeholder(self, f: Frame, t: float, p: Any, label: str, color: RGB) -> None:
        if p is None or p.error:
            offline(f, label, "OFFLINE")
        else:
            loading(f, t, label, color)

    def _caption(self, f: Frame, t: float, y: int, items: list[tuple[str, RGB]]) -> int:
        """One caption row that pages through `items`; pages that don't fit scroll once. Returns the page."""
        items = [(x.upper(), c) for x, c in items if x]
        if not items:
            return -1
        i, into = pick_page(items, t)
        text, col = items[i]
        if measure(text) <= TEXT_W:
            f.text_center(y, text, col)
        else:
            self._fast = True
            draw_marquee(f, text, into, 1, y, TEXT_W, col, speed=SCROLL, gap=GAP, hold=HOLD_S)
        return i

    # ---------------------------------------------------------------- launch
    def _render_launch(self, f: Frame, t: float, now: float) -> None:
        p, items = self._launches()
        if items is None:
            self._placeholder(f, t, p, "LAUNCH", self.accent)
            return
        nl = self.next_launch(now)
        if nl is None:
            f.sprite(ROCKET, 14, 3)
            f.hline(9, 13, 14, SHADE)
            f.text_center(17, "NO", MUTE)
            f.text_center(24, "LAUNCHES", MUTE)
            return
        dt = nl["net"] - now
        exact = nl["precision"] in EXACT
        if exact and dt <= 0:
            self._liftoff(f, t, nl, -dt)
        elif exact and dt <= FINAL_S:
            self._final(f, t, nl, dt)
        else:
            self._countdown(f, t, nl, dt, now)

    def _status_light(self, f: Frame, t: float, st: str, x: int = 28, y: int = 1) -> None:
        col = STATUS_COL.get(st, MUTE)
        if st == "HOLD" and (t % 1.0) >= 0.6:
            col = scale(col, 0.3)
        f.rect(x, y + 1, 3, 1, col)
        f.rect(x + 1, y, 1, 3, col)
        for ox, oy in ((0, 0), (2, 0), (0, 2), (2, 2)):
            f.set(x + ox, y + oy, scale(col, 0.45))

    def _header(self, f: Frame, t: float, nl: dict[str, Any]) -> None:
        name = nl["provider_abbr"] or "LAUNCH"
        name = HEADER_ABBR.get(name, name)
        f.text(1, 1, fit_text(name, 25), self.accent)
        self._status_light(f, t, nl["status"])

    def _clock(self, dt: datetime) -> str:
        if self.settings.hour24:
            return dt.strftime("%H:%M")
        return f"{dt.hour % 12 or 12}:{dt.minute:02d}{'A' if dt.hour < 12 else 'P'}"

    def _when(self, net: datetime) -> str:
        """Local launch time, with a two-letter weekday when it isn't today."""
        hm = self._clock(net)
        if net.date() != datetime.now().date():
            return net.strftime("%a")[:2].upper() + " " + hm
        return hm

    def _countdown(self, f: Frame, t: float, nl: dict[str, Any], dt: float, now: float) -> None:
        self._header(f, t, nl)
        d, h, m, s = split_hms(dt)
        prec = nl["precision"]
        exact = prec in EXACT
        net = datetime.fromtimestamp(nl["net"])
        hold = nl["status"] == "HOLD"
        hero = scale(WHITE, 0.5) if hold else WHITE
        y = 8
        if d >= 1:
            num = str(d)
            unit = "D" if d >= 100 else ("DAY" if d == 1 else "DAYS")
            w = measure(num, "big") + 2 + measure(unit)
            x = f.text((32 - w) // 2, y, num, hero, font="big") + 2
            f.text(x, y, "T-", self.accent)
            f.text(x, y + 5, unit, MUTE)
            if exact:
                sub, sub_col = f"{h:02d}:{m:02d}:{s:02d}", MUTE
            elif prec == "HR":
                sub, sub_col = self._when(net), MUTE
            elif prec == "DAY":
                sub, sub_col = net.strftime("%b %d").upper(), DIM
            else:
                sub, sub_col = net.strftime("%b %Y").upper(), DIM
        elif exact or prec == "HR":
            if h >= 1:
                a, b = f"{h:02d}", f"{m:02d}"
                colon = (now % 1.0) < 0.5 or not exact
                col = hero
            else:
                a, b = f"{m:02d}", f"{s:02d}"
                colon = True
                col = scale(PALETTE["amber"], 0.5) if hold else PALETTE["amber"]
            x = f.text(1, y, a, col, font="big") + 1
            if colon:
                f.text(x, y, ":", col, font="big")
            f.text(x + 3, y, b, col, font="big")
            sub, sub_col = self._when(net), MUTE if exact else DIM
        else:
            f.text_center(y + 1, "TODAY", hero, font="small")
            sub, sub_col = net.strftime("%b %d").upper(), DIM
        f.text_center(20, sub, sub_col)
        loc = (nl["location"] or nl["pad"]).split(",")[0]
        st = nl["status"]
        self._caption(
            f,
            t,
            26,
            [
                (nl["rocket"], WHITE),
                (nl["mission"], mix(self.accent, WHITE, 0.45)),
                (loc, MUTE),
                (STATUS_WORD.get(st, st), STATUS_COL.get(st, MUTE)),
            ],
        )

    @staticmethod
    def _pad(f: Frame, x: int, base: int) -> None:
        """Launch tower at x and the ground line below `base`."""
        f.vline(x, base - 13, 14, (70, 70, 90))
        for yy in range(base - 12, base, 3):
            f.set(x + 1, yy, (50, 50, 66))
        f.hline(0, base + 1, 32, (40, 40, 52))

    def _final(self, f: Frame, t: float, nl: dict[str, Any], dt: float) -> None:
        self._fast = True
        base, rx = 29, 6
        self._pad(f, rx - 3, base)
        # venting vapour drifting away from the base
        for i in range(8):
            ph = (t * 0.7 + i / 8) % 1.0
            side = 1 if i % 2 else -1
            vx = rx + 2 + round(side * (2 + ph * 5))
            vy = base - round(ph * 4) - (i % 3 == 0)
            f.blend(vx, vy, (210, 210, 225), 0.55 * (1 - ph))
        f.sprite(ROCKET, rx, base - ROCKET.h + 1)
        secs = f"{math.ceil(dt):02d}"
        red = PALETTE["red"] if (dt % 1.0) > 0.5 else PALETTE["amber"]
        f.text_right(30, 2, "T-", self.accent)
        f.text_right(30, 9, secs, red, font="big")
        f.text_right(30, 21, "SEC", MUTE)
        self._status_light(f, t, nl["status"], 28, 27)

    def _liftoff(self, f: Frame, t: float, nl: dict[str, Any], since: float) -> None:
        self._fast = True
        period = 6.0
        ph = (since % period) / period
        base, rx = 29, 14
        k = min(1.0, ph / 0.7)  # accelerating climb over the first 70 % of each loop
        ry = base - ROCKET.h + 1 - round((k**2) * 42)
        # smoke billowing out from the pad
        puff = min(1.0, ph * 2.2)
        for i in range(10):
            side = -1 if i % 2 else 1
            spread = (i // 2 + 1) * 2.4 * puff
            px = round(rx + 2 + side * spread)
            py = base - (i % 3) + (1 if spread > 6 else 0)
            f.circle(px, py, 1 if i > 5 else 2, scale((190, 190, 205), 0.5 * (1 - ph * 0.6)))
        # exhaust: a flickering flame column under the rocket
        seed = int(since * 10)
        for j in range(1, 9):
            yy = ry + ROCKET.h - 1 + j
            if yy > base:
                break
            flick = ((seed * 7 + j * 13) % 5) / 4
            col = mix(PALETTE["gold"], PALETTE["ember"], min(1.0, j / 5 + 0.2 * flick))
            f.set(rx + 2, yy, scale(col, 1 - j / 10))
            if j < 4:
                f.set(rx + 1 + (seed + j) % 3, yy, scale(PALETTE["amber"], 0.75 - j * 0.12))
        self._pad(f, rx - 4, base)
        f.sprite(ROCKET, rx, ry)
        if since < 10 or int(since // 2.5) % 2 == 0:
            f.text_center(1, "LIFTOFF", PALETTE["gold"])
        else:
            f.text_center(1, countdown_text(-since), self.accent)

    # ------------------------------------------------------------------- ISS
    def _render_iss(self, f: Frame, t: float, now: float) -> None:
        p, d = self._iss()
        if d is None:
            self._placeholder(f, t, p, "ISS", PALETTE["cyan"])
            return
        if self.settings.iss_view == "world":
            self._iss_world(f, t, d, now)
        else:
            self._iss_follow(f, t, d, now)

    def _shade_map(self, w: int, h: int, cols: np.ndarray, now: float) -> np.ndarray:
        m, lat, lon = _grid(w, h)
        m = m[:, cols]
        lon = lon[:, cols]
        if self.settings.iss_night:
            slat, slon = subsolar_point(now)
            dl, dn = math.radians(slat), math.radians(slon)
            alt = np.sin(lat) * math.sin(dl) + np.cos(lat) * math.cos(dl) * np.cos(lon - dn)
            day = np.clip((alt + 0.1) / 0.2, 0.0, 1.0)[..., None]  # a soft twilight band
        else:
            day = np.ones((h, len(cols), 1))
        land_c = np.array((5, 20, 10), np.float32) + np.array((15, 80, 30), np.float32) * day
        sea_c = np.array((0, 3, 10), np.float32) + np.array((0, 20, 56), np.float32) * day
        return np.where(m[..., None], land_c, sea_c).astype(np.uint8)

    def _tracks(
        self,
        f: Frame,
        d: dict[str, Any],
        to_view: Callable[[float, float], tuple[int, int]],
        now: float,
        h: int,
    ) -> None:
        s = self.settings

        def path(points: list[tuple[int, int]], col: RGB, alpha: Callable[[int, int], float]) -> None:
            n = len(points)
            for i in range(n - 1):
                (ax, ay), (bx, by) = points[i], points[i + 1]
                if abs(ax - bx) > 8:  # wrapped round the map edge
                    continue
                for x, y in _line_points(ax, ay, bx, by)[:-1]:
                    if y < h:
                        f.blend(x, y, col, alpha(i, n))

        if s.iss_track:
            pts = [to_view(la, lo) for _, la, lo in d.get("track") or []]
            path(pts, PALETTE["cyan"], lambda i, n: 0.15 + 0.55 * (i / max(1, n - 1)))
        if s.iss_ahead:
            ahead = [(la, lo) for ts, la, lo in d.get("ahead") or [] if ts >= now]
            pts = [to_view(d["lat"], d["lon"])] + [to_view(la, lo) for la, lo in ahead]
            path(pts, PALETTE["gold"], lambda i, n: 0.0 if i % 3 == 2 else 0.5 * (1 - i / max(1, n)))

    def _user(
        self, f: Frame, t: float, d: dict[str, Any], to_view: Callable[[float, float], tuple[int, int]]
    ) -> None:
        u = d.get("user")
        if not u:
            return
        x, y = to_view(u["lat"], u["lon"])
        f.set(x, y, scale(PALETTE["ember"], 0.55 + 0.45 * math.sin(t * 4)))

    @staticmethod
    def _iss_icon(f: Frame, t: float, x: int, y: int) -> None:
        panel = PALETTE["gold"]
        for ox, k in ((-2, 0.6), (-1, 0.95), (1, 0.95), (2, 0.6)):
            f.set(x + ox, y, scale(panel, k))
        f.set(x, y - 1, scale(WHITE, 0.45))
        f.set(x, y + 1, scale(WHITE, 0.45))
        f.set(x, y, WHITE if (t % 1.0) < 0.75 else PALETTE["cyan"])

    def _iss_follow(self, f: Frame, t: float, d: dict[str, Any], now: float) -> None:
        w, h = 64, 32
        ix, iy = project(d["lat"], d["lon"], w, h)
        ox = math.floor(ix) - 16
        f.px[:, :] = self._shade_map(w, h, (ox + np.arange(32)) % w, now)

        def to_view(lat: float, lon: float) -> tuple[int, int]:
            x, y = project(lat, lon, w, h)
            return (math.floor(x) - ox) % w, min(h - 1, math.floor(y))

        self._tracks(f, d, to_view, now, h)
        self._user(f, t, d, to_view)
        self._iss_icon(f, t, 16, min(h - 1, math.floor(iy)))
        # caption strip over the far south (the ISS never goes below 51.6 S)
        f.px[25:] = (f.px[25:].astype(np.uint16) * 25 // 100).astype(np.uint8)
        self._caption(f, t, 26, self._readout(d, now))

    def _iss_world(self, f: Frame, t: float, d: dict[str, Any], now: float) -> None:
        w, h = 32, 16
        f.px[:16, :] = self._shade_map(w, h, np.arange(32), now)

        def to_view(lat: float, lon: float) -> tuple[int, int]:
            x, y = project(lat, lon, w, h)
            return min(31, int(x)), min(15, int(y))

        self._tracks(f, d, to_view, now, h)
        self._user(f, t, d, to_view)
        x, y = to_view(d["lat"], d["lon"])
        f.set(x, y, WHITE if (t % 1.0) < 0.7 else PALETTE["cyan"])
        f.hline(0, 16, 32, SHADE)
        rows = [r for r in self._readout(d, now) if r[1] != PALETTE["gold"]]
        self._caption(f, t, 19, rows[1:] or rows)
        label, value, col = self._pass_row(d, now)
        if label and measure(label) + measure(value) + 3 <= TEXT_W:
            f.text(1, 26, label, MUTE)
            f.text_right(30, 26, value, col)
        else:
            f.text_center(26, f"UP {value}" if label else value, PALETTE["gold"] if label else col)

    def _pass_row(self, d: dict[str, Any], now: float) -> tuple[str, str, RGB]:
        """(label, value, colour) for the next pass; label '' means a centred message."""
        if (d.get("elev_deg") or -90) >= 10:
            return "", "OVER YOU", PALETTE["gold"]
        np_ = d.get("next_pass")
        if np_:
            mins = (np_["start"] - now) / 60.0
            if mins <= 0:
                return "", "OVER YOU", PALETTE["gold"]
            if mins < 60:
                return "PASS", f"{mins:.0f}M", WHITE
            if mins < 600:
                return "PASS", f"{int(mins // 60)}H{int(mins % 60):02d}", WHITE
            return "PASS", self._clock(datetime.fromtimestamp(np_["start"])), WHITE
        return "PASS", "--", DIM

    def _readout(self, d: dict[str, Any], now: float) -> list[tuple[str, RGB]]:
        mi = self.settings.units == "mi"
        k = 0.621371 if mi else 1.0
        unit = "MI" if mi else "KM"
        items: list[tuple[str, RGB]] = [
            ("ISS", PALETTE["cyan"]),
            (f"{d['alt_km'] * k:.0f} {unit}", WHITE),
            (f"{d['vel_kmh'] * k / 3600:.1f}{unit}/S", WHITE),
        ]
        label, value, col = self._pass_row(d, now)
        if not label:
            items.append((value, col))
        elif value != "--":
            items.append((f"UP {value}", PALETTE["gold"]))
        dist = d.get("dist_km")
        if dist is not None and (d.get("elev_deg") or -90) < 10:
            items.append((f"{dist * k:.0f}{unit}", MUTE))
        return items

    # ---------------------------------------------------------------- people
    def _render_people(self, f: Frame, t: float, now: float) -> None:
        p, v = self._part("people")
        if v is None:
            self._placeholder(f, t, p, "PEOPLE", PALETTE["mint"])
            return
        people = v["data"]["people"]
        n = int(v["data"].get("number") or len(people))
        f.text_center(1, "PEOPLE", MUTE)
        num = str(n)
        w = ASTRONAUT.w + 3 + measure(num, "big")
        x = (32 - w) // 2
        f.sprite(ASTRONAUT, x, 8)
        f.text(x + ASTRONAUT.w + 3, 8, num, WHITE, font="big")
        names = [
            (x["name"], mix(STATION_COL.get(x["station"], PALETTE["amber"]), WHITE, 0.45)) for x in people
        ]
        cur = self._caption(f, t, 26, names) if names else -1
        # one little figure per person, coloured by station; the one being named is lit
        m = len(people)
        step = 3 if m <= 10 else 2 if m <= 15 else 1
        wid = 2 if step > 1 else 1
        x0 = (32 - (m * step - (step - wid))) // 2
        for i, pp in enumerate(people):
            col = STATION_COL.get(pp["station"], PALETTE["amber"])
            k = 1.0 if i == cur else 0.45
            fx = x0 + i * step
            f.rect(fx, 19, wid, 2, scale(WHITE, k * 0.9))
            f.rect(fx, 21, wid, 3, scale(col, k))

    # ------------------------------------------------------------------ news
    def _render_news(self, f: Frame, t: float, now: float) -> None:
        p, v = self._part("news")
        if v is None:
            self._placeholder(f, t, p, "NEWS", self.accent)
            return
        items = v["items"]
        if not items:
            f.text_center(13, "NO NEWS", MUTE)
            return
        i, lines, page = self._news_page(t, items)
        a = items[i]
        age = age_label(now - a["published"]) if a.get("published") else ""
        if age:
            f.text_right(30, 1, age, MUTE)
        f.text(1, 1, fit_text(short_site(a["site"]), TEXT_W - measure(age) - 3), self.accent)
        for j, line in enumerate(lines[page * 4 : page * 4 + 4]):
            f.text(1, 8 + j * 6, line, WHITE if page == 0 and j == 0 else mix(WHITE, MUTE, 0.3))
        pages = max(1, math.ceil(len(lines) / 4))
        if pages > 1:  # page ticks on the right edge
            for q in range(pages):
                f.set(31, 8 + q * 2, WHITE if q == page else DIM)

    def _news_page(self, t: float, items: list[dict[str, Any]]) -> tuple[int, list[str], int]:
        """(article index, wrapped lines, page) at time t; each article shows all of its 4-line pages."""
        per = self.settings.news_seconds
        wrapped = [hyphen_wrap(a["title"].upper()) for a in items]
        counts = [max(1, math.ceil(len(w) / 4)) for w in wrapped]
        step = int(t // per) % sum(counts)
        for i, c in enumerate(counts):
            if step < c:
                return i, wrapped[i], step
            step -= c
        return 0, wrapped[0], 0

    # ------------------------------------------------------------- scheduling
    def wants_focus(self) -> bool:
        if not self.settings.take_over:
            return False
        nl = self.next_launch()
        if nl is None or nl["precision"] not in EXACT:
            return False
        return -120.0 < nl["net"] - time.time() <= FINAL_S

    def watches_focus(self) -> bool:
        return self.settings.take_over

    def status(self) -> dict[str, Any]:
        now = time.time()
        out: dict[str, Any] = {"mode": self.settings.mode}
        nl = self.next_launch(now)
        if nl is not None:
            out["next_launch"] = {
                "name": nl["name"],
                "provider": nl["provider"],
                "status": nl["status"],
                "net": datetime.fromtimestamp(nl["net"]).astimezone().isoformat(timespec="seconds"),
                "precision": nl["precision"],
                "t_minus": countdown_text(nl["net"] - now),
                "t_minus_s": round(nl["net"] - now),
                "pad": nl["pad"],
                "location": nl["location"],
            }
        _, d = self._iss()
        if d is not None:
            npass = d.get("next_pass")
            out["iss"] = {
                "lat": round(d["lat"], 3),
                "lon": round(d["lon"], 3),
                "alt_km": round(d["alt_km"], 1),
                "vel_kmh": round(d["vel_kmh"]),
                "visibility": d.get("visibility"),
                "dist_km": round(d["dist_km"]) if d.get("dist_km") is not None else None,
                "next_pass_in_min": round((npass["start"] - now) / 60) if npass else None,
                "next_pass_max_elev": round(npass["max_elev"]) if npass else None,
            }
        _, pv = self._part("people")
        if pv is not None:
            ppl = pv["data"]["people"]
            out["people"] = {
                "count": pv["data"]["number"],
                "names": [f"{x['name']} ({x['station']})" for x in ppl],
            }
        _, nv = self._part("news")
        if nv is not None and nv["items"]:
            a = nv["items"][0]
            out["latest_headline"] = {"title": a["title"], "site": a["site"], "url": a["url"]}
        sp = self._prov("space")
        if sp is not None and sp.value and sp.value.get("errors"):
            out["errors"] = sp.value["errors"]
        return out

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "next":
            self._skip += 1
            self.ctx.invalidate()
            return {"skip": self._skip}
        raise KeyError(f"{self.id} has no action {name!r}")

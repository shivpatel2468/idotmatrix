"""Flight Radar — a phosphor PPI scope of live ADS-B traffic around you.

The scope fills the panel edge to edge (radius 16 around the centre seam). A rotating sweep paints aircraft,
which then fade until the next pass, like a real plan-position indicator. North is up; you are the centre.
Everything is computed from the `flights` provider's last value; positions are dead-reckoned between polls.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame, measure, mix, scale
from ..gfx.color import RGB

CX = CY = 16.0  # scope centre: the seam between pixels 15 and 16, so the circle is symmetric
R_SCOPE = 16.0  # pixel-centre distance 15.5 reaches every edge
R_PLOT = 15.0  # where a contact at exactly `range_nm` lands
LABEL_Y = 26  # tiny text row on the bottom edge
CLIP_FPS = 8.0  # <= the 10 fps verified on the panel, with GIF headroom for busy skies
MAX_FRAMES = 120  # per baked loop (GIF budget); slow sweeps get a lower frame rate instead

# intensity ramp stops per theme: 0 = off ... 1 = white-hot phosphor
THEMES: dict[str, dict[str, Any]] = {
    "green": {
        "ramp": [
            (0.0, (0, 0, 0)),
            (0.12, (0, 34, 8)),
            (0.45, (0, 130, 30)),
            (0.8, (30, 255, 80)),
            (1.0, (200, 255, 200)),
        ],
        "hi": (255, 190, 0),
    },
    "amber": {
        "ramp": [
            (0.0, (0, 0, 0)),
            (0.12, (36, 14, 0)),
            (0.45, (150, 64, 0)),
            (0.8, (255, 160, 10)),
            (1.0, (255, 235, 170)),
        ],
        "hi": (0, 220, 255),
    },
    "cyan": {
        "ramp": [
            (0.0, (0, 0, 0)),
            (0.12, (0, 22, 38)),
            (0.45, (0, 100, 150)),
            (0.8, (0, 215, 255)),
            (1.0, (200, 250, 255)),
        ],
        "hi": (255, 72, 24),
    },
    "military": {
        "ramp": [
            (0.0, (0, 0, 0)),
            (0.12, (14, 30, 4)),
            (0.45, (70, 125, 15)),
            (0.8, (160, 235, 40)),
            (1.0, (235, 255, 190)),
        ],
        "hi": (255, 30, 30),
    },
}


def _lut(stops: list[tuple[float, RGB]]) -> np.ndarray:
    xs = np.linspace(0.0, 1.0, 256)
    pos = [p for p, _ in stops]
    return np.stack([np.interp(xs, pos, [c[i] for _, c in stops]) for i in range(3)], axis=1).astype(np.uint8)


# per-pixel polar coordinates of pixel centres, shared by every instance
_yy, _xx = np.mgrid[0:32, 0:32].astype(np.float32) + 0.5
DX, DY = _xx - CX, _yy - CY
RR = np.hypot(DX, DY)
ANG = np.mod(np.arctan2(DX, -DY), 2 * math.pi)  # clockwise from north
INSIDE = RR <= R_SCOPE - 0.3


def scope_xy(dist_nm: float, bearing_deg: float, range_nm: float) -> tuple[float, float]:
    """Continuous panel coordinates of a contact at `dist_nm` on `bearing_deg` (north up)."""
    k = dist_nm / max(0.1, range_nm) * R_PLOT
    b = math.radians(bearing_deg)
    return CX + k * math.sin(b), CY - k * math.cos(b)


_RAY = np.arange(0.6, 15.6, 0.35, dtype=np.float32)  # sample radii along the beam
_RAY_K = (0.6 + 0.4 * np.clip(_RAY / 6, 0, 1)).astype(np.float32)  # beam brightens away from the hub


def beam(theta: float) -> np.ndarray:
    """A 1 px anti-aliased beam from the centre at `theta` (Wu-style bilinear splat of samples along the ray)."""
    out = np.zeros((32, 32), np.float32)
    x = CX + _RAY * math.sin(theta) - 0.5  # in pixel-index space (pixel centres at integers)
    y = CY - _RAY * math.cos(theta) - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    for ox, oy, w in (
        (0, 0, (1 - fx) * (1 - fy)),
        (1, 0, fx * (1 - fy)),
        (0, 1, (1 - fx) * fy),
        (1, 1, fx * fy),
    ):
        xi, yi = x0 + ox, y0 + oy
        ok = (xi >= 0) & (xi < 32) & (yi >= 0) & (yi < 32)
        np.maximum.at(out, (yi[ok], xi[ok]), (w**0.75 * _RAY_K)[ok])
    return out


def to_pixel(fx: float, fy: float) -> tuple[int, int]:
    return max(0, min(31, math.floor(fx))), max(0, min(31, math.floor(fy)))


def alt_label(a: dict[str, Any]) -> str:
    if a.get("ground"):
        return "GND"
    alt = a.get("alt_ft")
    if alt is None:
        return "---"
    return f"FL{round(alt / 100):03d}" if alt >= 10000 else f"{int(alt)}FT"


class RadarSettings(AppSettings):
    layout: str = Choice(
        "scope", {"scope": "Radar scope", "list": "Departures list"}, title="Layout", group="Scope"
    )
    theme: str = Choice(
        "green",
        {"green": "Green phosphor", "amber": "Amber", "cyan": "Cyan", "military": "Military grid"},
        title="Theme",
        group="Scope",
    )
    range_nm: int = Field(30, ge=5, le=150, title="Range (nm)", json_schema_extra={"group": "Scope"})
    sweep_speed: float = Field(
        12.0, ge=2.0, le=30.0, title="Sweep speed (rpm)", json_schema_extra={"group": "Scope"}
    )
    trails: bool = Field(True, title="Heading trails", json_schema_extra={"group": "Scope"})
    show_labels: bool = Field(
        True,
        title="Show callsign",
        description="Callsign, altitude and distance of the focused aircraft",
        json_schema_extra={"group": "Labels"},
    )
    highlight: str = Choice(
        "nearest",
        {"none": "None", "nearest": "Nearest", "fastest": "Fastest", "highest": "Highest"},
        title="Highlight",
        group="Labels",
    )
    rotate_labels: bool = Field(
        False,
        title="Cycle labels",
        description="Step the label through every aircraft",
        json_schema_extra={"group": "Labels"},
    )
    min_altitude_ft: int = Field(
        0, ge=0, le=40000, title="Min altitude (ft)", json_schema_extra={"group": "Filters"}
    )
    hide_ground: bool = Field(
        True, title="Hide aircraft on the ground", json_schema_extra={"group": "Filters"}
    )


@register
class Radar(App):
    id = "radar"
    name = "Flight Radar"
    description = (
        "A phosphor radar scope of live aircraft around you (free ADS-B). Click a blip to inspect it."
    )
    icon = "radar"
    category = "data"
    Settings = RadarSettings
    fps = 10.0
    uses = ("flights",)
    actions = (Action("next", "Next aircraft", "skip-forward"), Action("clear", "Clear selection", "x"))

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.selected: str | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self.on_settings()

    # ------------------------------------------------------------ lifecycle
    def _prov(self) -> Any:
        try:
            return self.ctx.provider("flights")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._prov()
        if p is not None and hasattr(p, "configure"):
            p.configure(self.settings.range_nm)

    def on_settings(self) -> None:
        th = THEMES.get(self.settings.theme, THEMES["green"])
        self._lut = _lut(th["ramp"])
        self._hi: RGB = th["hi"]
        self._base = self._grid(self.settings.theme)
        self.on_start()

    @staticmethod
    def _grid(theme: str) -> np.ndarray:
        """Static scope furniture as intensities: range rings, crosshair, bearing ticks, rim."""
        g = np.zeros((32, 32), np.float32)
        # levels are lit enough to survive the panel gamma (0.16 / 0.10 read as black on the LEDs)
        for rr, k in ((R_PLOT / 3, 0.24), (R_PLOT * 2 / 3, 0.24)):
            g = np.maximum(g, k * np.clip(1 - np.abs(RR - rr) / 0.75, 0, 1))
        rim = 0.36 * np.clip(1 - np.abs(RR - 15.35) / 0.6, 0, 1)
        g = np.maximum(g, rim)
        # 30-degree ticks just inside the rim, brighter at the cardinal points
        for i in range(12):
            a = i * math.pi / 6
            d = np.abs(np.angle(np.exp(1j * (ANG - a)))) * RR
            tick = np.clip(1 - d / 0.7, 0, 1) * ((RR > 12.6) & (RR < 15.8))
            g = np.maximum(g, (0.42 if i % 3 == 0 else 0.26) * tick)
        # crosshair on the two centre columns/rows, dotted so it stays faint
        cross = ((np.abs(DX) < 0.6) | (np.abs(DY) < 0.6)) & (RR < R_PLOT) & (RR > 1.5)
        if theme == "military":  # a square map grid: solid cross plus lines 7.5 px either side of it
            grid = ((np.abs(np.abs(DX) - 7.5) < 0.1) | (np.abs(np.abs(DY) - 7.5) < 0.1)) & INSIDE
            g = np.maximum(g, 0.16 * grid)
            g = np.maximum(g, 0.16 * cross)
        else:
            dotted = (_xx + _yy).astype(int) % 2 == 0
            g = np.maximum(g, 0.16 * (cross & dotted))
        g[~(RR <= R_SCOPE)] = 0
        return g

    # -------------------------------------------------------------- contacts
    def _data(self) -> tuple[Any, dict[str, Any] | None]:
        p = self._prov()
        return p, (p.value if p is not None else None)

    def contacts(self, now: float | None = None) -> list[dict[str, Any]]:
        """Filtered aircraft inside the range, dead-reckoned to `now`, with scope coordinates."""
        _, d = self._data()
        if not d:
            return []
        s = self.settings
        now = time.time() if now is None else now
        age = max(0.0, min(30.0, now - float(d.get("updated") or now)))
        out = []
        for a in d.get("aircraft") or []:
            if a.get("ground") and s.hide_ground:
                continue
            alt = a.get("alt_ft")
            if s.min_altitude_ft and not a.get("ground") and (alt is None or alt < s.min_altitude_ft):
                continue
            b = math.radians(a.get("bearing_deg") or 0.0)
            e, n = a["dist_nm"] * math.sin(b), a["dist_nm"] * math.cos(b)
            trk, gs = a.get("track"), a.get("speed_kt")
            if trk is not None and gs and not a.get("ground"):
                moved = gs * age / 3600.0
                e += moved * math.sin(math.radians(trk))
                n += moved * math.cos(math.radians(trk))
            dist = math.hypot(e, n)
            if dist > s.range_nm:
                continue
            brg = (math.degrees(math.atan2(e, n)) + 360) % 360
            fx, fy = scope_xy(dist, brg, s.range_nm)
            out.append({**a, "dist_now": dist, "brg_now": brg, "fx": fx, "fy": fy, "xy": to_pixel(fx, fy)})
        out.sort(key=lambda c: c["dist_now"])
        return out

    def _focus(self, cs: list[dict[str, Any]], t: float) -> tuple[dict[str, Any] | None, bool]:
        """(aircraft the label/highlight is on, whether it's the user's selection)."""
        if not cs:
            return None, False
        if self.selected:
            for c in cs:
                if c["id"] == self.selected:
                    return c, True
        s = self.settings
        if s.rotate_labels:
            return cs[int(t / 4.0) % len(cs)], False
        if s.highlight == "fastest":
            return max(cs, key=lambda c: c.get("speed_kt") or 0), False
        if s.highlight == "highest":
            return max(cs, key=lambda c: c.get("alt_ft") or 0), False
        return cs[0], False  # nearest (also the label target when highlight is none)

    # ---------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        if self.settings.layout == "list":
            self._render_list(f, t)
        else:
            self._render_scope(f, t)

    # ------------------------------------------------------------ the scope loop (baked as a clip)
    def _schedule(self, cs: list[dict[str, Any]]) -> dict[str, Any]:
        """One seamless loop of whole sweep revolutions.

        The sweep is deterministic, so the scope is a baked clip (a streamed full-screen sweep only reached ~5 fps
        on the link and stuttered). `per_rev` frames per turn at <= 10 fps; the caption steps through its parts
        (or, with "cycle labels", through up to four aircraft) in equal slots that divide the loop exactly.
        """
        s = self.settings
        period = 60.0 / s.sweep_speed
        focus, selected = self._focus(cs, 0.0)
        slots: list[tuple[dict[str, Any] | None, int]]
        if s.rotate_labels and not selected and cs:
            slots = [(c, 0) for c in cs[:4]]
        elif focus is not None and s.show_labels:
            slots = [(focus, k) for k in range(len(self._caption_parts(focus)))]
        else:
            slots = [(focus, 0)]
        revs = max(1, math.ceil(len(slots) * 1.6 / period))  # every caption slot shows for >= 1.6 s
        per_rev = max(8, round(period * CLIP_FPS))
        if per_rev * revs > MAX_FRAMES:
            per_rev = max(8, MAX_FRAMES // revs)
        return {
            "per_rev": per_rev,
            "total": per_rev * revs,
            "ms": round(period * 1000 / per_rev),
            "slots": slots,
            "selected": selected,
        }

    def _render_scope(self, f: Frame, t: float) -> None:
        _p, d = self._data()
        cs = self.contacts() if d else []
        sch = self._schedule(cs)
        i = int(t * 1000 / sch["ms"] + 1e-6) % sch["total"]
        self._paint_scope(f, i, sch, cs)

    def _paint_scope(self, f: Frame, i: int, sch: dict[str, Any], cs: list[dict[str, Any]]) -> None:
        s = self.settings
        p, d = self._data()
        per_rev, total = sch["per_rev"], sch["total"]
        theta = 2 * math.pi * (i % per_rev) / per_rev
        period = per_rev * sch["ms"] / 1000  # seconds per turn of the baked loop
        omega = 2 * math.pi / period
        ph = i / total  # loop phase: every pulse below runs a whole number of cycles per loop

        # sweep: trailing phosphor wedge + a bright anti-aliased beam
        da = np.mod(theta - ANG, 2 * math.pi)  # angle since the beam passed each pixel
        radial = 0.45 + 0.55 * (RR / R_SCOPE)
        wedge = 0.58 * np.exp(-da / 0.6) * radial
        inten = np.maximum(self._base, np.maximum(wedge, beam(theta))) * INSIDE
        if d is None:  # searching: dimmer beam, no contacts
            inten *= 0.75
        inten[15:17, 15:17] = np.maximum(inten[15:17, 15:17], 0.6)  # you

        n_slots = len(sch["slots"])
        focus, part = sch["slots"][min(n_slots - 1, i * n_slots // total)]
        selected = sch["selected"]
        decay = period * 0.38
        halos: list[tuple[int, int, float]] = []
        for c in cs:
            ang = math.radians(c["brg_now"])
            tau = ((theta - ang) % (2 * math.pi)) / omega  # seconds since the sweep painted it
            k = 0.16 + 0.84 * math.exp(-tau / decay)
            x, y = c["xy"]
            if s.trails and c.get("track") is not None and not c.get("ground"):
                tr = math.radians(c["track"])
                for step, kk in ((1.3, 0.5), (2.5, 0.28)):
                    tx, ty = to_pixel(c["fx"] - math.sin(tr) * step, c["fy"] + math.cos(tr) * step)
                    if (tx, ty) != (x, y):
                        inten[ty, tx] = max(inten[ty, tx], kk * k + 0.06)
            inten[y, x] = max(inten[y, x], 0.5 + 0.5 * k)  # a contact never fades below mid phosphor
            if tau < 0.35:  # fresh paint glows onto the neighbours
                halos.append((x, y, 0.5 * (1 - tau / 0.35)))
        for x, y, h in halos:
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < 32 and 0 <= ny < 32:
                    inten[ny, nx] = max(inten[ny, nx], h)

        f.px[:] = self._lut[np.clip(inten * 255, 0, 255).astype(np.uint8)]

        if focus is not None and (selected or s.highlight != "none" or s.rotate_labels):
            x, y = focus["xy"]
            seconds = total * sch["ms"] / 1000
            cycles = max(1, round(seconds * (1.4 if selected else 0.64)))  # ~9 rad/s and ~4 rad/s
            wave = 0.5 + 0.5 * math.sin(ph * 2 * math.pi * cycles)
            pulse = wave if selected else 0.8 + 0.2 * wave
            f.set(x, y, scale(self._hi, 0.35 + 0.65 * pulse))
            if selected:  # lock-on brackets
                for ox, oy in ((-2, -2), (2, -2), (-2, 2), (2, 2)):
                    f.set(x + ox, y + oy, scale(self._hi, 0.55))

        # bottom-edge caption over a darkened strip
        text, color = None, scale(self._lut[210], 1.0)
        if p is None or (d is None and p.error):
            text, color = "OFFLINE", (255, 170, 0)
        elif d is None:
            blinks = max(1, round(total * sch["ms"] / 1200))
            text = "SCAN" if (ph * blinks) % 1.0 < 0.75 else ""
        elif not cs:
            text, color = "QUIET", tuple(int(v) for v in self._lut[170])  # type: ignore[assignment]
        elif focus is not None and s.show_labels:
            parts = self._caption_parts(focus)
            text = parts[part % len(parts)]
            color = self._hi if selected else tuple(int(v) for v in self._lut[225])  # type: ignore[assignment]
        if text is not None:
            f.px[LABEL_Y - 1 :] = (f.px[LABEL_Y - 1 :].astype(np.uint16) * 3 // 10).astype(np.uint8)
            if text:
                f.text_center(LABEL_Y, text, color)

    def _caption_parts(self, a: dict[str, Any]) -> list[str]:
        parts = [a.get("callsign") or a["id"].upper(), alt_label(a), f"{a['dist_now']:.0f}NM"]
        route = self._route(a)
        if route and route.get("origin") and route.get("destination"):
            o, dst = route["origin"].get("iata"), route["destination"].get("iata")
            if o and dst:
                parts.insert(1, f"{o}-{dst}")
        out = []
        for txt in parts:
            while measure(txt) > 30 and len(txt) > 1:
                txt = txt[:-1]
            out.append(txt)
        return out

    def _caption(self, a: dict[str, Any], t: float, selected: bool) -> str:
        parts = self._caption_parts(a)
        return parts[int(t / 2.2) % len(parts)]

    def _route(self, a: dict[str, Any]) -> dict[str, Any] | None:
        p = self._prov()
        if p is None or not hasattr(p, "cached_route"):
            return None
        return p.cached_route(a.get("callsign") or "")

    def _render_list(self, f: Frame, t: float) -> None:
        s = self.settings
        p, d = self._data()
        bright = tuple(int(v) for v in self._lut[225])
        mid = tuple(int(v) for v in self._lut[185])  # dimmer phosphor levels vanish on the panel
        dim = tuple(int(v) for v in self._lut[160])
        cs = self.contacts() if d else []
        f.text(1, 1, str(len(cs)) if d else "--", bright)
        f.text_right(30, 1, f"{s.range_nm}NM", dim)
        f.hline(1, 7, 30, dim)
        if p is None or (d is None and p.error):
            f.text_center(14, "OFFLINE", (255, 170, 0))
            return
        if d is None:
            f.text_center(12, "SCAN", mid)
            for i in range(3):
                k = 0.5 + 0.5 * math.sin(t * 5 - i * 0.9)
                f.rect(11 + i * 4, 20, 2, 2, scale(bright, 0.25 + 0.75 * k))
            return
        if not cs:
            f.text_center(16, "QUIET", mid)
            return
        row, top = 12, 9
        n = len(cs)
        offset = 0.0
        if n > 2:  # board flips one row every 3 s with a short eased slide
            step, frac = divmod(t / 3.0, 1.0)
            ease = 0.0 if frac < 0.85 else (1 - math.cos((frac - 0.85) / 0.15 * math.pi)) / 2
            offset = ((step + ease) % n) * row
        clip = (0, top, 31, 31)
        count = n if n <= 2 else n + 3
        for i in range(count):
            a = cs[i % n]
            y = round(top + i * row - offset)
            if y > 31 or y + row < top:
                continue
            sel = a["id"] == self.selected
            c1 = self._hi if sel else bright
            call = (a.get("callsign") or a["id"].upper())[:7]
            f.text(1, y, call, c1, clip=clip)
            vr = a.get("vrate") or 0
            if abs(vr) > 300 and not a.get("ground") and measure(call) <= 25:
                f.text(28, y, "↑" if vr > 0 else "↓", c1 if sel else mid, clip=clip)
            f.text(1, y + 6, alt_label(a), mid, clip=clip)
            dist = f"{a['dist_now']:.0f}"
            f.text(
                31 - measure(dist), y + 6, dist, dim if not sel else mix(self._hi, (0, 0, 0), 0.3), clip=clip
            )

    # ---------------------------------------------------------------- output
    #: contact updates re-bake the loop at most this often: back-to-back GIF uploads freeze the panel
    #: (docs/HARDWARE_PROTOCOL.md #16). The list layout streams and stays live.
    clip_refresh = 90.0
    clip_colors = 64

    def kind(self) -> Kind:
        return "clip" if self.settings.layout == "scope" else "stream"

    def clip_key(self) -> str:
        p, d = self._data()
        state = "none" if p is None else ("data" if d else ("error" if p.error else "scan"))
        return super().clip_key() + json.dumps([state, self.selected])

    def clip_chunk(self) -> str:
        cs = self.contacts() if self._data()[1] else []
        sig = [(c["id"], c["xy"], alt_label(c), round(c["dist_now"])) for c in cs]
        focus = [a["id"] if a else None for a, _k in self._schedule(cs)["slots"]]
        return json.dumps([sig, focus, [self._caption_parts(c) for c in cs[:4]]])

    def clip_frames(self) -> Clip:
        cs = self.contacts() if self._data()[1] else []
        sch = self._schedule(cs)
        frames = []
        for i in range(sch["total"]):
            f = Frame()
            self._paint_scope(f, i, sch, cs)
            frames.append(f)
        return Clip(frames, [sch["ms"]] * sch["total"])

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        _, d = self._data()
        cs = self.contacts()
        blips = [
            {
                "id": c["id"],
                "callsign": c.get("callsign"),
                "x": c["xy"][0],
                "y": c["xy"][1],
                "alt_ft": c.get("alt_ft"),
                "speed_kt": c.get("speed_kt"),
                "type": c.get("type"),
            }
            for c in cs
        ]
        sel = None
        if self.selected:
            hit = next((c for c in cs if c["id"] == self.selected), None)
            if hit is None and d:
                hit = next((a for a in d.get("aircraft") or [] if a["id"] == self.selected), None)
            if hit is None:
                sel = {"id": self.selected, "lost": True}
            else:
                sel = {k: v for k, v in hit.items() if k not in ("fx", "fy", "xy", "dist_now", "brg_now")}
                if "dist_now" in hit:
                    sel["dist_nm"] = round(hit["dist_now"], 1)
                    sel["bearing_deg"] = round(hit["brg_now"], 1)
                if "xy" in hit:
                    sel["x"], sel["y"] = hit["xy"]
                sel["route"] = self._route(hit)
        return {
            "count": len(cs),
            "range_nm": self.settings.range_nm,
            "source": (d or {}).get("source"),
            "center": (d or {}).get("center"),
            "selected": sel,
            "blips": blips,
        }

    # --------------------------------------------------------------- actions
    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "select":
            self.selected = str(payload.get("id") or "") or None
            self._lookup_route()
            return self.status().get("selected")
        if name == "clear":
            self.selected = None
            return None
        if name == "next":
            cs = self.contacts()
            if not cs:
                self.selected = None
                return None
            ids = [c["id"] for c in cs]
            i = ids.index(self.selected) + 1 if self.selected in ids else 0
            self.selected = ids[i % len(ids)]
            self._lookup_route()
            return self.status().get("selected")
        raise KeyError(f"{self.id} has no action {name!r}")

    def _lookup_route(self) -> None:
        """Fire-and-forget adsbdb lookup for the selection; the provider caches it (misses too)."""
        p, d = self._data()
        if not self.selected or p is None or not d or not hasattr(p, "route"):
            return
        a = next((a for a in d.get("aircraft") or [] if a["id"] == self.selected), None)
        cs = (a or {}).get("callsign") or ""
        if not cs or p.route_known(cs):
            return

        async def run() -> None:
            try:
                if await p.route(cs) is not None:
                    p.hub.on_change(p.name)  # push the new status to the studio once
            except Exception:
                pass

        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

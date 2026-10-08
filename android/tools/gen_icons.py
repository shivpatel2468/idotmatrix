"""Launcher icon options for the Android app — one source, two outputs.

    uv run python android/tools/gen_icons.py

writes, for every icon in ICONS:
  android/app/src/main/res/drawable/ic_<id>_bg.xml / ic_<id>_fg.xml / ic_<id>_mono.xml   (adaptive-icon layers)
  android/app/src/main/res/mipmap-anydpi-v26/ic_launcher_<id>.xml                       (background + foreground + monochrome)
and web/src/lib/appIcons.ts (the same artwork as inline SVG, so Settings → App icon shows exactly what the launcher shows).

Coordinates are the adaptive-icon canvas: 108 × 108, launchers show the middle 72 × 72 (18..90) through their mask and
everything important stays inside the 66-unit safe circle around (54, 54). The manifest has one <activity-alias> per id
(`.Launcher<Id>`); MainActivity.ICONS lists the ids. Add an icon: add it here, run this, add the alias + the id there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "android/app/src/main/res"
TS = ROOT / "web/src/lib/appIcons.ts"

# ----------------------------------------------------------------------------- primitives

Stops = list[tuple[float, str]]  # (offset, "#rrggbb" or "#rrggbbaa")


@dataclass
class Lin:
    x1: float
    y1: float
    x2: float
    y2: float
    stops: Stops


@dataclass
class Rad:
    cx: float
    cy: float
    r: float
    stops: Stops


Fill = str | Lin | Rad


@dataclass
class Shape:
    d: str
    fill: Fill
    alpha: float = 1.0
    evenodd: bool = False


@dataclass
class Layer:
    shapes: list[Shape] = field(default_factory=list)

    def add(self, d: str, fill: Fill, alpha: float = 1.0, evenodd: bool = False) -> Layer:
        if d:
            self.shapes.append(Shape(d, fill, alpha, evenodd))
        return self


def f(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def circle(cx: float, cy: float, r: float) -> str:
    return f"M{f(cx - r)},{f(cy)}a{f(r)},{f(r)} 0 1,0 {f(2 * r)},0a{f(r)},{f(r)} 0 1,0 {f(-2 * r)},0z"


def circles(pts: list[tuple[float, float]], r: float) -> str:
    return "".join(circle(x, y, r) for x, y in pts)


def rrect(x: float, y: float, w: float, h: float, r: float) -> str:
    return (
        f"M{f(x + r)},{f(y)}h{f(w - 2 * r)}a{f(r)},{f(r)} 0 0,1 {f(r)},{f(r)}v{f(h - 2 * r)}"
        f"a{f(r)},{f(r)} 0 0,1 {f(-r)},{f(r)}h{f(-(w - 2 * r))}a{f(r)},{f(r)} 0 0,1 {f(-r)},{f(-r)}"
        f"v{f(-(h - 2 * r))}a{f(r)},{f(r)} 0 0,1 {f(r)},{f(-r)}z"
    )


def rrects(pts: list[tuple[float, float]], s: float, r: float) -> str:
    return "".join(rrect(x - s / 2, y - s / 2, s, s, r) for x, y in pts)


def poly(pts: list[tuple[float, float]]) -> str:
    return "M" + "L".join(f"{f(x)},{f(y)}" for x, y in pts) + "z"


FULL = "M0,0h108v108h-108z"


def grid(rows: list[str], cx: float, cy: float, pitch: float) -> tuple[list, list]:
    """Cells of a dot pattern centred on (cx, cy): ([(x, y, col, row) lit], [(x, y) unlit])."""
    h, w = len(rows), max(len(r) for r in rows)
    x0, y0 = cx - (w - 1) * pitch / 2, cy - (h - 1) * pitch / 2
    lit, off = [], []
    for j, row in enumerate(rows):
        for i in range(w):
            ch = row[i] if i < len(row) else "."
            p = (x0 + i * pitch, y0 + j * pitch)
            (lit.append((*p, i, j)) if ch != "." else off.append(p))
    return lit, off


D_SQUARE = ["###..", "#..#.", "#...#", "#...#", "#...#", "#..#.", "###.."]

# ----------------------------------------------------------------------------- the icons


@dataclass
class Icon:
    id: str
    name: str
    hint: str
    bg: Layer
    fg: Layer
    mono: Layer


def classic() -> Icon:
    # today's icon, unchanged: a 5 × 5 ember "D" on graphite
    rows = ["###..", "#..#.", "#...#", "#..#.", "###.."]
    lit, off = grid(rows, 54, 54, 10)
    fg = Layer().add(circles(off, 3.5), "#2a2a33").add(circles([p[:2] for p in lit], 3.5), "#f94a18")
    mono = Layer().add(circles(off, 3.5), "#ffffff", 0.3).add(circles([p[:2] for p in lit], 3.5), "#ffffff")
    return Icon("classic", "Classic", "The original ember dot D", Layer().add(FULL, "#0b0b0f"), fg, mono)


def monogram() -> Icon:
    # "DD" in LED dots — rose Desk, gold Dot, like the logo — on a black glass tile
    rows = [a + "." + b for a, b in zip(D_SQUARE, D_SQUARE, strict=True)]
    lit, off = grid(rows, 54, 54, 4.3)
    left = [(x, y) for x, y, i, _ in lit if i < 5]
    right = [(x, y) for x, y, i, _ in lit if i > 5]
    bg = Layer().add(FULL, Rad(54, 40, 80, [(0, "#1d1c24"), (0.6, "#0c0b10"), (1, "#050507")]))
    fg = (
        Layer()
        .add(circles(off, 1.35), "#25242d")
        .add(circles(left, 3.6), "#ff4f7b", 0.2)
        .add(circles(right, 3.6), "#ffcc33", 0.2)
        .add(circles(left, 1.75), "#ff4f7b")
        .add(circles(right, 1.75), "#ffcc33")
        .add(circles(left + right, 0.6), "#ffffff", 0.45)
    )
    mono = Layer().add(circles(off, 1.35), "#ffffff", 0.3).add(circles(left + right, 1.75), "#ffffff")
    return Icon("monogram", "Monogram", "DD in rose and gold LEDs", bg, fg, mono)


def ink() -> Icon:
    # a big gold-leaf D inside a dim dot matrix, on deep ink
    rows = ["......."] + ["." + r + "." for r in D_SQUARE] + ["......."]
    lit, off = grid(rows, 54, 54, 6.2)
    pts = [p[:2] for p in lit]
    gold = Lin(38, 30, 70, 78, [(0, "#fff1b8"), (0.45, "#ffcc33"), (1, "#b8892a")])
    bg = Layer().add(FULL, Rad(54, 36, 84, [(0, "#2a2546"), (0.55, "#14121f"), (1, "#08070d")]))
    fg = (
        Layer()
        .add(circles(off, 1.9), "#2c2944")
        .add(circles(pts, 4.6), "#ffcc33", 0.16)
        .add(circles(pts, 2.55), gold)
        .add(circles([(x - 0.7, y - 0.8) for x, y in pts], 0.75), "#ffffff", 0.55)
    )
    mono = Layer().add(circles(off, 1.9), "#ffffff", 0.3).add(circles(pts, 2.55), "#ffffff")
    return Icon("ink", "Gold leaf", "Gold dots on midnight ink", bg, fg, mono)


def sunset() -> Icon:
    # the brand gradient (rose → ember → gold) with a white dot D, like a lit sign
    rows = ["###..", "#..#.", "#...#", "#..#.", "###.."]
    lit, off = grid(rows, 54, 54, 10)
    pts = [p[:2] for p in lit]
    bg = Layer().add(FULL, Lin(10, 6, 98, 102, [(0, "#ff4f7b"), (0.55, "#ff8c2e"), (1, "#ffcf4d")]))
    fg = (
        Layer()
        .add(circles(off, 3.4), "#ffffff", 0.24)
        .add(circles([(x, y + 1.3) for x, y in pts], 3.7), "#8a1236", 0.22)
        .add(circles(pts, 3.7), "#ffffff")
    )
    mono = Layer().add(circles(off, 3.4), "#ffffff", 0.3).add(circles(pts, 3.7), "#ffffff")
    return Icon("sunset", "Sunset", "Rose-to-gold tile, white LEDs", bg, fg, mono)


def porcelain() -> Icon:
    # minimal: an ivory tile with the panel on it — a black screen in a gold rim, a rainbow dot D
    rows = ["." + r + "." for r in D_SQUARE]
    lit, off = grid(rows, 54, 54, 5.4)
    hues = ["#ff4f7b", "#ff8c2e", "#ffcf4d", "#3ddc97", "#37c8ff"]
    bg = Layer().add(FULL, Lin(54, 0, 54, 108, [(0, "#fdfbf7"), (1, "#e8e0d2")]))
    fg = (
        Layer()
        .add(rrect(29, 33, 50, 50, 12), "#40301c", 0.10)
        .add(rrect(29, 31, 50, 50, 12), "#40301c", 0.10)
        .add(
            rrect(28.5, 28.5, 51, 51, 12.5),
            Lin(30, 28, 78, 80, [(0, "#f3e3b0"), (0.5, "#c9a24c"), (1, "#8f6a1f")]),
        )
        .add(rrect(31, 31, 46, 46, 10), "#0c0c0f")
        .add(circles(off, 1.6), "#1f1f27")
    )
    for k, c in enumerate(hues):
        fg.add(circles([(x, y) for x, y, i, _ in lit if i == k + 1], 2.0), c)
    fg.add(rrect(31, 31, 46, 20, 10), "#ffffff", 0.05)
    mono = (
        Layer()
        .add(rrect(28.5, 28.5, 51, 51, 12.5) + rrect(31.5, 31.5, 45, 45, 9.5), "#ffffff", 1.0, evenodd=True)
        .add(circles([p[:2] for p in lit], 2.0), "#ffffff")
    )
    return Icon("porcelain", "Porcelain", "The panel on an ivory tile", bg, fg, mono)


def chip() -> Icon:
    # a casino chip on felt: ember rim with white inserts, gold dot D in the middle
    stripes = ""
    for k in range(8):
        a = math.radians(k * 45 + 22.5)
        ux, uy, px, py = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        r0, r1, hw = 23.2, 31, 4.1
        stripes += poly(
            [
                (54 + ux * r0 + px * hw, 54 + uy * r0 + py * hw),
                (54 + ux * r1 + px * hw, 54 + uy * r1 + py * hw),
                (54 + ux * r1 - px * hw, 54 + uy * r1 - py * hw),
                (54 + ux * r0 - px * hw, 54 + uy * r0 - py * hw),
            ]
        )
    lit, _ = grid(D_SQUARE, 54, 54, 4.1)
    pts = [p[:2] for p in lit]
    bg = Layer().add(FULL, Rad(54, 44, 82, [(0, "#1a8a59"), (0.6, "#0d4d31"), (1, "#062a1b")]))
    fg = (
        Layer()
        .add(circle(54, 56.5, 31.5), "#000000", 0.28)
        .add(circle(54, 54, 31.8), "#5a0718")
        .add(circle(54, 54, 31), Rad(48, 46, 40, [(0, "#e8364f"), (1, "#a8132f")]))
        .add(stripes, "#f5efe6")
        .add(circle(54, 54, 21.6), "#f5efe6")
        .add(circle(54, 54, 20.2), "#8e1029")
        .add(circle(54, 54, 18.4), Rad(50, 48, 22, [(0, "#2a1620"), (1, "#120a0e")]))
        .add(circles(pts, 3.2), "#ffcc33", 0.16)
        .add(circles(pts, 1.6), Lin(46, 40, 62, 68, [(0, "#fff1b8"), (0.5, "#ffcc33"), (1, "#c9962e")]))
    )
    mono = (
        Layer()
        .add(circle(54, 54, 31) + circle(54, 54, 21.6), "#ffffff", 1.0, evenodd=True)
        .add(circles(pts, 1.6), "#ffffff")
    )
    return Icon("chip", "Casino chip", "An ember chip on green felt", bg, fg, mono)


def heart() -> Icon:
    # a pixel heart, lit, on a black panel
    rows = [
        ".##...##.",
        "####.####",
        "#########",
        "#########",
        ".#######.",
        "..#####..",
        "...###...",
        "....#....",
    ]
    lit, off = grid(rows, 54, 55, 5.1)
    hi = [(x, y) for x, y, i, j in lit if (i, j) in {(1, 1), (2, 1), (1, 2), (6, 1)}]
    low = [(x, y) for x, y, i, j in lit if j >= 5 and (x, y) not in hi]
    main = [(x, y) for x, y, *_ in lit if (x, y) not in hi and (x, y) not in low]
    allp = [p[:2] for p in lit]
    bg = Layer().add(FULL, Rad(54, 50, 78, [(0, "#24101a"), (0.6, "#0e080c"), (1, "#060507")]))
    fg = (
        Layer()
        .add(circles(off, 1.2), "#2a1c24")
        .add(circles(allp, 4.8), "#ff3b5c", 0.13)
        .add(rrects(main, 4.3, 1.2), "#ff3b5c")
        .add(rrects(low, 4.3, 1.2), "#d61f45")
        .add(rrects(hi, 4.3, 1.2), "#ffb3c1")
    )
    mono = Layer().add(circles(off, 1.2), "#ffffff", 0.3).add(rrects(allp, 4.3, 1.2), "#ffffff")
    return Icon("heart", "Pixel heart", "A lit pixel heart", bg, fg, mono)


ICONS = [classic(), monogram(), ink(), sunset(), porcelain(), chip(), heart()]

# ----------------------------------------------------------------------------- writers


def argb(c: str, alpha: float = 1.0) -> str:
    c = c.lstrip("#")
    a = int(c[6:8], 16) / 255 if len(c) == 8 else 1.0
    return f"#{round(a * alpha * 255):02X}{c[:6].upper()}"


def vd(layer: Layer) -> str:
    out = []
    for s in layer.shapes:
        attrs = f'android:pathData="{s.d}"'
        if s.evenodd:
            attrs += ' android:fillType="evenOdd"'
        if isinstance(s.fill, str):
            out.append(f'    <path android:fillColor="{argb(s.fill, s.alpha)}" {attrs} />')
            continue
        g = s.fill
        if isinstance(g, Lin):
            head = f'android:type="linear" android:startX="{f(g.x1)}" android:startY="{f(g.y1)}" android:endX="{f(g.x2)}" android:endY="{f(g.y2)}"'
        else:
            head = f'android:type="radial" android:centerX="{f(g.cx)}" android:centerY="{f(g.cy)}" android:gradientRadius="{f(g.r)}"'
        items = "\n".join(
            f'                <item android:offset="{f(o)}" android:color="{argb(c, s.alpha)}" />'
            for o, c in g.stops
        )
        out.append(
            f"    <path {attrs}>\n"
            f'        <aapt:attr name="android:fillColor">\n'
            f"            <gradient {head}>\n{items}\n            </gradient>\n"
            f"        </aapt:attr>\n    </path>"
        )
    body = "\n".join(out)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- generated by android/tools/gen_icons.py — edit there, not here -->\n"
        '<vector xmlns:android="http://schemas.android.com/apk/res/android" xmlns:aapt="http://schemas.android.com/aapt"\n'
        '    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">\n'
        f"{body}\n</vector>\n"
    )


def svg(icon: Icon) -> str:
    defs, els = [], []
    n = 0
    for layer in (icon.bg, icon.fg):
        for s in layer.shapes:
            rule = ' fill-rule="evenodd"' if s.evenodd else ""
            if isinstance(s.fill, str):
                op = f' fill-opacity="{f(s.alpha)}"' if s.alpha < 1 else ""
                els.append(f'<path d="{s.d}" fill="{s.fill}"{op}{rule}/>')
                continue
            gid = f"ai-{icon.id}-{n}"
            n += 1
            g = s.fill
            st = "".join(f'<stop offset="{f(o)}" stop-color="{c}"/>' for o, c in g.stops)
            if isinstance(g, Lin):
                defs.append(
                    f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{f(g.x1)}" y1="{f(g.y1)}" x2="{f(g.x2)}" y2="{f(g.y2)}">{st}</linearGradient>'
                )
            else:
                defs.append(
                    f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{f(g.cx)}" cy="{f(g.cy)}" r="{f(g.r)}">{st}</radialGradient>'
                )
            op = f' fill-opacity="{f(s.alpha)}"' if s.alpha < 1 else ""
            els.append(f'<path d="{s.d}" fill="url(#{gid})"{op}{rule}/>')
    return f"<defs>{''.join(defs)}</defs>{''.join(els)}"


def main() -> None:
    (RES / "drawable").mkdir(parents=True, exist_ok=True)
    (RES / "mipmap-anydpi-v26").mkdir(parents=True, exist_ok=True)
    for icon in ICONS:
        for part, layer in (("bg", icon.bg), ("fg", icon.fg), ("mono", icon.mono)):
            (RES / f"drawable/ic_{icon.id}_{part}.xml").write_text(vd(layer), encoding="utf-8", newline="\n")
        (RES / f"mipmap-anydpi-v26/ic_launcher_{icon.id}.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<!-- generated by android/tools/gen_icons.py -->\n"
            '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
            f'    <background android:drawable="@drawable/ic_{icon.id}_bg" />\n'
            f'    <foreground android:drawable="@drawable/ic_{icon.id}_fg" />\n'
            f'    <monochrome android:drawable="@drawable/ic_{icon.id}_mono" />\n'
            "</adaptive-icon>\n",
            encoding="utf-8",
            newline="\n",
        )
    rows = ",\n".join(
        f'  {{ id: "{i.id}", name: "{i.name}", hint: "{i.hint}",\n    svg: `{svg(i)}` }}' for i in ICONS
    )
    TS.write_text(
        "// generated by android/tools/gen_icons.py — the Android launcher icon options as inline SVG (108 × 108 adaptive\n"
        "// canvas; launchers show 18..90 through their mask). Edit the generator, not this file.\n"
        "export type AppIconOption = { id: string; name: string; hint: string; svg: string };\n\n"
        f"export const APP_ICONS: AppIconOption[] = [\n{rows},\n];\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{len(ICONS)} icons → {RES} and {TS}")


if __name__ == "__main__":
    main()

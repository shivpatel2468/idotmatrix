"""The DeskDot LED logo exists once in TypeScript (web/src/lib/logo.ts: the studio header and the boot intros) and as
plain-JS copies in the pages that can't import it (TV view, phone pages, web-app join/host). These tests keep every
copy identical — glyphs, tube split, colours, timings — so the logo can't drift between screens."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOGO_TS = ROOT / "web" / "src" / "lib" / "logo.ts"
NEON_MARK = ROOT / "web" / "src" / "components" / "NeonMark.tsx"
COPIES = [
    ROOT / "src" / "deskdot" / "tv" / "tv.js",
    ROOT / "src" / "deskdot" / "casino.html",
    ROOT / "src" / "deskdot" / "controller.html",
    ROOT / "web" / "webapp" / "join" / "join.js",
    ROOT / "web" / "webapp" / "host.js",
]
CONSTANTS = ["GLYPHS", "TUBES", "LOGO", "STRIKE", "DELAY"]
REGION = re.compile(r"// <deskdot-logo>.*?// </deskdot-logo>", re.S)


def _literal(src: str, name: str) -> object:
    """The value of `const NAME[: type] = <literal>;` — an object/array literal of strings and numbers."""
    m = re.search(rf"\bconst {name}\b[^=]*=\s*", src)
    assert m, f"no `const {name}`"
    i = m.end()
    opener = src[i]
    assert opener in "[{", f"{name} is not a literal"
    closer = {"[": "]", "{": "}"}[opener]
    depth, j, in_str = 0, i, False
    while True:
        c = src[j]
        if in_str:
            in_str = c != '"'
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                assert c == closer
                break
        j += 1
    text = src[i : j + 1]
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', text)  # bare keys
    text = re.sub(r",\s*([\]}])", r"\1", text)  # trailing commas
    return json.loads(text)


def _int(src: str, name: str) -> int:
    m = re.search(rf"\b{name}\s*=\s*(\d+)", src)
    assert m, f"no {name}"
    return int(m.group(1))


def _timeline(src: str, name: str) -> dict:
    m = re.search(rf"\bconst {name}\b[^=]*=\s*\{{([^}}]*)\}}", src)
    assert m, f"no `const {name}`"
    return {k: float(v) for k, v in re.findall(r"(\w+):\s*([\d.]+)", m.group(1))}


def _region(path: Path) -> str:
    found = REGION.findall(path.read_text(encoding="utf-8"))
    assert len(found) == 1, (
        f"{path.name}: expected one // <deskdot-logo> … // </deskdot-logo> block, found {len(found)}"
    )
    return found[0]


def _normalise(block: str) -> str:
    return "\n".join(line.strip() for line in block.splitlines())


@pytest.fixture(scope="module")
def reference() -> dict:
    ts = LOGO_TS.read_text(encoding="utf-8")
    ref = {name: _literal(ts, name) for name in CONSTANTS}
    ref["glitchLetter"] = _int(ts, "glitchLetter")
    ref["ROWS"] = _int(ts, "ROWS")
    ref["HEADER"] = _timeline(NEON_MARK.read_text(encoding="utf-8"), "HEADER")
    return ref


def test_reference_is_the_deskdot_logo(reference: dict) -> None:
    assert reference["TUBES"] == ["D", "esk", "Dot"]
    assert reference["LOGO"] == ["#ff3f78", "#ff3f78", "#ffcc33"]  # two shades: "Desk" rose, "Dot" gold
    assert set(reference["GLYPHS"]) == {"D", "e", "s", "k", "o", "t"}
    for ch, rows in reference["GLYPHS"].items():
        assert len(rows) == reference["ROWS"], ch
        assert len({len(r) for r in rows}) == 1, f"{ch}: ragged glyph"
    # the loose letter is the "o" of Dot
    letters = "".join(reference["TUBES"])
    assert letters[reference["glitchLetter"]] == "o"


@pytest.mark.parametrize("path", COPIES, ids=lambda p: p.name)
def test_copy_matches_logo_ts(path: Path, reference: dict) -> None:
    block = _region(path)
    for name in CONSTANTS:
        assert _literal(block, name) == reference[name], (
            f"{path.name}: {name} differs from web/src/lib/logo.ts"
        )
    assert _int(block, "glitchLetter") == reference["glitchLetter"]
    assert _int(block, "ROWS") == reference["ROWS"]
    assert _timeline(block, "HEADER") == reference["HEADER"], (
        f"{path.name}: timeline differs from NeonMark.tsx"
    )


@pytest.mark.parametrize("path", COPIES[1:], ids=lambda p: p.name)
def test_copies_are_identical(path: Path) -> None:
    assert _normalise(_region(path)) == _normalise(_region(COPIES[0])), (
        f"{path.name}: the logo block differs from tv.js"
    )


@pytest.mark.parametrize("path", COPIES, ids=lambda p: p.name)
def test_copy_is_used(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert "DeskDotLogo.mount(" in REGION.sub("", src), f"{path.name} carries the logo but never mounts it"

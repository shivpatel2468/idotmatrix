"""QR Code — Wi-Fi join, URL or text as a scannable QR code, encoded from scratch (ISO/IEC 18004).

The encoder covers what fits a 32×32 panel: byte mode, error correction L or M, versions 1–3 (21, 25 and 29
modules; every one of those is a single Reed–Solomon block, so there is no interleaving). The smallest version
that fits the payload is chosen, all eight masks are scored with the standard penalty rules and the best one
wins. `tests/test_newapps.py` checks the Reed–Solomon and format bits against published vectors and decodes the
rendered panel with OpenCV.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, to_rgb

# (data codewords, ec codewords) per (version, level) — single block each
CAPACITY: dict[tuple[int, str], tuple[int, int]] = {
    (1, "L"): (19, 7),
    (1, "M"): (16, 10),
    (2, "L"): (34, 10),
    (2, "M"): (28, 16),
    (3, "L"): (55, 15),
    (3, "M"): (44, 26),
}
ALIGN = {1: None, 2: 18, 3: 22}  # centre of the single alignment pattern
LEVEL_BITS = {"L": 0b01, "M": 0b00}


def max_bytes(version: int, level: str) -> int:
    """Payload bytes that fit in byte mode (4-bit mode + 8-bit count header)."""
    return (CAPACITY[(version, level)][0] * 8 - 12) // 8


# --------------------------------------------------------------------- GF(256) and Reed–Solomon
_EXP = [0] * 512
_LOG = [0] * 256
_v = 1
for _i in range(255):
    _EXP[_i] = _v
    _LOG[_v] = _i
    _v <<= 1
    if _v & 0x100:
        _v ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


@lru_cache(maxsize=16)
def _generator(n: int) -> tuple[int, ...]:
    """Coefficients of prod_{i<n} (x - a^i), highest degree first (leading 1 included)."""
    g = [1]
    for i in range(n):
        nxt = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            nxt[j] ^= c
            nxt[j + 1] ^= _gf_mul(c, _EXP[i])
        g = nxt
    return tuple(g)


def rs_ecc(data: list[int], n: int) -> list[int]:
    """Reed–Solomon error-correction codewords for `data` (polynomial long division)."""
    gen = _generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gf_mul(gen[j], c)
    return rem[len(data) :]


# --------------------------------------------------------------------- bit stream
def data_codewords(payload: bytes, version: int, level: str) -> list[int]:
    n_data, _ = CAPACITY[(version, level)]
    if len(payload) > max_bytes(version, level):
        raise ValueError("payload too long for this version")
    bits: list[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> (length - 1 - i)) & 1 for i in range(length))

    put(0b0100, 4)  # byte mode
    put(len(payload), 8)
    for b in payload:
        put(b, 8)
    cap = n_data * 8
    put(0, min(4, cap - len(bits)))  # terminator
    put(0, (8 - len(bits) % 8) % 8)
    words = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(words) < n_data:
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    return words


def format_bits(level: str, mask: int) -> int:
    """15-bit format information: level + mask, BCH(15,5), XOR 101010000010010."""
    data = (LEVEL_BITS[level] << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


# --------------------------------------------------------------------- matrix
MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Matrix:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = 17 + 4 * version
        n = self.size
        self.dark = [[False] * n for _ in range(n)]
        self.func = [[False] * n for _ in range(n)]
        self._function_patterns()

    def put(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.func[y][x] = True

    def _function_patterns(self) -> None:
        n = self.size
        for i in range(n):  # timing
            self.put(6, i, i % 2 == 0)
            self.put(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):  # finders + separators
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self.put(x, y, d not in (2, 4))
        a = ALIGN[self.version]
        if a is not None:
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    self.put(a + dx, a + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)  # reserve the format areas (real bits drawn later)
        self.put(8, n - 8, True)  # the dark module

    def draw_format(self, bits: int) -> None:
        n = self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.put(8, i, bit(i))
        self.put(8, 7, bit(6))
        self.put(8, 8, bit(7))
        self.put(7, 8, bit(8))
        for i in range(9, 15):
            self.put(14 - i, 8, bit(i))
        for i in range(8):
            self.put(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.put(8, n - 15 + i, bit(i))
        self.put(8, n - 8, True)

    def place(self, codewords: list[int]) -> None:
        """Zig-zag the codeword bits into the non-function modules, two columns at a time, bottom-right first."""
        n = self.size
        i = 0
        total = len(codewords) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.func[y][x] and i < total:
                        self.dark[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        fn = MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.func[y][x] and fn(x, y):
                    self.dark[y][x] = not self.dark[y][x]


def penalty(m: list[list[bool]]) -> int:
    """The four standard mask-penalty rules (N1=3, N2=3, N3=40, N4=10)."""
    n = len(m)
    score = 0
    lines = [row[:] for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]
    finder = [True, False, True, True, True, False, True]
    for line in lines:
        run, prev = 0, None
        for v in line:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + run - 5
                run, prev = 1, v
        if run >= 5:
            score += 3 + run - 5
        padded = [False] * 4 + line + [False] * 4
        for i in range(len(padded) - 6):
            if padded[i : i + 7] == finder:
                before = padded[max(0, i - 4) : i]
                after = padded[i + 7 : i + 11]
                if (len(before) == 4 and not any(before)) or (len(after) == 4 and not any(after)):
                    score += 40
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    dark = sum(sum(r) for r in m)
    score += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return score


@lru_cache(maxsize=32)
def encode(payload: bytes, level: str = "M", min_version: int = 1) -> tuple[tuple[bool, ...], ...]:
    """QR matrix (rows of booleans, True = dark) for `payload`; raises ValueError if it can't fit version 3."""
    for version in range(max(1, min_version), 4):
        if len(payload) <= max_bytes(version, level):
            break
    else:
        raise ValueError(f"too long: {len(payload)} bytes (max {max_bytes(3, level)} at level {level})")
    data = data_codewords(payload, version, level)
    words = data + rs_ecc(data, CAPACITY[(version, level)][1])
    best: tuple[int, list[list[bool]]] | None = None
    for mask in range(8):
        mat = _Matrix(version)
        mat.place(words)
        mat.apply_mask(mask)
        mat.draw_format(format_bits(level, mask))
        p = penalty(mat.dark)
        if best is None or p < best[0]:
            best = (p, mat.dark)
    assert best is not None
    return tuple(tuple(r) for r in best[1])


def wifi_payload(ssid: str, password: str, security: str, hidden: bool) -> str:
    """The de-facto Wi-Fi QR format: WIFI:T:WPA;S:ssid;P:pass;H:true;; with \\ ; , : " escaped."""

    def esc(s: str) -> str:
        return "".join("\\" + c if c in '\\;,:"' else c for c in s)

    parts = [f"T:{security}" if security != "nopass" else "T:nopass", f"S:{esc(ssid)}"]
    if security != "nopass":
        parts.append(f"P:{esc(password)}")
    if hidden:
        parts.append("H:true")
    return "WIFI:" + ";".join(parts) + ";;"


class QRSettings(AppSettings):
    mode: str = Choice("url", {"url": "URL", "wifi": "Wi-Fi join", "text": "Text"}, title="Content")
    text: str = Field(
        "https://example.com",
        max_length=53,
        title="URL / text",
        description="Up to 53 bytes at level L (42 at M). Shorter content gives bigger modules.",
    )
    ssid: str = Field(
        "MyNetwork", max_length=32, title="Wi-Fi name (SSID)", json_schema_extra={"group": "Wi-Fi"}
    )
    password: str = Field("", max_length=40, title="Wi-Fi password", json_schema_extra={"group": "Wi-Fi"})
    security: str = Choice(
        "WPA", {"WPA": "WPA/WPA2/WPA3", "WEP": "WEP", "nopass": "Open"}, title="Security", group="Wi-Fi"
    )
    hidden: bool = Field(False, title="Hidden network", json_schema_extra={"group": "Wi-Fi"})
    ecc: str = Choice(
        "M", {"L": "L (7 %, more room)", "M": "M (15 %, sturdier)"}, title="Error correction", group="Look"
    )
    dark: Color = Field("#000000", title="Module colour", json_schema_extra={"group": "Look"})
    light: Color = Field(
        "#ffffff",
        title="Background colour",
        description="Dark on light scans best.",
        json_schema_extra={"group": "Look"},
    )


@register
class QRCode(App):
    id = "qr"
    name = "QR Code"
    description = "Share your Wi-Fi, a link or a note as a scannable QR code (encoder written from scratch)."
    icon = "qr-code"
    category = "productivity"
    Settings = QRSettings
    fps = 1.0

    def payload(self) -> str:
        s = self.settings
        if s.mode == "wifi":
            return wifi_payload(s.ssid, s.password, s.security, s.hidden)
        return s.text

    def matrix(self) -> tuple[tuple[bool, ...], ...] | None:
        try:
            return encode(self.payload().encode("utf-8"), self.settings.ecc)
        except ValueError:
            return None

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        m = self.matrix()
        if m is None:
            n = len(self.payload().encode("utf-8"))
            f.text_center(8, "TOO BIG", PALETTE["amber"])
            f.text_center(16, f"{n}/{max_bytes(3, s.ecc)}B", PALETTE["mute"])
            f.text_center(23, "TRY L" if s.ecc == "M" else "SHORTEN", PALETTE["dim"])
            return
        dark, light = to_rgb(s.dark), to_rgb(s.light)
        f.clear(light)
        n = len(m)
        off = (32 - n) // 2
        for y, row in enumerate(m):
            for x, v in enumerate(row):
                if v:
                    f.set(off + x, off + y, dark)

    def status(self) -> dict[str, Any]:
        m = self.matrix()
        n = len(self.payload().encode("utf-8"))
        if m is None:
            return {"error": "too long", "bytes": n, "max": max_bytes(3, self.settings.ecc)}
        return {"version": (len(m) - 17) // 4, "modules": len(m), "bytes": n, "ecc": self.settings.ecc}

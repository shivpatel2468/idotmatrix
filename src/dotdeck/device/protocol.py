"""iDotMatrix BLE wire protocol — pure functions that return bytes.

Nothing here performs I/O. Every encoder is byte-for-byte compatible with the
reference `idotmatrix` 0.0.9 Python library (itself derived from the vendor's
BleProtocolN.java) and is pinned by tests/test_protocol.py.

GATT
    service   : vendor (discovered at runtime)
    write     : 0000fa02-0000-1000-8000-00805f9b34fb  (commands + data)
    notify    : 0000fa03-0000-1000-8000-00805f9b34fb  (acks, unused so far)
    adv name  : starts with "IDM-"

Short commands are `[len_lo, len_hi, cmd, sub, ...args]` where len counts the
whole packet. Bulk uploads (PNG / GIF) are split into 4 KiB chunks with a
header each; the transport then splits every chunk to the ATT MTU.

See docs/HARDWARE_PROTOCOL.md for the full reference.
"""

from __future__ import annotations

import struct
import zlib
from datetime import datetime

UUID_WRITE = "0000fa02-0000-1000-8000-00805f9b34fb"
UUID_NOTIFY = "0000fa03-0000-1000-8000-00805f9b34fb"
NAME_PREFIX = "IDM-"
UPLOAD_CHUNK = 4096


def _u8(v: int) -> int:
    return int(v) % 256


# ---------------------------------------------------------------- system
def screen_on() -> bytes:
    return bytes([5, 0, 7, 1, 1])


def screen_off() -> bytes:
    return bytes([5, 0, 7, 1, 0])


def brightness(percent: int) -> bytes:
    """Panel brightness, clamped to the firmware's accepted 5..100 %."""
    return bytes([5, 0, 4, 128, max(5, min(100, int(percent)))])


def flip(enabled: bool = True) -> bytes:
    """Rotate the panel 180°."""
    return bytes([5, 0, 6, 128, 1 if enabled else 0])


def freeze() -> bytes:
    """Toggle freezing of the current screen."""
    return bytes([4, 0, 3, 0])


def set_time(now: datetime | None = None) -> bytes:
    n = now or datetime.now()
    return bytes([11, 0, 1, 128, n.year % 100, n.month, n.day, n.weekday() + 1, n.hour, n.minute, n.second])


def speed(value: int) -> bytes:
    return bytes([5, 0, 3, 1, _u8(value)])


def password(pin: int) -> bytes:
    return bytes([8, 0, 4, 2, 1, (pin // 10000) % 256, (pin // 100) % 100 % 256, pin % 100 % 256])


def reset() -> list[bytes]:
    """Soft-reset sequence (fixes a panel that stopped responding to uploads)."""
    return [bytes.fromhex("04 00 03 80"), bytes.fromhex("05 00 04 80 50")]


# ------------------------------------------------------------ DIY / draw
def diy_mode(mode: int = 1) -> bytes:
    """Enter (1) or leave (0) DIY draw mode. Required before PNG frames or pixels.

    Entering DIY mode blanks the panel for ~200-400 ms, so the transport only
    sends it when the panel is not already in DIY mode.
    """
    return bytes([5, 0, 4, 1, _u8(mode)])


def pixel(x: int, y: int, r: int, g: int, b: int) -> bytes:
    """Set one LED in DIY mode (the vendor app's graffiti brush)."""
    return bytes([10, 0, 5, 1, 0, _u8(r), _u8(g), _u8(b), _u8(x), _u8(y)])


def image_upload(png: bytes) -> bytes:
    """Wrap a 32x32 PNG for DIY-mode display.

    Header per 4 KiB chunk: uint16 packet length (chunk + 9), 0, 0, (0 first | 2 cont),
    uint32 len(png), then the PNG bytes.

    The reference library writes ``len(png) + n_chunks`` in the length field instead. That only
    works for PNGs that fit one BLE packet; the true packet length (verified on hardware
    2026-09-24) works for every size.
    """
    chunks = [png[i : i + UPLOAD_CHUNK] for i in range(0, len(png), UPLOAD_CHUNK)]
    total = struct.pack("<I", len(png))
    out = bytearray()
    for i, chunk in enumerate(chunks):
        out += struct.pack("<H", len(chunk) + 9) + bytes([0, 0, 2 if i else 0]) + total + chunk
    return bytes(out)


def gif_upload(gif: bytes) -> list[bytes]:
    """Wrap a GIF as a list of chunks; the panel stores and loops it natively.

    Header (16 bytes): uint16 chunk_len, 1, 0, (0 first | 2 cont), uint32 len(gif),
    uint32 crc32(gif), 5, 0, 13. Each chunk must be written *with response*.
    """
    header = bytearray([255, 255, 1, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 5, 0, 13])
    header[5:9] = len(gif).to_bytes(4, "little")
    header[9:13] = zlib.crc32(gif).to_bytes(4, "little")
    out: list[bytes] = []
    for i in range(0, len(gif), UPLOAD_CHUNK):
        chunk = gif[i : i + UPLOAD_CHUNK]
        header[4] = 2 if i else 0
        header[0:2] = (len(chunk) + len(header)).to_bytes(2, "little")
        out.append(bytes(header) + chunk)
    return out


# ------------------------------------------------------ native firmware modes
def clock(
    style: int = 0, show_date: bool = True, hour24: bool = True, rgb: tuple[int, int, int] = (255, 255, 255)
) -> bytes:
    """Firmware clock. style 0..7 (vendor designs)."""
    if not 0 <= style <= 7:
        raise ValueError("clock style must be 0..7")
    flags = style | (128 if show_date else 0) | (64 if hour24 else 0)
    return bytes([8, 0, 6, 1, flags, _u8(rgb[0]), _u8(rgb[1]), _u8(rgb[2])])


def countdown(mode: int, minutes: int, seconds: int) -> bytes:
    """mode: 0 disable, 1 start, 2 pause, 3 restart."""
    if not 0 <= mode <= 3:
        raise ValueError("countdown mode must be 0..3")
    if not 0 <= seconds <= 59:
        raise ValueError("seconds must be 0..59")
    return bytes([7, 0, 8, 128, mode, _u8(minutes), seconds])


def chronograph(mode: int) -> bytes:
    """mode: 0 reset, 1 start, 2 pause, 3 continue."""
    if not 0 <= mode <= 3:
        raise ValueError("chronograph mode must be 0..3")
    return bytes([5, 0, 9, 128, mode])


def scoreboard(left: int, right: int) -> bytes:
    """Two counters, 0..999 each."""
    a = max(0, min(999, int(left)))
    b = max(0, min(999, int(right)))
    return bytes([8, 0, 10, 128, a & 0xFF, a >> 8, b & 0xFF, b >> 8])


def fullscreen_color(r: int, g: int, b: int) -> bytes:
    return bytes([7, 0, 2, 2, _u8(r), _u8(g), _u8(b)])


def effect(style: int, colors: list[tuple[int, int, int]]) -> bytes:
    """Firmware effects 0..6 with 2..7 colours.

    0 horizontal rainbow · 1 colour sparkles on black · 2 white sparkles on colour ·
    3 vertical rainbow · 4 diagonal-right rainbow · 5 diagonal-left rainbow · 6 random colour
    """
    if not 0 <= style <= 6:
        raise ValueError("effect style must be 0..6")
    if not 2 <= len(colors) <= 7:
        raise ValueError("effect needs 2..7 colours")
    body = [c for rgb in colors for c in (_u8(rgb[0]), _u8(rgb[1]), _u8(rgb[2]))]
    return bytes([6 + len(colors), 0, 3, 2, style, 90, len(colors), *body])


def eco(enabled: bool, start: tuple[int, int], end: tuple[int, int], brightness_percent: int) -> bytes:
    """Night mode: between start (h, m) and end (h, m) use `brightness_percent`."""
    return bytes(
        [10, 0, 2, 128, 1 if enabled else 0, start[0], start[1], end[0], end[1], _u8(brightness_percent)]
    )


def mic_type(kind: int) -> bytes:
    return bytes([6, 0, 11, 128, _u8(kind)])

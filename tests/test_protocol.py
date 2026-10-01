"""Wire-format pins. Expected bytes were produced by the reference `idotmatrix` 0.0.9 library
(verified byte-for-byte on 2026-09-24). If one of these fails, the panel will misbehave."""

import zlib
from datetime import datetime

import pytest

from deskdot.device import protocol as P


@pytest.mark.parametrize(
    ("packet", "expected"),
    [
        (P.brightness(42), "05 00 04 80 2a"),
        (P.brightness(1), "05 00 04 80 05"),  # clamped to firmware minimum
        (P.brightness(250), "05 00 04 80 64"),
        (P.screen_on(), "05 00 07 01 01"),
        (P.screen_off(), "05 00 07 01 00"),
        (P.flip(True), "05 00 06 80 01"),
        (P.freeze(), "04 00 03 00"),
        (P.diy_mode(1), "05 00 04 01 01"),
        (P.set_time(datetime(2026, 9, 24, 13, 5, 9)), "0b 00 01 80 1a 09 18 04 0d 05 09"),
        (P.clock(3, True, False, (10, 20, 30)), "08 00 06 01 83 0a 14 1e"),
        (P.clock(0, True, True, (255, 255, 255)), "08 00 06 01 c0 ff ff ff"),
        (P.scoreboard(300, 7), "08 00 0a 80 2c 01 07 00"),
        (P.countdown(1, 5, 30), "07 00 08 80 01 05 1e"),
        (P.chronograph(1), "05 00 09 80 01"),
        (P.pixel(4, 5, 1, 2, 3), "0a 00 05 01 00 01 02 03 04 05"),
        (P.fullscreen_color(9, 8, 7), "07 00 02 02 09 08 07"),
        (P.effect(2, [(1, 2, 3), (4, 5, 6), (7, 8, 9)]), "09 00 03 02 02 5a 03 01 02 03 04 05 06 07 08 09"),
    ],
)
def test_short_commands(packet: bytes, expected: str) -> None:
    assert packet.hex(" ") == expected


def test_image_upload_header() -> None:
    png = bytes(110)
    out = P.image_upload(png)
    # uint16 packet length (payload + 9), 0, 0, first-chunk flag, uint32 len, then the PNG.
    # Differs from the reference library's len+1: the true length is what current firmware needs.
    assert out[:9].hex(" ") == "77 00 00 00 00 6e 00 00 00"
    assert out[9:] == png


def test_image_upload_multichunk_flags() -> None:
    data = bytes(range(256)) * 40  # 10240 bytes -> 3 chunks
    out = P.image_upload(data)
    assert len(out) == len(data) + 3 * 9
    assert out[4] == 0 and out[9 + 4096 + 4] == 2
    assert int.from_bytes(out[:2], "little") == 4096 + 9


def test_gif_upload_chunks() -> None:
    gif = bytes(range(256)) * 20  # 5120 bytes -> 2 chunks
    chunks = P.gif_upload(gif)
    assert len(chunks) == 2
    h = chunks[0][:16]
    assert h.hex(" ") == "10 10 01 00 00 00 14 00 00 cb 22 02 67 05 00 0d"
    assert int.from_bytes(h[9:13], "little") == zlib.crc32(gif)
    assert chunks[1][4] == 2  # continuation flag
    assert int.from_bytes(chunks[1][:2], "little") == len(chunks[1])


@pytest.mark.parametrize(
    "bad",
    [
        lambda: P.clock(8),
        lambda: P.countdown(4, 0, 0),
        lambda: P.effect(7, [(0, 0, 0)] * 2),
        lambda: P.effect(0, [(0, 0, 0)]),
    ],
)
def test_validation(bad) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        bad()

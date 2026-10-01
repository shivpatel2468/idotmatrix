"""`deskdot` command line.

deskdot serve [--sim] [--address MAC] [--port N]   run engine + studio
deskdot scan                                      list nearby panels
deskdot doctor [--address MAC]                    connect and draw a test pattern
deskdot preview APP [--out file.png]              render an app without hardware
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import ClassVar

from . import __version__


def _serve(a: argparse.Namespace) -> None:
    import uvicorn

    from .config import load_config
    from .server import create_app

    cfg = load_config(
        Path(a.config) if a.config else None,
        device="sim" if a.sim else None,
        address=a.address,
        port=a.port,
        host=a.host,
    )
    logging.basicConfig(
        level=cfg.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="warning", ws_ping_interval=20)


def _scan(_a: argparse.Namespace) -> None:
    from .device.ble import scan

    found = asyncio.run(scan())
    if not found:
        print("No IDM-* panels found. Is it powered, and disconnected from the phone app?")
    for d in found:
        print(f"{d['address']}  {d['name']:<16} rssi {d['rssi']}")


def _doctor(a: argparse.Namespace) -> None:
    """Connect, draw corner markers + a colour ramp, report link stats."""
    from .config import load_config
    from .device import protocol as P
    from .device.ble import BleDevice
    from .gfx import Frame, hsv

    address = a.address or load_config().address

    async def run() -> None:
        dev = BleDevice(address)
        await dev.start()
        for _ in range(60):
            if dev.connected:
                break
            await asyncio.sleep(0.5)
        if not dev.connected:
            print(f"FAIL: could not connect ({dev.info.last_error})")
            await dev.stop()
            sys.exit(1)
        print(f"connected to {dev.info.name} {dev.info.address}, write chunk {dev.info.mtu} B")
        f = Frame()
        for x in range(32):
            f.vline(x, 12, 8, hsv(x / 32))
        for cx, cy in ((0, 0), (31, 0), (0, 31), (31, 31)):
            f.set(cx, cy, (255, 255, 255))
        f.rect(0, 0, 32, 32, (40, 40, 60), fill=False)
        f.text_center(3, "DESKDOT", (255, 72, 24))
        f.text_center(24, "OK", (0, 255, 120))
        dev.command(P.brightness(50))
        dev.show_frame(f.to_png())
        await asyncio.sleep(3)
        print(
            f"frames {dev.info.frames_sent}, bytes {dev.info.bytes_sent}, last write {dev.info.last_write_ms} ms"
        )
        print("You should see a rainbow band, white corners and 'OK'. Leaving it connected for 5 s…")
        await asyncio.sleep(5)
        await dev.stop()

    asyncio.run(run())


def _preview(a: argparse.Namespace) -> None:
    import json

    from . import apps  # noqa: F401 — registers built-ins
    from .engine import REGISTRY
    from .gfx import Frame

    cls = REGISTRY[a.app]

    class _Ctx:
        data: ClassVar[dict] = {}  # type: ignore[type-arg]
        library = None

        def provider(self, _n: str):  # type: ignore[no-untyped-def]
            class _P:
                value = None
                error = None
                art = None
                art_id = None
                position = 0.0

                def want(self, *_: object) -> None: ...
                def get(self, *_: object) -> None: ...

            return _P()

        def save(self) -> None: ...
        def invalidate(self) -> None: ...
        def notify(self, **_: object) -> None: ...

    app = cls(_Ctx(), cls.Settings.model_validate(json.loads(a.settings)))  # type: ignore[arg-type]
    f = Frame()
    app.render(f, a.t)
    Path(a.out).write_bytes(f.to_png(a.scale))
    print(f"wrote {a.out}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="deskdot", description=f"DeskDot {__version__} — iDotMatrix 32x32 engine"
    )
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the engine and the studio (default)")
    s.add_argument("--sim", action="store_true", help="use the simulated panel")
    s.add_argument("--address", help="panel MAC address (overrides config)")
    s.add_argument("--port", type=int)
    s.add_argument("--host")
    s.add_argument("--config", help="path to deskdot.toml")
    s.set_defaults(fn=_serve)
    sub.add_parser("scan", help="find nearby panels").set_defaults(fn=_scan)
    d = sub.add_parser("doctor", help="connect and draw a test pattern")
    d.add_argument(
        "--address", default=None, help="panel MAC (default: deskdot.toml, else the first IDM-* found)"
    )
    d.set_defaults(fn=_doctor)
    pv = sub.add_parser("preview", help="render one app frame to PNG (no hardware)")
    pv.add_argument("app")
    pv.add_argument("--settings", default="{}")
    pv.add_argument("--t", type=float, default=0.0)
    pv.add_argument("--scale", type=int, default=10)
    pv.add_argument("--out", default="preview.png")
    pv.set_defaults(fn=_preview)
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        a = p.parse_args(["serve", *(argv or sys.argv[1:])])
    a.fn(a)


if __name__ == "__main__":
    main()

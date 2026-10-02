"""Render the real animated preview of every app for idotmatrix.com, and copy the studio media the pages use.

    uv run python scripts/build_site_media.py                 # every app (takes a few minutes, one process)
    uv run python scripts/build_site_media.py clock weather   # just these apps
    uv run python scripts/build_site_media.py --no-network    # skip live data (data apps show their offline state)

Writes, per visible app:
    site/media/apps/<id>.gif      the animation at native 32×32 (the site scales it up with CSS and a dot mask)
    site/media/apps/<id>.png      a 32×32 still (shown first, and kept for visitors who prefer reduced motion)
    site/media/apps/og/<id>.png   a 480×480 LED-styled still for social cards (og:image)
and copies the studio screenshots/recordings from docs/media into site/media (plus WebP versions of the big ones),
so `site/` is a complete publish directory.

Previews use the engine's own paths (src/deskdot/previews.py): clip apps sample their real baked loop, every other
app is rendered frame by frame for a few seconds. Live data comes from the free public providers, fetched once for
a fixed demo location (never this machine's location). Providers that would read this computer (window titles,
media sessions, notifications, the screen, the camera, audio, photos, calendars…) are never started; a few get
fixed sample values instead so their apps don't sit on "loading".
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = SITE / "media" / "apps"
DOCS_MEDIA = ROOT / "docs" / "media"

# The public site shows these, so the data must not depend on (or reveal) where it was built.
DEMO_LOCATION = {"city": "San Francisco", "lat": 37.7749, "lon": -122.4194, "country": "US"}
# Public, key-less sources that are safe to fetch for a demo.
PUBLIC_PROVIDERS = {
    "airquality",
    "chess",
    "currency",
    "daily",
    "flights",
    "gamedeals",
    "github",
    "headlines",
    "holidays",
    "iss",
    "markets",
    "planets",
    "pokedex",
    "quakes",
    "rainradar",
    "sky",
    "space",
    "sports",
    "stocks",
    "tides",
    "trivia",
    "weather",
}
# Per-app settings for the preview (on top of the defaults) where the default needs personal input.
PREVIEW_SETTINGS: dict[str, dict[str, Any]] = {
    "github": {"user": "torvalds"},
}
# Studio screenshots/recordings the pages show (docs/media → site/media as WebP; every current browser decodes it).
COPY_MEDIA = [
    "studio.png",
    "studio-tour.gif",
    "studio-phone.png",
    "phone-controller.png",
    "studio-play.png",
    "studio-settings.png",
    "studio-multiplayer.png",
    "studio-flyview.png",
]
OG_SOURCE = "apps-grid.png"  # cropped to the 1200×630 social card (media/og.png)
# The home page's panel: a reel of these previews, back to back (media/hero-reel.gif).
HERO_REEL = [
    "synthwave",
    "clock",
    "petworld",
    "weather",
    "cycles",
    "nowplaying",
    "wireframe",
    "radar",
    "boids",
]
HERO_SECONDS = 3.2

STREAM_SECONDS = 4.0
STREAM_FPS = 8.0
GAME_SECONDS = 6.0
GAME_FPS = 10.0
MAX_CLIP_FRAMES = 120
OG_SIZE = 480

log = logging.getLogger("build_site_media")


# --------------------------------------------------------------------------- sample data for local-only providers
def _sample_art() -> Image.Image:
    """A made-up album cover: a sunset over a grid, so Now Playing has art to build its palette from."""
    img = Image.new("RGB", (128, 128))
    d = ImageDraw.Draw(img)
    for y in range(128):
        k = y / 127
        d.line([(0, y), (127, y)], fill=(int(40 + 200 * k), int(10 + 40 * k), int(90 - 40 * k)))
    d.ellipse([34, 30, 94, 90], fill=(255, 170, 60))
    for i in range(6):
        d.rectangle([30, 52 + i * 7, 98, 53 + i * 7], fill=(int(40 + 200 * (52 + i * 7) / 127), 20, 70))
    d.rectangle([0, 92, 127, 127], fill=(20, 6, 40))
    for x in range(-60, 190, 16):
        d.line([(64, 92), (x, 127)], fill=(255, 60, 160))
    for y in (96, 102, 110, 120):
        d.line([(0, y), (127, y)], fill=(255, 60, 160))
    return img


def _lock_private(hub: Any) -> None:
    """Providers that would read this computer never start: no fetch loop, no capture thread."""
    for name, p in hub.providers.items():
        if name in PUBLIC_PROVIDERS:
            continue
        p.acquire = p.release = p.refresh = lambda *_a, **_k: None
        if hasattr(p, "_start_thread"):
            p._start_thread = lambda *_a, **_k: None


class _SynthAudio:
    """Stands in for the audio-capture provider: a 120 BPM synthetic track, driven by the (simulated) clock, so
    the visualizer and the music-reactive pets move in their previews without listening to this machine."""

    name = "audio"
    error = None
    updated = 0.0
    supported = True

    def acquire(self) -> None: ...
    def release(self) -> None: ...
    def refresh(self) -> None: ...
    def snapshot(self) -> dict[str, Any]:
        return {"updated": None, "error": None, "active": False}

    async def stop(self) -> None: ...

    @property
    def value(self) -> dict[str, Any]:
        t = time.monotonic()
        beat_phase = (t * 2.0) % 1.0  # 120 BPM
        beat = max(0.0, 1.0 - beat_phase / 0.125)
        k = np.arange(32, dtype=np.float32)
        base = 0.85 * np.exp(-k / 11.0) + 0.12
        wobble = 0.22 * np.sin(t * 3.1 + k * 0.55) * np.sin(t * 1.7 + k * 0.21)
        bands = np.clip(base + wobble + beat * 0.35 * np.exp(-k / 5.0), 0, 1)
        return {
            "bands": bands.tolist(),
            "peaks": np.clip(bands + 0.08, 0, 1).tolist(),
            "level": float(0.05 + 0.05 * beat),
            "wave": (0.6 * np.sin(k * 0.6 + t * 9.0)).tolist(),
            "bass": float(bands[:6].mean()),
            "mid": float(bands[6:20].mean()),
            "treble": float(bands[20:].mean()),
            "beat": beat,
            "beats": int(t * 2.0),
            "bpm": 120.0,
            "music": True,
            "source": "system",
            "t": time.time(),
        }


def _inject_samples(hub: Any) -> None:
    now = time.time()
    hub.providers["audio"] = _SynthAudio()
    system = hub.providers.get("system")
    if system is not None:
        hist = [round(28 + 18 * abs(np.sin(i / 3.0)) + (i % 5) * 2) for i in range(32)]
        system.value = {
            "cpu": hist[-1],
            "ram": 61,
            "ram_used_gb": 9.8,
            "disk": 47,
            "net_down": 2.4e6,
            "net_up": 3.1e5,
            "battery": 84,
            "plugged": True,
            "uptime": 3 * 86400 + 5 * 3600,
            "cpu_hist": hist,
            "ram_hist": [58 + (i % 4) for i in range(32)],
        }
        system.updated = now
    media = hub.providers.get("media")
    if media is not None:
        media.value = {
            "active": True,
            "title": "Neon Skyline",
            "artist": "The Pixels",
            "album": "Thirty-Two",
            "playing": True,
            "position": 42.0,
            "duration": 214.0,
            "app": "spotify.exe",
            "is_spotify": True,
            "source": "spotify",
            "source_label": "Spotify",
            "art_id": "site-demo",
            "art_source": "demo",
            "palette": ["#ff3f78", "#ff7419", "#ffcc33", "#3a0f4f"],
            "track": "Neon Skyline\x1fThe Pixels",
        }
        media.art_image = _sample_art()
        media.art_id = "site-demo"
        media._playing, media._pos, media._pos_at, media._duration = True, 42.0, time.monotonic(), 214.0
        media.updated = now
    window = hub.providers.get("window")
    if window is not None:
        window.value = {
            "proc": "code.exe",
            "exe": "",
            "name": "VS Code",
            "title": "main.py - deskdot",
            "category": "code",
            "since": now - 1520,
            "top": [
                {"proc": "code.exe", "exe": "", "name": "VS Code", "seconds": 5400},
                {"proc": "chrome.exe", "exe": "", "name": "Chrome", "seconds": 2700},
                {"proc": "slack.exe", "exe": "", "name": "Slack", "seconds": 900},
            ],
        }
        window.updated = now


# --------------------------------------------------------------------------- image helpers
def _led_still(frame_img: Image.Image, size: int = OG_SIZE) -> Image.Image:
    """Upscale a 32×32 frame into round LEDs with a soft glow on a dark chassis."""
    cell = size // 32
    big = Image.new("RGB", (32 * cell, 32 * cell), (6, 6, 9))
    d = ImageDraw.Draw(big)
    px = frame_img.convert("RGB").load()
    r = cell * 0.40
    for y in range(32):
        for x in range(32):
            c = px[x, y]
            cx, cy = x * cell + cell / 2, y * cell + cell / 2
            lit = max(c) > 12
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c if lit else (20, 20, 26))
    glow = big.filter(ImageFilter.GaussianBlur(cell * 0.9))
    out = Image.blend(glow, big, 0.5)
    out = Image.composite(big, out, big.convert("L").point(lambda v: 255 if v > 30 else 0))
    if out.size != (size, size):
        canvas = Image.new("RGB", (size, size), (6, 6, 9))
        canvas.paste(out, ((size - out.width) // 2, (size - out.height) // 2))
        out = canvas
    return out


def _gif_info(data: bytes) -> tuple[int, int]:
    im = Image.open(io.BytesIO(data))
    n = getattr(im, "n_frames", 1)
    total = 0
    for i in range(n):
        im.seek(i)
        total += int(im.info.get("duration", 100))
    return n, total


# --------------------------------------------------------------------------- rendering
def _frames_for(engine: Any, app: Any) -> tuple[list[Any], list[int]]:
    from deskdot.apps.games_core import GameApp
    from deskdot.gfx import Frame

    try:
        is_clip = app.kind() == "clip"
    except Exception:
        is_clip = False
    if is_clip:
        clip = app.clip_frames()
        frames, durs = list(clip.frames), list(clip.durations_ms)
        while len(frames) > MAX_CLIP_FRAMES:  # merge pairs: same playback time, half the frames
            durs = [a + b for a, b in zip(durs[::2], [*durs[1::2], 0], strict=False)]
            frames = frames[::2]
        return [engine._panel(f) for f in frames], durs
    game = app.category == "games"
    seconds = GAME_SECONDS if game else STREAM_SECONDS
    fps = (
        GAME_FPS if game else max(2.0, min(STREAM_FPS, float(getattr(app, "fps", STREAM_FPS)) or STREAM_FPS))
    )
    if not game and float(getattr(app, "fps", 1.0)) < 2:
        fps = 4.0  # slow apps (clocks, dashboards): fewer, longer frames
    n = round(seconds * fps)
    # Apps that animate from the wall clock (games step their simulation from time.monotonic) get a simulated
    # clock that advances exactly one frame per render, so a 6 s preview takes milliseconds, not 6 s.
    real = time.monotonic
    start = real()
    sim = [start]
    game_clock = isinstance(app, GameApp)
    if game_clock:
        app._clock = lambda: sim[0]
    frames = []
    time.monotonic = lambda: sim[0]
    try:
        for i in range(n):
            sim[0] = start + i / fps
            f = Frame()
            try:
                app.render(f, 0.4 + i / fps)
            except Exception as e:
                log.warning("%s: render failed at frame %d: %s", app.id, i, e)
                f.text_center(13, "?", (255, 30, 60), font="small")
            frames.append(engine._panel(f))
    finally:
        time.monotonic = real
        if game_clock:
            del app._clock
    return frames, [round(1000 / fps)] * n


def _write(app_id: str, frames: list[Any], durs: list[int]) -> dict[str, Any]:
    from deskdot.gfx.image import encode_gif

    gif = encode_gif(frames, durs, max_colors=256)
    for colors in (128, 64, 32):  # keep each preview small
        if len(gif) <= 120_000:
            break
        gif = encode_gif(frames, durs, max_colors=colors)
    (OUT / f"{app_id}.gif").write_bytes(gif)
    # poster: a frame from ~40 % into the loop (past any intro), as the LEDs show it
    poster = frames[min(len(frames) - 1, int(len(frames) * 0.4))].to_image().convert("RGB")
    poster.save(OUT / f"{app_id}.png", optimize=True)
    _led_still(poster).save(OUT / "og" / f"{app_id}.png", optimize=True)
    n, ms = _gif_info(gif)
    return {"bytes": len(gif), "frames": n, "ms": ms}


async def render_all(only: list[str], network: bool, wait_s: float) -> dict[str, Any]:
    import deskdot.apps  # noqa: F401 — registers every built-in app
    from deskdot.config import Config, Store
    from deskdot.device import SimDevice
    from deskdot.engine import Engine
    from deskdot.engine.app import REGISTRY
    from deskdot.gfx import Frame
    from deskdot.providers import build_hub

    ids = [i for i, c in sorted(REGISTRY.items()) if not c.hidden]
    if only:
        unknown = set(only) - set(ids)
        if unknown:
            raise SystemExit(f"unknown app ids: {', '.join(sorted(unknown))}")
        ids = [i for i in ids if i in only]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "og").mkdir(exist_ok=True)

    report: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(device="sim", data_dir=Path(tmp))
        store = Store(Path(tmp) / "state.json")
        store.data["location"] = dict(DEMO_LOCATION)
        for app_id, patch in PREVIEW_SETTINGS.items():
            store.section("apps")[app_id] = dict(patch)
        hub = build_hub(store, lambda _n: None)
        engine = Engine(cfg, store, SimDevice(bytes_per_second=1e7, min_frame_interval=0.0), hub)
        _lock_private(hub)
        _inject_samples(hub)
        try:
            apps = {}
            for app_id in ids:
                app = engine._slot(app_id).app
                try:
                    app.on_start()
                    app.render(Frame(), 0.0)  # lets apps tell their providers what they want
                except Exception as e:
                    log.warning("%s: warm-up render failed: %s", app_id, e)
                apps[app_id] = app
            held = (
                sorted({u for a in apps.values() for u in a.uses if u in PUBLIC_PROVIDERS}) if network else []
            )
            for name in held:
                hub.get(name).acquire()
            if held:
                print(f"fetching live data: {', '.join(held)}", file=sys.stderr)
                deadline = time.monotonic() + wait_s
                while time.monotonic() < deadline:
                    pending = [n for n in held if hub.get(n).value is None and hub.get(n).error is None]
                    if not pending:
                        break
                    await asyncio.sleep(0.5)
                for a in apps.values():  # a second pass: some apps ask for more once the first data is in
                    try:
                        a.render(Frame(), 0.2)
                    except Exception:
                        pass
                await asyncio.sleep(3.0)
                for name in held:
                    p = hub.get(name)
                    state = "ok" if p.value is not None else f"none ({p.error or 'timeout'})"
                    print(f"  {name}: {state}", file=sys.stderr)
            for i, app_id in enumerate(ids, 1):
                t0 = time.perf_counter()
                frames, durs = _frames_for(engine, apps[app_id])
                info = _write(app_id, frames, durs)
                info["seconds"] = round(time.perf_counter() - t0, 2)
                report[app_id] = info
                print(
                    f"[{i:>2}/{len(ids)}] {app_id:<14} {info['frames']:>3} frames {info['ms'] / 1000:>5.1f}s "
                    f"{info['bytes'] / 1024:>6.1f} KB  ({info['seconds']} s)",
                    file=sys.stderr,
                )
                await asyncio.sleep(0)  # let provider tasks breathe between apps
        finally:
            await hub.close()
    return report


def _gif_frames(path: Path) -> tuple[list[Image.Image], list[int]]:
    im = Image.open(path)
    frames, durs = [], []
    for k in range(getattr(im, "n_frames", 1)):
        im.seek(k)
        frames.append(im.convert("RGB"))
        durs.append(int(im.info.get("duration", 100)))
    return frames, durs


def copy_media() -> dict[str, int]:
    """docs/media → site/media as WebP (the site must be self-contained), plus the 1200×630 social card."""
    dst = SITE / "media"
    dst.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for name in COPY_MEDIA:
        src = DOCS_MEDIA / name
        if not src.exists():
            log.warning("missing %s", src)
            continue
        webp = dst / (src.stem + ".webp")
        frames, durs = _gif_frames(src)
        if len(frames) > 1:
            frames[0].save(
                webp, save_all=True, append_images=frames[1:], duration=durs, loop=0, quality=55, method=6
            )
            poster = dst / (src.stem + "-poster.webp")
            frames[0].save(poster, quality=80, method=6)
            sizes[poster.name] = poster.stat().st_size
        else:
            frames[0].save(webp, quality=82, method=6)
        sizes[webp.name] = webp.stat().st_size
    src = DOCS_MEDIA / OG_SOURCE
    if src.exists():
        im = Image.open(src).convert("RGB")
        w, h = im.size
        ch = round(w * 630 / 1200)
        top = max(0, (h - ch) // 2)
        im.crop((0, top, w, top + min(ch, h))).resize((1200, 630), Image.LANCZOS).save(
            dst / "og.png", optimize=True
        )
        sizes["og.png"] = (dst / "og.png").stat().st_size
    return sizes


def build_hero_reel() -> int:
    """Back-to-back previews for the home page's panel, at 32×32 like the rest."""
    frames: list[Image.Image] = []
    durs: list[int] = []
    for app_id in HERO_REEL:
        path = OUT / f"{app_id}.gif"
        if not path.exists():
            continue
        fr, du = _gif_frames(path)
        acc = 0
        k = 0
        while acc < HERO_SECONDS * 1000:  # loop short previews until the slot is filled
            frames.append(fr[k % len(fr)])
            durs.append(du[k % len(du)])
            acc += du[k % len(du)]
            k += 1
        frames.append(Image.new("RGB", (32, 32)))  # a blink of black between apps, like the engine's cut
        durs.append(90)
    if not frames:
        return 0
    from deskdot.gfx import Frame
    from deskdot.gfx.image import encode_gif

    as_frames = [Frame(np.asarray(f, dtype=np.uint8).copy()) for f in frames]
    gif = encode_gif(as_frames, durs, max_colors=256)
    (SITE / "media" / "hero-reel.gif").write_bytes(gif)
    frames[1].save(SITE / "media" / "hero-reel.png", optimize=True)
    return len(gif)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apps", nargs="*", help="only these app ids")
    ap.add_argument("--no-network", action="store_true", help="don't fetch live data")
    ap.add_argument("--wait", type=float, default=25.0, help="seconds to wait for live data")
    ap.add_argument("--skip-copy", action="store_true", help="don't copy docs/media")
    ap.add_argument("--skip-apps", action="store_true", help="only copy docs/media")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not args.skip_copy:
        for name, n in copy_media().items():
            print(f"media/{name}: {n / 1024:.0f} KB", file=sys.stderr)
    if not args.skip_apps:
        report = asyncio.run(render_all(args.apps, not args.no_network, args.wait))
        total = sum(r["bytes"] for r in report.values())
        biggest = max(report.items(), key=lambda kv: kv[1]["bytes"]) if report else None
        print(f"{len(report)} previews, {total / 1024:.0f} KB of GIFs", file=sys.stderr)
        if biggest:
            print(f"largest: {biggest[0]} {biggest[1]['bytes'] / 1024:.0f} KB", file=sys.stderr)
        index = OUT / "index.json"
        old = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
        old.update(
            {k: {"frames": v["frames"], "ms": v["ms"], "bytes": v["bytes"]} for k, v in report.items()}
        )
        index.write_text(json.dumps(dict(sorted(old.items())), indent=1) + "\n", encoding="utf-8")
        n = build_hero_reel()
        print(f"media/hero-reel.gif: {n / 1024:.0f} KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

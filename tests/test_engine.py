"""Engine behaviour: routing, latest-frame-wins, playlist, overlays, temporary activation."""

from __future__ import annotations

import asyncio

from dotdeck.device import protocol as P
from dotdeck.engine import Notice, Playlist, PlaylistItem
from dotdeck.gfx import Frame


async def _run(engine, seconds: float) -> None:  # type: ignore[no-untyped-def]
    await engine.start()
    await asyncio.sleep(seconds)


async def test_stream_app_reaches_device(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("clock")
    await _run(engine, 0.6)
    dev = engine.device
    assert dev.info.status == "connected"
    assert dev.info.mode == "diy"
    assert dev.info.frames_sent >= 1
    assert any(w.startswith(P.diy_mode(1)) for w in dev.writes)
    await engine.stop()


async def test_clip_app_uploads_gif_once(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("agent", {"state": "thinking"})
    await _run(engine, 1.2)
    gifs = [w for w in engine.device.writes if w[2:3] == b"\x01" and w[13:16] == b"\x05\x00\x0d"]
    assert len(gifs) == 1, "a clip is uploaded once, then the panel plays it natively"
    assert engine.device.info.mode == "gif"
    await engine.stop()


async def test_latest_frame_wins() -> None:
    from dotdeck.device import SimDevice

    dev = SimDevice(bytes_per_second=2000, min_frame_interval=0.0)
    await dev.start()
    await asyncio.sleep(0.1)
    for i in range(50):
        dev.show_frame(Frame(fill=(i, 0, 0)).to_png())
    await asyncio.sleep(0.6)
    # far fewer than 50 frames go out, and the last one sent is the newest
    assert dev.info.frames_sent < 10
    assert dev.info.frames_dropped > 40
    await dev.stop()


def test_frame_supersedes_queued_gif() -> None:
    """A calibration pattern (or any newer frame) must not be overwritten by an older queued GIF."""
    from dotdeck.device import SimDevice

    dev = SimDevice()
    dev.show_gif(b"GIF89a...")
    dev.show_frame(Frame().to_png())
    assert dev._gif is None
    assert dev._frame is not None


async def test_commands_jump_the_frame_queue() -> None:
    from dotdeck.device import SimDevice

    dev = SimDevice(bytes_per_second=5000, min_frame_interval=0.0)
    await dev.start()
    await asyncio.sleep(0.1)
    dev.show_frame(Frame().to_png())
    dev.set_brightness(33)
    await asyncio.sleep(0.4)
    assert P.brightness(33) in dev.writes
    await dev.stop()


async def test_playlist_rotates_and_skips(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_playlist(
        Playlist(
            enabled=True,
            items=[
                PlaylistItem(app="clock", duration=3),
                PlaylistItem(app="text", duration=3, settings={"text": "HI"}),
            ],
        )
    )
    engine.playlist_control("play")
    await _run(engine, 0.3)
    assert engine.current.app.id == "clock"
    engine.playlist_control("next")
    await asyncio.sleep(0.3)
    assert engine.current.app.id == "text"
    assert engine.current.app.settings.text == "HI"  # per-item override
    await engine.stop()


async def test_notification_overlays_and_expires(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("clock")
    await _run(engine, 0.2)
    engine.notify(Notice(title="T", message="HELLO", duration=1.0))
    await asyncio.sleep(0.3)
    assert engine.overlay is not None
    await asyncio.sleep(1.2)
    assert engine.overlay is None
    await engine.stop()


async def test_temporary_activation_reverts(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("clock")
    await _run(engine, 0.2)
    engine.activate("agent", {"state": "working"}, revert_after=1.0)
    await asyncio.sleep(0.3)
    assert engine.current.app.id == "agent"
    engine.activate("agent", {"state": "done"}, revert_after=1.0)  # chained: still returns to clock
    await asyncio.sleep(1.4)
    assert engine.current.app.id == "clock"
    await engine.stop()


async def test_bad_render_shows_error_frame(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("clock")
    await _run(engine, 0.2)

    def boom(f, t):  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    engine.current.app.render = boom
    await asyncio.sleep(0.8)
    assert engine.current.error and "kaboom" in engine.current.error
    assert engine.frame.px.any()  # error frame, loop still alive
    await engine.stop()


async def test_handoff_clock_then_take_back(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("clock")
    await _run(engine, 0.4)
    dev = engine.device
    assert await engine.handoff("clock") == "clock"
    assert engine.released
    assert dev.info.mode == "native"
    assert any(w[2:4] == b"\x06\x01" for w in dev.writes), "firmware clock command sent"
    sent = dev.info.frames_sent
    await asyncio.sleep(0.4)
    assert dev.info.frames_sent == sent, "nothing streams over the hand-off"
    engine.activate("clock")  # showing anything takes the panel back
    assert not engine.released
    await asyncio.sleep(0.4)
    assert dev.info.frames_sent > sent
    await engine.stop()


async def test_handoff_app_uploads_a_loop(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_handoff({"mode": "app", "app": "ambient", "seconds": 3})
    await _run(engine, 0.3)
    assert await engine.handoff() == "app"
    assert engine.device.info.mode == "gif"
    await engine.stop()


async def test_handoff_on_exit(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_handoff({"mode": "clock", "on_exit": True})
    await _run(engine, 0.3)
    dev = engine.device
    await engine.stop()
    assert any(w[2:4] == b"\x06\x01" for w in dev.writes), "clock handed off before disconnecting"


async def test_gif_upload_is_never_abandoned_midway() -> None:
    """A half-sent GIF leaves the real firmware ignoring the next one: finish it, then send the newer one."""
    from dotdeck.device import SimDevice

    dev = SimDevice(bytes_per_second=20000, min_frame_interval=0.0)
    await dev.start()
    await asyncio.sleep(0.1)
    first, second = bytes(range(256)) * 40, bytes(reversed(range(256))) * 40  # ~10 KB each, several chunks
    dev.show_gif(first)
    await asyncio.sleep(0.05)  # first upload is in flight
    dev.show_gif(second)
    assert await dev.flush(10.0)
    chunks_a, chunks_b = P.gif_upload(first), P.gif_upload(second)
    joined = b"".join(dev.writes)
    assert all(c in joined for c in chunks_a), "the in-flight GIF was completed"
    assert all(c in joined for c in chunks_b), "then the newer GIF was sent"
    await dev.stop()


async def test_a_hung_connect_is_abandoned_and_retried() -> None:
    """After Windows sleeps, a Bluetooth connect can hang forever; the supervisor must give up and try again."""
    import asyncio

    from dotdeck.device import SimDevice

    class Hangs(SimDevice):
        attempts = 0

        async def _connect(self) -> None:
            type(self).attempts += 1
            if type(self).attempts == 1:
                await asyncio.Event().wait()  # never returns
            await super()._connect()

    dev = Hangs(min_frame_interval=0.0)
    dev.connect_timeout = 0.2
    await dev.start()
    try:
        for _ in range(100):
            if dev.connected:
                break
            await asyncio.sleep(0.05)
        assert dev.connected, "the supervisor recovered from a connect that never returned"
        assert Hangs.attempts == 2
    finally:
        await dev.stop()

"""Information-radiator apps: CI, uptime, OBS, 3D printer, media server, Anki.

Providers are exercised against trimmed real captures (GitHub) and spec-accurate fixtures
(tests/fixtures/maker), served through ``httpx.MockTransport`` or tiny local servers (HTTP, TCP and an
obs-websocket v5 fake). No test touches the network or the panel.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest

from dotdeck.apps import anki as anki_app
from dotdeck.apps import ci as ci_app
from dotdeck.apps import mediaserver as media_app
from dotdeck.apps import obs as obs_app
from dotdeck.apps import printer as printer_app
from dotdeck.apps import uptime as uptime_app
from dotdeck.apps._radiator import Alerts, fmt_age, fmt_eta
from dotdeck.gfx import Frame
from dotdeck.providers.anki import AnkiProvider, card_front, sum_stats
from dotdeck.providers.ci import CIProvider, parse_repos, run_state, summarize
from dotdeck.providers.mediaserver import (
    MediaServerProvider,
    parse_jellyfin_latest,
    parse_jellyfin_sessions,
    parse_plex_recent,
    parse_plex_sessions,
)
from dotdeck.providers.obs import OBSProvider, auth_string
from dotdeck.providers.printer import PrinterProvider, parse_moonraker, parse_octoprint
from dotdeck.providers.radiator import base_url, redact, safe_error
from dotdeck.providers.uptime import UptimeProvider, parse_targets

FX = Path(__file__).parent / "fixtures" / "maker"
SECRET = "s3cr3t-T0KEN-value"


def fx(name: str) -> Any:
    return json.loads((FX / name).read_text(encoding="utf-8"))


def hub_with(handler: Callable[[httpx.Request], httpx.Response] | None = None) -> Any:
    transport = httpx.MockTransport(handler) if handler else None
    http = (
        httpx.AsyncClient(transport=transport, timeout=3.0) if transport else httpx.AsyncClient(timeout=3.0)
    )
    changes: list[str] = []
    return SimpleNamespace(http=http, on_change=changes.append, changes=changes)


class Ctx:
    """Minimal AppContext for render tests."""

    def __init__(self, **providers: Any) -> None:
        self.providers = providers
        self.key = "test"
        self.notices: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}

    def provider(self, name: str) -> Any:
        return self.providers[name]

    def notify(self, **kw: Any) -> None:
        self.notices.append(kw)


def render_ms(app: Any, t: float = 1.0) -> tuple[Frame, float]:
    f = Frame()
    t0 = time.perf_counter()
    app.render(f, t)
    return f, (time.perf_counter() - t0) * 1000


# =============================================================================== shared helpers
def test_redaction_and_urls() -> None:
    assert SECRET not in redact(f"GET /x?api_key={SECRET} failed", SECRET)
    err = safe_error(httpx.ConnectError(f"boom {SECRET}"), SECRET)
    assert SECRET not in err and err.startswith("ConnectError")
    assert base_url("octopi.local", 80) == "http://octopi.local:80"
    assert base_url("https://nas:8920/", 8096) == "https://nas:8920"
    assert fmt_age(42) == "42S" and fmt_age(7200) == "2H" and fmt_eta(3900) == "1H05"


def test_alerts_prime_dedupe_and_skip_previews() -> None:
    p = CIProvider(hub_with())
    p._emit("broke", repo="a/b", workflow="Tests")  # before the app existed: never replayed
    a1, a2 = Alerts(Ctx(), p), Alerts(Ctx(), p)
    assert a1.drain(p) == []
    p._emit("broke", repo="a/b", workflow="Tests")
    assert [e["kind"] for e in a1.drain(p)] == ["broke"]
    assert a2.drain(p) == []  # a second slot doesn't announce it again
    preview = SimpleNamespace(key="preview:ci")
    p._emit("fixed", repo="a/b", workflow="Tests")
    assert Alerts(preview, None).drain(p) == []


# =============================================================================== CI
def test_ci_parse_and_summarize_real_capture() -> None:
    assert parse_repos("python/cpython, https://github.com/psf/black.git, bad, PYTHON/CPYTHON") == [
        "python/cpython",
        "psf/black",
    ]
    e = summarize("python/cpython", "main", fx("gh_runs_cpython_main.json"))
    assert e["state"] == "pass" and e["settled"] == "pass"
    assert e["last"]["name"] in {"Tests", "mypy", "Lint"} and len(e["runs"]) == 5
    assert run_state({"status": "in_progress"}) == "running"
    assert run_state({"status": "completed", "conclusion": "timed_out"}) == "fail"
    assert run_state({"status": "completed", "conclusion": "cancelled"}) == "cancelled"


def test_ci_head_commit_semantics() -> None:
    runs = fx("gh_runs_cpython_main.json")
    head = runs["workflow_runs"][0]["head_sha"]
    runs["workflow_runs"][1]["conclusion"] = "failure"  # another workflow on the same head commit failed
    runs["workflow_runs"][1]["head_sha"] = head
    assert summarize("r/r", "main", runs)["state"] == "fail"
    runs["workflow_runs"][0].update(status="in_progress", conclusion=None)
    e = summarize("r/r", "main", runs)
    assert e["state"] == "fail"  # a failure on the head commit outranks a run still going
    assert e["settled"] == "fail"


def test_ci_deploy_verdict_and_friday_rule() -> None:
    green = {"a/b": {"repo": "a/b", "state": "pass", "settled": "pass"}}
    thu = datetime(2026, 9, 24, 16, 0)
    fri_am, fri_pm, sat = (
        datetime(2026, 9, 25, 10, 0),
        datetime(2026, 9, 25, 15, 30),
        datetime(2026, 9, 26, 12),
    )
    assert ci_app.verdict(green, "friday", 15, thu)[0] == "YES"
    assert ci_app.verdict(green, "friday", 15, fri_am)[0] == "YES"
    assert ci_app.verdict(green, "friday", 15, fri_pm)[:2] == ("NOPE", "cancelled")
    assert ci_app.verdict(green, "always", 15, fri_pm)[0] == "YES"
    assert ci_app.verdict(green, "friday", 15, sat)[0] == "YES"
    assert ci_app.verdict(green, "weekend", 15, sat)[2] == "WEEKEND"
    red = {**green, "c/d": {"repo": "c/d", "state": "fail", "settled": "fail"}}
    assert ci_app.verdict(red, "always", 15, thu)[:2] == ("NO", "fail")
    running = {"a/b": {"repo": "a/b", "state": "running", "settled": "pass"}}
    assert ci_app.verdict(running, "always", 15, thu)[0] == "WAIT"
    assert ci_app.verdict({}, "always", 15, thu)[0] == "?"
    unread = {**green, "e/f": {"repo": "e/f", "state": "none", "settled": "none", "error": "boom"}}
    assert ci_app.verdict(unread, "always", 15, thu)[2] == "NO DATA"
    no_ci = {**green, "e/f": {"repo": "e/f", "state": "none", "settled": "none", "error": None}}
    assert ci_app.verdict(no_ci, "always", 15, thu)[0] == "YES"  # a repo without workflows doesn't block


def test_ci_budget_stays_under_60_per_hour() -> None:
    p = CIProvider(hub_with())
    for n in (1, 3, 8, 16):
        p.configure([f"o/r{i}" for i in range(n)], floor=60)
        polls_per_hour = 3600 / p.budget_interval()
        assert polls_per_hour * n <= 50  # one request per repo per poll, 10/h margin for branch lookups
    p.configure(["o/r"], token="x", floor=60)
    assert p.budget_interval() == 60  # a token lifts the budget; the floor still applies
    p._rate = {"remaining": 1, "reset": time.time() + 900}
    p.configure(["o/r"], token="", floor=60)
    assert p.next_interval() > 800  # nearly out of requests: wait for the reset


async def test_ci_fetch_with_token_etag_and_break_alert() -> None:
    runs = fx("gh_runs_cpython_main.json")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        hdr = {
            "x-ratelimit-remaining": "4990",
            "x-ratelimit-limit": "5000",
            "x-ratelimit-reset": "1790000000",
        }
        if req.url.path == "/repos/python/cpython":
            return httpx.Response(200, json=fx("gh_repo_cpython.json"), headers=hdr)
        if req.url.path == "/repos/python/cpython/actions/runs":
            if req.headers.get("if-none-match") == '"v1"' and not state["changed"]:
                return httpx.Response(304, headers=hdr)
            return httpx.Response(200, json=runs, headers={**hdr, "etag": '"v1"'})
        return httpx.Response(404)

    state = {"changed": False}
    hub = hub_with(handler)
    p = CIProvider(hub)
    p.configure(["python/cpython"], token=SECRET)
    v = await p.fetch()
    assert v["repos"]["python/cpython"]["state"] == "pass"
    q = seen[-1].url.params
    assert q["branch"] == "main" and q["event"] == "push" and q["per_page"] == "5"
    assert seen[-1].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(seen[-1].url)
    await p.fetch()
    assert seen[-1].headers.get("if-none-match") == '"v1"'  # conditional request: a 304 reuses the cache
    assert len([r for r in seen if r.url.path == "/repos/python/cpython"]) == 1  # branch cached
    assert p.events == []  # first observation only arms
    head = runs["workflow_runs"][0]["head_sha"]
    runs["workflow_runs"] = [
        dict(r, conclusion="failure") if r["head_sha"] == head else r for r in runs["workflow_runs"]
    ]
    state["changed"] = True
    await p.fetch()
    assert [e["kind"] for e in p.events] == ["broke"]
    app = ci_app.CI(Ctx(ci=p), ci_app.CISettings(repos="python/cpython", token=SECRET))
    app._alerts.seq = 0
    render_ms(app)
    assert app.ctx.notices and "BROKE" in app.ctx.notices[0]["message"]
    st = json.dumps(app.status())
    assert SECRET not in st and '"token": "set"' in st
    await hub.http.aclose()


async def test_ci_errors_are_redacted() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1"})

    hub = hub_with(handler)
    p = CIProvider(hub)
    p.configure(["python/cpython"], token=SECRET, branch="main")
    with pytest.raises(RuntimeError, match="rate limit") as ei:
        await p.fetch()
    assert SECRET not in str(ei.value)
    assert p.next_interval() >= 30  # held back until GitHub allows requests again
    n = len(p.requests)
    with pytest.raises(RuntimeError, match="rate limit"):
        await p.fetch()
    assert len(p.requests) == n  # no request while held
    await hub.http.aclose()


# =============================================================================== uptime
def test_uptime_targets() -> None:
    ts = parse_targets(
        "example.com, http://nas.local:8080/health, db.local:5432, NAS=10.0.0.2:445, ping://r, x y"
    )
    assert [t["kind"] for t in ts] == ["http", "http", "tcp", "tcp", "ping"]
    assert ts[0]["url"] == "https://example.com" and ts[0]["label"] == "EXAMPLE"
    assert ts[3]["label"] == "NAS" and ts[3]["port"] == 445
    assert parse_targets("api.github.com")[0]["label"] == "GITHUB"


@contextlib.asynccontextmanager
async def http_server(status: dict[str, int]):  # type: ignore[no-untyped-def]
    """A tiny HTTP/1.1 server whose status code the test can flip."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            await reader.readuntil(b"\r\n\r\n")
            code = status["code"]
            writer.write(f"HTTP/1.1 {code} X\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok".encode())
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()


async def test_uptime_http_tcp_and_transitions() -> None:
    status = {"code": 200}
    async with http_server(status) as port:
        closed = socket_free_port()
        hub = hub_with()
        p = UptimeProvider(hub)
        targets = parse_targets(
            f"WEB=http://127.0.0.1:{port}/, SOCK=127.0.0.1:{port}, DEAD=127.0.0.1:{closed}, ping://router"
        )
        p.configure(targets, confirm=2, timeout=2)
        v = await p.fetch()
        st = {s["label"]: s for s in v["targets"].values()}
        assert st["WEB"]["up"] is True and st["WEB"]["status"] == 200 and st["WEB"]["latency"] is not None
        assert st["SOCK"]["up"] is True and st["SOCK"]["latency"] is not None
        assert st["DEAD"]["up"] is False and st["DEAD"]["error"]
        assert st["ROUTER"]["up"] is None and "ICMP" in st["ROUTER"]["error"]
        assert p.events == []  # first check arms
        status["code"] = 503
        await p.fetch()
        assert p.events == []  # one failure isn't an outage (confirm=2)
        v = await p.fetch()
        assert [e["kind"] for e in p.events] == ["down"] and p.events[0]["label"] == "WEB"
        web = next(s for s in v["targets"].values() if s["label"] == "WEB")
        assert web["history"][-2:] == [None, None]
        status["code"] = 200
        await p.fetch()
        assert [e["kind"] for e in p.events] == ["down", "up"]
        await hub.http.aclose()


def socket_free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_uptime_app_flash_and_notify() -> None:
    p = UptimeProvider(hub_with())
    targets = parse_targets("A=a.example, B=b.example:22")
    now = time.time()
    p.value = {
        "targets": {
            targets[0]["key"]: {
                "label": "A",
                "kind": "http",
                "up": True,
                "latency": 80.0,
                "history": [80.0] * 30,
                "status": 200,
            },
            targets[1]["key"]: {
                "label": "B",
                "kind": "tcp",
                "up": False,
                "latency": None,
                "history": [None] * 5,
                "status": None,
                "error": "REFUSED",
            },
        },
        "checked": now,
    }
    ctx = Ctx(uptime=p)
    app = uptime_app.Uptime(ctx, uptime_app.UptimeSettings(targets="A=a.example, B=b.example:22"))
    render_ms(app, 1.0)
    p._emit("down", key=targets[1]["key"], label="B", error="REFUSED")
    f, _ = render_ms(app, 2.0)
    assert ctx.notices[-1]["title"] == "B" and "DOWN" in ctx.notices[-1]["message"]
    assert f.get(0, 0) == (255, 20, 60)  # the edge flashes red
    f, _ = render_ms(app, 9.0)
    assert f.get(15, 0) != (255, 20, 60)  # flash over after 4 s


# =============================================================================== OBS
@contextlib.asynccontextmanager
async def fake_obs(password: str | None, scene: str = "Main Camera"):  # type: ignore[no-untyped-def]
    """An obs-websocket v5 server per protocol.md: Hello → Identify (auth) → Identified, requests, events."""
    from websockets.asyncio.server import serve

    state = {"identified": 0, "streaming": True}
    salt, challenge = (
        "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
        "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=",
    )

    async def handler(ws: Any) -> None:
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.5.2", "rpcVersion": 1}
        if password is not None:
            hello["authentication"] = {"challenge": challenge, "salt": salt}
        await ws.send(json.dumps({"op": 0, "d": hello}))
        ident = json.loads(await ws.recv())
        assert ident["op"] == 1 and ident["d"]["rpcVersion"] == 1
        if password is not None:
            secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
            want = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
            if ident["d"].get("authentication") != want:
                await ws.close(4009, "Authentication failed.")
                return
        state["identified"] += 1
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            d = json.loads(raw)["d"]
            rt = d["requestType"]
            data: dict[str, Any] = {}
            if rt == "GetStreamStatus":
                data = {
                    "outputActive": state["streaming"],
                    "outputReconnecting": False,
                    "outputTimecode": "00:12:34.000",
                    "outputDuration": 754000,
                    "outputCongestion": 0.0,
                    "outputBytes": 1,
                    "outputSkippedFrames": 12,
                    "outputTotalFrames": 45000,
                }
            elif rt == "GetRecordStatus":
                data = {
                    "outputActive": False,
                    "outputPaused": False,
                    "outputTimecode": "00:00:00.000",
                    "outputDuration": 0,
                    "outputBytes": 0,
                }
            elif rt == "GetCurrentProgramScene":
                data = {"currentProgramSceneName": scene, "sceneName": scene}
            await ws.send(
                json.dumps(
                    {
                        "op": 7,
                        "d": {
                            "requestType": rt,
                            "requestId": d["requestId"],
                            "requestStatus": {"result": True, "code": 100},
                            "responseData": data,
                        },
                    }
                )
            )
            if rt == "GetCurrentProgramScene":
                await asyncio.sleep(0.05)
                await ws.send(
                    json.dumps(
                        {
                            "op": 5,
                            "d": {
                                "eventType": "CurrentProgramSceneChanged",
                                "eventIntent": 4,
                                "eventData": {"sceneName": "BRB", "sceneUuid": "x"},
                            },
                        }
                    )
                )

    async with serve(handler, "127.0.0.1", 0, subprotocols=["obswebsocket.json"]) as server:  # type: ignore[list-item]
        port = next(iter(server.sockets)).getsockname()[1]
        yield port, state


def test_obs_auth_string_matches_spec_construction() -> None:
    pw, salt, ch = (
        "supersecretpassword",
        "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
        "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=",
    )
    secret = base64.b64encode(hashlib.sha256((pw + salt).encode()).digest()).decode()
    assert (
        auth_string(pw, salt, ch)
        == base64.b64encode(hashlib.sha256((secret + ch).encode()).digest()).decode()
    )


async def test_obs_connects_authenticates_and_follows_events() -> None:
    async with fake_obs(SECRET) as (port, srv):
        hub = hub_with()
        p = OBSProvider(hub)
        p.configure("127.0.0.1", port, SECRET)
        v = p.value = await p.fetch()  # as the provider loop does
        assert srv["identified"] == 1
        assert v["state"] == "on" and v["streaming"] is True and v["skipped"] == 12
        assert 750 < time.time() - v["stream_since"] < 760
        await asyncio.sleep(0.3)  # the scene-change event arrives after the response
        assert p.value is not None and p.value["scene"] == "BRB"
        assert SECRET not in json.dumps(p.value)
        app = obs_app.OBS(Ctx(obs=p), obs_app.OBSSettings(port=port, password=SECRET))
        assert app.wants_focus() is True
        assert SECRET not in json.dumps(app.status())
        if p._ws is not None:
            await p._close(p._ws)
        await hub.http.aclose()


async def test_obs_wrong_password_and_obs_closed_are_quiet_values() -> None:
    async with fake_obs("right") as (port, _srv):
        p = OBSProvider(hub_with())
        p.configure("127.0.0.1", port, "wrong")
        v = await p.fetch()
        assert v["state"] == "auth"
    p2 = OBSProvider(hub_with())
    p2.configure("127.0.0.1", socket_free_port(), "")
    v2 = await p2.fetch()  # nothing listening: an idle value, not an exception
    assert v2["state"] == "off"
    assert p2.next_interval() >= 1.0
    f, _ = render_ms(obs_app.OBS(Ctx(obs=SimpleNamespace(value=v2, error=None)), obs_app.OBSSettings()))
    assert f.px.any()


async def test_obs_provider_loop_is_quiet_when_obs_is_closed() -> None:
    hub = hub_with()
    p = OBSProvider(hub)
    p.configure("127.0.0.1", socket_free_port(), "")
    p.acquire()
    for _ in range(80):  # Windows takes ~2 s to refuse a connection
        if p.value is not None:
            break
        await asyncio.sleep(0.1)
    assert p.value is not None and p.value["state"] == "off"
    assert p.error is None  # an idle value, so the provider loop logs nothing
    p.release()
    await p.stop()
    await hub.http.aclose()


# =============================================================================== printer
def test_printer_parsers() -> None:
    o = parse_octoprint(fx("octoprint_job_printing.json"), fx("octoprint_printer.json"))
    assert o["state"] == "printing" and round(o["progress"], 3) == 0.428 and o["left"] == 5039
    assert o["nozzle"] == [214.8, 215.0] and o["bed"] == [59.6, 60.0]
    assert parse_octoprint(fx("octoprint_job_done.json"), None)["state"] == "done"
    assert parse_octoprint(fx("octoprint_job_cancelled.json"), None)["state"] == "idle"
    m = parse_moonraker(fx("moonraker_printing.json"))
    assert m["state"] == "printing" and m["progress"] == 0.31 and m["nozzle"] == [244.6, 245.0]
    assert m["left"] is not None and 4400 < m["left"] < 4450  # extrapolated: 1987.2 / 0.31 - 1987.2
    assert parse_moonraker(fx("moonraker_complete.json"))["state"] == "done"


async def test_printer_octoprint_done_and_cancel_events() -> None:
    seq = {"job": "octoprint_job_printing.json"}
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/api/job":
            return httpx.Response(200, json=fx(seq["job"]))
        if req.url.path == "/api/printer":
            return httpx.Response(200, json=fx("octoprint_printer.json"))
        return httpx.Response(404)

    hub = hub_with(handler)
    p = PrinterProvider(hub)
    p.configure("octoprint", "octopi.local", 0, SECRET)
    v = await p.fetch()
    assert v["state"] == "printing" and seen[0].headers["x-api-key"] == SECRET
    assert str(seen[0].url) == "http://octopi.local/api/job"  # default port 80
    seq["job"] = "octoprint_job_done.json"
    v = await p.fetch()
    assert v["state"] == "done" and v["finished_at"] and [e["kind"] for e in p.events] == ["done"]
    seq["job"] = "octoprint_job_printing.json"
    await p.fetch()
    seq["job"] = "octoprint_job_cancelled.json"
    v = await p.fetch()
    assert v["state"] == "failed" and [e["kind"] for e in p.events] == ["done", "failed"]
    app = printer_app.Printer(
        Ctx(printer=p), printer_app.PrinterSettings(host="octopi.local", api_key=SECRET)
    )
    app._alerts.seq = 0
    render_ms(app)
    assert [n["title"] for n in app.ctx.notices] == ["PRINT DONE", "PRINT FAILED"]
    assert SECRET not in json.dumps(app.status())
    await hub.http.aclose()


async def test_printer_moonraker_and_offline() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/printer/objects/query"
        assert {"print_stats", "display_status", "extruder", "heater_bed"} <= set(req.url.params.keys())
        return httpx.Response(200, json=fx("moonraker_printing.json"))

    hub = hub_with(handler)
    p = PrinterProvider(hub)
    p.configure("moonraker", "voron.local", 0, "")
    v = await p.fetch()
    assert v["state"] == "printing" and v["kind"] == "moonraker" and "x-api-key" not in {k.lower() for k in v}
    await hub.http.aclose()

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused {SECRET}")

    hub2 = hub_with(down)
    p2 = PrinterProvider(hub2)
    p2.configure("octoprint", "octopi.local", 0, SECRET)
    v2 = await p2.fetch()
    assert v2["state"] == "offline" and SECRET not in json.dumps(v2)
    await hub2.http.aclose()


# =============================================================================== media server
def poster_png() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (200, 300))
    px = np.zeros((300, 200, 3), dtype=np.uint8)
    px[..., 0] = np.linspace(20, 230, 200)[None, :]
    px[..., 2] = np.linspace(200, 30, 300)[:, None]
    img = Image.fromarray(px)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_media_parsers() -> None:
    plex = parse_plex_recent(fx("plex_recently_added.json"))
    assert [(i["title"], i["sub"], i["kind"]) for i in plex] == [
        ("SEVERANCE", "S02E05", "TV"),
        ("DUNE: PART TWO", "2024", "MOVIE"),
        ("BLUE LINES", "MASSIVE ATTACK", "MUSIC"),
    ]
    assert plex[0]["art"] == "/library/metadata/48171/thumb/1739000000"  # the show's poster, not the still
    assert parse_plex_sessions(fx("plex_sessions.json"))[0]["progress"] == pytest.approx(0.45)
    jf = parse_jellyfin_latest(fx("jellyfin_latest.json"))
    assert jf[0]["art"] == "5e6f708192a3b4c5d6e7f8091a2b3c4d" and jf[0]["sub"] == "S02E05"
    assert jf[2]["sub"] == "3 NEW"
    assert len(parse_jellyfin_sessions(fx("jellyfin_sessions.json"))) == 1  # idle sessions skipped


@pytest.mark.parametrize("server", ["plex", "jellyfin"])
async def test_media_fetch_posters_and_token_in_header(server: str) -> None:
    seen: list[httpx.Request] = []
    png = poster_png()

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        routes = {
            "/library/recentlyAdded": fx("plex_recently_added.json"),
            "/status/sessions": fx("plex_sessions.json"),
            "/Users": fx("jellyfin_users.json"),
            "/Users/8c4b0e3c1a2d4b5e9f6a7b8c9d0e1f2a/Items/Latest": fx("jellyfin_latest.json"),
            "/Sessions": fx("jellyfin_sessions.json"),
        }
        if path in routes:
            return httpx.Response(200, json=routes[path])
        if path == "/photo/:/transcode" or path.endswith("/Images/Primary"):
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})
        return httpx.Response(404)

    hub = hub_with(handler)
    p = MediaServerProvider(hub)
    p.configure(server, "nas.local", 0, SECRET)
    v = await p.fetch()
    items = v["items"]
    assert len(items) == 3 and len(v["sessions"]) == 1
    assert items[0]["cover"].shape == (32, 32, 3) and items[0]["thumb"].shape == (15, 10, 3)
    for r in seen:
        assert SECRET not in str(r.url)  # the token only ever travels in a header
        assert SECRET in (r.headers.get("x-plex-token", "") + r.headers.get("x-emby-token", ""))
    assert seen[0].url.port == (32400 if server == "plex" else 8096)
    n = len(seen)
    await p.fetch()
    assert not [r for r in seen[n:] if "Images" in r.url.path or "transcode" in r.url.path]  # posters cached
    app = media_app.MediaServer(
        Ctx(mediaserver=p), media_app.MediaServerSettings(server=server, host="nas.local", token=SECRET)
    )
    for layout in ("poster", "shelf", "streams"):
        app.settings = app.Settings(server=server, host="nas.local", token=SECRET, layout=layout)
        f, ms = render_ms(app)
        assert f.px.any() and ms < 50
    assert SECRET not in json.dumps(app.status())
    await hub.http.aclose()


async def test_media_bad_token() -> None:
    hub = hub_with(lambda req: httpx.Response(401))
    p = MediaServerProvider(hub)
    p.configure("plex", "nas", 0, SECRET)
    assert (await p.fetch())["state"] == "auth"
    await hub.http.aclose()


# =============================================================================== Anki
def fake_anki(port_is_dotdeck: bool = False) -> Callable[[httpx.Request], httpx.Response]:
    replies = fx("ankiconnect.json")

    def handler(req: httpx.Request) -> httpx.Response:
        if port_is_dotdeck:  # the DotDeck engine answering on 8765: JSON, but not an AnkiConnect envelope
            return httpx.Response(405, json={"detail": "Method Not Allowed"})
        body = json.loads(req.content)
        assert body["version"] == 6
        return httpx.Response(200, json=replies[body["action"]])

    return handler


def test_anki_helpers() -> None:
    stats = fx("ankiconnect.json")["getDeckStats"]["result"]
    assert sum_stats(stats, "") == {"new": 20, "learn": 3, "review": 47, "total": 2140}  # top-level only
    assert sum_stats(stats, "Japanese::Kana")["review"] == 7
    card = fx("ankiconnect.json")["cardsInfo"]["result"][0]
    assert card_front(card) == "SAYONARA"
    assert (
        card_front({"fields": {"Text": {"value": "{{c1::Paris}} is the capital", "order": 0}}})
        == "PARIS IS THE CAPITAL"
    )


async def test_anki_counts_word_and_key() -> None:
    seen: list[dict[str, Any]] = []
    inner = fake_anki()

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return inner(req)

    hub = hub_with(handler)
    p = AnkiProvider(hub)
    p.configure("127.0.0.1", 8766, SECRET, "", word=True)
    v = await p.fetch()
    assert v["state"] == "ok" and v["due"] == 70 and v["reviewed"] == 38 and v["word"] == "SAYONARA"
    assert all(b.get("key") == SECRET for b in seen)
    assert str(p.url) == "http://127.0.0.1:8766"
    app = anki_app.Anki(Ctx(anki=p), anki_app.AnkiSettings(key=SECRET))
    assert SECRET not in json.dumps(app.status())
    await hub.http.aclose()


async def test_anki_port_clash_and_closed() -> None:
    hub = hub_with(fake_anki(port_is_dotdeck=True))
    p = AnkiProvider(hub)
    p.configure("127.0.0.1", 8765, "", "", word=False)
    assert (await p.fetch())["state"] == "conflict"
    p.configure("127.0.0.1", 9000, "", "", word=False)
    assert (await p.fetch())["state"] == "notanki"
    await hub.http.aclose()

    def refused(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    hub2 = hub_with(refused)
    p2 = AnkiProvider(hub2)
    assert (await p2.fetch())["state"] == "off"
    await hub2.http.aclose()
    assert anki_app.AnkiSettings().port == 8766


# =============================================================================== every app, every state
STATES: dict[str, list[Any]] = {
    "ci": [
        None,
        {"repos": {"python/cpython": summarize("python/cpython", "main", fx("gh_runs_cpython_main.json"))}},
    ],
    "uptime": [None, {"targets": {}}],
    "obs": [
        None,
        {"state": "off"},
        {"state": "auth"},
        {"state": "on", "streaming": True, "stream_since": time.time() - 4000, "scene": "X"},
    ],
    "printer": [
        None,
        {"state": "offline"},
        {"state": "idle"},
        parse_octoprint(fx("octoprint_job_printing.json"), fx("octoprint_printer.json")),
    ],
    "mediaserver": [None, {"state": "ok", "items": [], "sessions": []}, {"state": "auth"}],
    "anki": [
        None,
        {"state": "off"},
        {"state": "conflict", "port": 8765},
        {"state": "ok", "due": 0, "reviewed": 3},
    ],
}
APPS = {
    "ci": (ci_app.CI, {}),
    "uptime": (uptime_app.Uptime, {}),
    "obs": (obs_app.OBS, {}),
    "printer": (printer_app.Printer, {"host": "p"}),
    "mediaserver": (media_app.MediaServer, {"host": "m", "token": "t"}),
    "anki": (anki_app.Anki, {}),
}


@pytest.mark.parametrize("app_id", list(APPS))
def test_every_state_renders_fast(app_id: str) -> None:
    cls, base = APPS[app_id]
    for value in STATES[app_id]:
        for err in (None, "RuntimeError: boom"):
            p = SimpleNamespace(
                value=value, error=err, seq=0, events_since=lambda s: [], configure=lambda *a, **k: None
            )
            for layout in cls.Settings.model_fields["layout"].json_schema_extra["enum"]:  # type: ignore[index]
                app = cls(Ctx(**{app_id: p}), cls.Settings(**base, layout=layout))
                for t in (0.0, 3.3, 11.9):
                    _f, ms = render_ms(app, t)
                    assert ms < 50, f"{app_id}/{layout} took {ms:.1f} ms"
                json.dumps(app.status())
        app = cls(Ctx(), cls.Settings(**base))  # provider not registered at all
        render_ms(app)

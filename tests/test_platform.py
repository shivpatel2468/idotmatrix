"""Platform features: status indicators, custom push apps, On Air, eye break, ntfy and Home Assistant.

Everything runs offline: the Windows registry is a fake `winreg`, ntfy lines are literal strings, and Home
Assistant is an `httpx.MockTransport`.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from dotdeck.config import Config
from dotdeck.engine import PlaylistItem
from dotdeck.engine.persistent import (
    ActiveIndicator,
    Indicator,
    draw_indicators,
    draw_onair_badge,
    draw_onair_glow,
    indicator_origin,
)
from dotdeck.gfx import Frame
from dotdeck.gfx.image import GIF_BUDGET, encode_gif_budget
from dotdeck.providers import homeassistant as ha
from dotdeck.providers.custom import CustomApp
from dotdeck.providers.ntfy import parse_line, stream_url, topics_of
from dotdeck.providers.onair import CONSENT, filter_apps, friendly, scan_consent
from dotdeck.server import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


# =================================================================== API
def test_indicator_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.post("/api/indicators/1", json={"color": "#00ff78", "blink": True, "lifetime_s": 60})
        assert r.status_code == 200
        assert r.json()["indicator"]["blink"] == 1000
        assert c.post("/api/indicators/2", json={"color": [255, 170, 0], "size": 3}).status_code == 200
        assert c.post("/api/indicators/4", json={}).status_code == 422
        assert c.post("/api/indicators/1", json={"color": "nope"}).status_code == 422
        assert c.post("/api/indicators/1", json={"size": 5}).status_code == 422
        st = c.get("/api/state").json()["engine"]["indicators"]
        assert st["1"]["color"] == "#00ff78" and st["2"]["color"] == "#ffaa00"
        assert 0 < st["1"]["remaining_s"] <= 60
        assert c.delete("/api/indicators/2").json()["cleared"] is True
        assert set(c.get("/api/indicators").json()) == {"1"}


def test_custom_app_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        body = {"text": "OPEN", "icon": "door", "color": [255, 170, 0], "progress": 40, "duration": 8}
        r = c.post("/api/custom/garage", json=body)
        assert r.status_code == 200 and r.json()["app"]["color"] == "#ffaa00"
        assert c.post("/api/custom/bad name", json={"text": "x"}).status_code == 422
        assert c.post("/api/custom/x", json={"icon": "no-such-icon"}).status_code == 422
        assert c.post("/api/custom/x", json={"progress": 150, "text": "a"}).status_code == 422
        assert c.post("/api/custom/x", json={"rows": ["#?"], "palette": {"#": "#fff"}}).status_code == 422
        art = {"rows": ["#.", ".#"], "palette": {"#": "ember"}, "text": "HI"}
        assert c.post("/api/custom/art", json=art).json()["app"]["palette"] == {"#": "#ff4818"}
        names = {a["name"] for a in c.get("/api/custom").json()}
        assert names == {"garage", "art"}
        assert {a["name"] for a in c.get("/api/state").json()["engine"]["custom"]} == names
        # AWTRIX semantics: an empty body removes the app
        assert c.post("/api/custom/art", json={}).json()["removed"] is True
        assert c.delete("/api/custom/garage").status_code == 200
        assert c.delete("/api/custom/garage").status_code == 404
        # ?show=true pins it on screen
        c.post("/api/custom/temp?show=true", json={"text": "21.5°", "icon": "temp"})
        time.sleep(0.3)
        cur = c.get("/api/state").json()["engine"]["current"]
        assert cur["app"] == "custom"


def test_integrations_mask_and_keep_secrets(tmp_path: Path) -> None:
    secret = "eyJhbGciOiJIUzI1NiJ9.SECRET-TOKEN-9f3a"
    with _client(tmp_path) as c:
        r = c.patch("/api/integrations/homeassistant", json={"url": "http://ha.local:8123/", "token": secret})
        assert r.status_code == 200
        assert r.json() == {"url": "http://ha.local:8123", "token": "••••9f3a", "token_set": True}
        # sending the mask back (as the studio form does) keeps the stored token
        r = c.patch("/api/integrations/homeassistant", json={"url": "http://ha2:8123", "token": "••••9f3a"})
        assert r.json()["token_set"] is True
        for path in ("/api/state", "/api/integrations"):
            assert secret not in c.get(path).text
        assert c.app.state.engine.integration("homeassistant")["token"] == secret  # type: ignore[attr-defined]
        assert c.patch("/api/integrations/homeassistant", json={"token": ""}).json()["token_set"] is False
        assert c.patch("/api/integrations/homeassistant", json={"url": "ftp://x"}).status_code == 422
        assert c.patch("/api/integrations/nope", json={}).status_code == 404
        r = c.patch("/api/integrations/ntfy", json={"topics": "phone-alerts", "token": "tk_abcdef"})
        assert r.json()["token"] == "••••cdef"
        assert "tk_abcdef" not in c.get("/api/state").text
        assert c.patch("/api/integrations/eyebreak", json={"interval_min": 1}).status_code == 422
        assert c.patch("/api/integrations/onair", json={"style": "glow"}).json()["style"] == "glow"
        assert c.post("/api/integrations/homeassistant/test").json()["ok"] is False  # no token any more


def test_onair_simulation_takes_over_and_releases(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        c.put("/api/playlist", json={"enabled": True, "items": [{"app": "clock", "duration": 60}]})
        c.post("/api/playlist/play")
        c.patch("/api/integrations/onair", json={"style": "full"})
        c.post("/api/onair/simulate", json={"seconds": 30})
        time.sleep(0.5)
        eng = c.get("/api/state").json()["engine"]
        assert eng["takeover"] == "onair" and eng["current"]["app"] == "onair"
        assert eng["onair"]["glyph"] == "both"
        c.post("/api/onair/simulate", json={"seconds": 0})
        time.sleep(0.5)
        eng = c.get("/api/state").json()["engine"]
        assert eng["takeover"] is None and eng["current"]["app"] == "clock"
        c.post("/api/eyebreak/now")
        time.sleep(0.4)
        assert c.get("/api/state").json()["engine"]["current"]["app"] == "eyebreak"


# ============================================================== overlays
def test_indicators_draw_at_corners() -> None:
    now = 100.0
    f = Frame(fill=(40, 40, 40))
    inds = {
        1: ActiveIndicator(Indicator(color="#00ff00"), now),
        2: ActiveIndicator(Indicator(color="#0000ff", size=3), now),
        3: ActiveIndicator(Indicator(color="#ff0000"), now),
    }
    draw_indicators(f, inds, now)
    assert f.get(31, 0) == (0, 255, 0) and f.get(30, 1) == (0, 255, 0)
    x, y = indicator_origin(2, 3)
    assert (x, y) == (29, 14) and f.get(31, 16) == (0, 0, 255)
    assert f.get(31, 31) == (255, 0, 0)
    assert f.get(29, 0) == (0, 0, 0), "a black halo separates the indicator from the app"
    assert f.get(10, 10) == (40, 40, 40), "the rest of the frame is untouched"


def test_indicator_blink_fade_and_lifetime() -> None:
    blink = ActiveIndicator(Indicator(blink=1000), now=0.0)
    assert blink.level(0.1) == 1.0 and blink.level(0.6) == 0.0 and blink.animated
    fade = ActiveIndicator(Indicator(fade=2000), now=0.0)
    assert fade.level(0.0) < 0.2 < fade.level(1.0)
    life = ActiveIndicator(Indicator(lifetime_s=5), now=0.0)
    assert not life.expired(4.9) and life.expired(5.0)
    assert not ActiveIndicator(Indicator(), now=0.0).expired(1e9)


def test_onair_badge_and_glow() -> None:
    f = Frame(fill=(0, 80, 0))
    draw_onair_badge(f, "mic", 0.0)
    reds = sum(1 for x in range(8) for y in range(9) if f.get(x, y)[0] > 150 and f.get(x, y)[1] < 60)
    assert reds >= 12
    assert f.get(20, 20) == (0, 80, 0)
    g = Frame()
    draw_onair_glow(g, 1.2)
    assert g.get(0, 0)[0] > 200 and g.get(31, 15)[0] > 200 and g.get(15, 15) == (0, 0, 0)


async def test_persistent_overlays_force_streaming(engine) -> None:  # type: ignore[no-untyped-def]
    engine.activate("agent", {"state": "thinking"})  # a clip app
    engine.set_indicator(1, Indicator(color="#00ff00"))
    await engine.start()
    await asyncio.sleep(0.6)
    assert engine.frame.get(31, 0) == (0, 255, 0)
    assert engine._persist_drawn
    engine.clear_indicator(1)
    await asyncio.sleep(0.4)
    assert not engine._persist_drawn
    await engine.stop()


async def test_onair_badge_style_draws_over_app(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_integration("onair", {"style": "badge"})
    engine.activate("clock")
    engine.simulate_onair(30)
    await engine.start()
    await asyncio.sleep(0.4)
    assert engine.current.app.id == "clock" and engine.takeover is None
    assert engine.frame.get(2, 2)[0] > 150  # the red cam glyph in the corner
    await engine.stop()


# ========================================================== custom apps
def test_custom_app_expiry(engine) -> None:  # type: ignore[no-untyped-def]
    prov = engine.hub.get("custom")
    now = time.time()
    prov.push("short", CustomApp(text="A", lifetime=5), now=now)
    prov.push("forever", CustomApp(text="B"), now=now)
    assert set(prov.fresh(now + 4)) == {"short", "forever"}
    assert set(prov.fresh(now + 6)) == {"forever"}
    assert "short" not in engine.store.get("custom_apps")


def test_custom_apps_join_playlist_while_fresh(engine) -> None:  # type: ignore[no-untyped-def]
    from dotdeck.engine import Playlist

    engine.set_playlist(Playlist(enabled=True, items=[PlaylistItem(app="clock", duration=10)]))
    engine.push_custom("door", CustomApp(text="OPEN", icon="door", duration=7))
    items = engine._playlist_items()
    assert [i.app for i in items] == ["clock", "custom"]
    assert items[1].duration == 7 and items[1].settings == {"name": "door"}
    slot = engine._slot("custom", items[1])
    assert slot.app.relevant()
    engine.remove_custom("door")
    assert [i.app for i in engine._playlist_items()] == ["clock"]
    assert not slot.app.relevant()


def test_custom_apps_survive_restart(tmp_path: Path) -> None:
    from dotdeck.config import Store
    from dotdeck.providers import build_hub

    store = Store(tmp_path / "state.json")
    build_hub(store, lambda _n: None).get("custom").push("x", CustomApp(text="KEEP"))  # type: ignore[attr-defined]
    store.save_now()
    again = build_hub(Store(tmp_path / "state.json"), lambda _n: None).get("custom")
    assert again.value["x"]["text"] == "KEEP"


def test_custom_scrolling_is_a_seamless_clip(engine) -> None:  # type: ignore[no-untyped-def]
    engine.push_custom("long", CustomApp(text="WASHING MACHINE IS DONE", icon="drop"))
    engine.push_custom("short", CustomApp(text="21°", icon="temp"))
    long_app = engine._slot("custom", PlaylistItem(app="custom", settings={"name": "long"})).app
    short_app = engine._slot("custom", PlaylistItem(app="custom", settings={"name": "short"})).app
    assert long_app.kind() == "clip" and short_app.kind() == "stream"
    clip = long_app.clip_frames()
    assert clip.frames[0] == long_app.clip_frames().frames[0]
    assert len(encode_gif_budget(clip.frames, clip.durations_ms, long_app.clip_colors)) <= GIF_BUDGET


# =============================================================== on air
class FakeWinreg:
    """Just enough of `winreg` for scan_consent: nested dict nodes of subkeys and values."""

    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, tree: dict[str, Any]) -> None:
        self.tree = tree

    def OpenKey(self, parent: Any, path: str) -> dict[str, Any]:
        node = self.tree if parent == "HKCU" else parent
        for part in path.split("\\"):
            if part not in node.get("keys", {}):
                raise OSError(path)
            node = node["keys"][part]
        return node

    def EnumKey(self, node: dict[str, Any], i: int) -> str:
        keys = list(node.get("keys", {}))
        if i >= len(keys):
            raise OSError
        return keys[i]

    def EnumValue(self, node: dict[str, Any], i: int) -> tuple[str, Any, int]:
        vals = list(node.get("values", {}).items())
        if i >= len(vals):
            raise OSError
        return vals[i][0], vals[i][1], 11


def _consent_tree() -> dict[str, Any]:
    def app(start: int, stop: int) -> dict[str, Any]:
        return {"values": {"LastUsedTimeStart": start, "LastUsedTimeStop": stop}}

    webcam = {
        "keys": {
            "MSTeams_8wekyb3d8bbwe": app(134347280062076757, 0),  # in use now
            "Microsoft.WindowsCamera_8wekyb3d8bbwe": app(134345569245931650, 134345569272583300),
            "Claude_pzs8sxrjxfjjc": {"values": {}},  # never used
            "NonPackaged": {
                "keys": {
                    "C:#Program Files#Zoom#bin#Zoom.exe": app(1, 0),
                    "C:#Python#python.exe": app(1, 0),  # DotDeck itself (ignored)
                }
            },
        }
    }
    mic = {
        "keys": {
            "NonPackaged": {"keys": {"C:#Program Files#Google#Chrome#Application#chrome.exe": app(5, 9)}}
        }
    }
    node: dict[str, Any] = {"keys": {"webcam": webcam, "microphone": mic}}
    root: dict[str, Any] = node
    for part in reversed(CONSENT.split("\\")):
        root = {"keys": {part: root}}
    return root


def test_onair_registry_parsing() -> None:
    fake = FakeWinreg(_consent_tree())
    found = scan_consent(fake, ignore={"c:#python#python.exe"})
    assert found["webcam"] == ["MSTeams_8wekyb3d8bbwe", "C:#Program Files#Zoom#bin#Zoom.exe"]
    assert found["microphone"] == []
    assert filter_apps(found, {"webcam", "microphone"}, "") == {"webcam": ["MSTeams", "Zoom"]}
    assert filter_apps(found, {"webcam"}, "zoom, teams") == {}
    assert filter_apps(found, {"microphone"}, "") == {}
    assert friendly("Microsoft.WindowsCamera_8wekyb3d8bbwe") == "WindowsCamera"
    assert scan_consent(FakeWinreg({"keys": {}})) == {"webcam": [], "microphone": []}


async def test_onair_engine_follows_provider(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_integration("onair", {"enabled": True, "webcam": True, "microphone": False, "exclude": "obs"})
    prov = engine.hub.get("onair")
    prov.value = {"supported": True, "in_use": {"webcam": ["C:#obs#obs64.exe"], "microphone": ["Zoom"]}}
    engine._update_onair(time.monotonic())
    assert engine.onair["active"] is False  # obs excluded, microphone not watched
    prov.value = {"supported": True, "in_use": {"webcam": ["MSTeams_8wekyb3d8bbwe"], "microphone": []}}
    engine._update_onair(time.monotonic())
    assert engine.onair["active"] and engine.onair["glyph"] == "cam"
    assert engine._select(time.monotonic()).app.id == "onair"
    prov.value = {"supported": True, "in_use": {"webcam": [], "microphone": []}}
    engine._update_onair(time.monotonic())
    assert engine._select(time.monotonic()).app.id != "onair"
    assert engine.takeover is None


# ============================================================ eye break
async def test_eyebreak_fires_after_interval_but_not_on_air_or_fullscreen(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_integration("eyebreak", {"enabled": True, "interval_min": 20})
    idle = engine.hub.get("idle")
    idle.value = {"supported": True, "idle_s": 1.0, "fullscreen": False}
    now = time.monotonic()
    engine._active_since = now - 19 * 60
    engine._update_eyebreak(now)
    assert not engine._break_until
    engine._active_since = now - 21 * 60
    idle.value = {"supported": True, "idle_s": 1.0, "fullscreen": True}
    engine._update_eyebreak(now)
    assert not engine._break_until, "never during a full-screen game"
    idle.value = {"supported": True, "idle_s": 1.0, "fullscreen": False}
    engine.hub.get("onair").value = {"supported": True, "in_use": {"microphone": ["Zoom"]}}
    engine._update_eyebreak(now)
    assert not engine._break_until, "never while on a call"
    engine.hub.get("onair").value = {"supported": True, "in_use": {}}
    engine._update_eyebreak(now)
    assert engine._break_until > now
    assert engine._select(now).app.id == "eyebreak"
    engine._update_eyebreak(engine._break_until + 0.1)
    assert not engine._break_until and engine._active_since > now


async def test_eyebreak_idle_resets_timer(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_integration("eyebreak", {"enabled": True, "interval_min": 20})
    engine.hub.get("idle").value = {"supported": True, "idle_s": 300.0, "fullscreen": False}
    now = time.monotonic()
    engine._active_since = now - 30 * 60
    engine._update_eyebreak(now)
    assert not engine._break_until and engine._active_since == now


# ================================================================= ntfy
def test_ntfy_line_parsing() -> None:
    assert parse_line('{"id":"a1","time":1,"event":"open","topic":"t"}') is None
    assert parse_line('{"id":"k","time":1,"event":"keepalive","topic":"t"}') is None
    assert parse_line("not json") is None and parse_line("") is None
    m = parse_line(
        '{"id":"sPs71M8x","time":1790000000,"event":"message","topic":"phone",'
        '"title":"Garage","message":"Door left open","priority":5,"tags":["warning","app-garage"]}'
    )
    assert m == {
        "id": "sPs71M8x",
        "topic": "phone",
        "title": "Garage",
        "message": "Door left open",
        "priority": 5,
        "tags": ["warning", "app-garage"],
        "time": 1790000000,
    }
    assert parse_line('{"event":"message","message":"hi","priority":"9"}')["priority"] == 5
    assert topics_of(" a, b-c ,bad topic!,") == ["a", "b-c"]
    assert stream_url("https://ntfy.sh/", ["a", "b"]) == "https://ntfy.sh/a,b/json"


def test_ntfy_messages_become_notices_or_custom_apps(engine) -> None:  # type: ignore[no-untyped-def]
    engine.set_integration("ntfy", {"enabled": False, "route_prefix": "app-", "lifetime": 600})
    engine._on_event(
        "ntfy", {"title": "Backup", "message": "done", "priority": 3, "tags": ["white_check_mark"]}
    )
    n = engine.notices[-1]
    assert (n.title, n.message, n.icon, n.style, n.color) == ("BACKUP", "done", "ok", "banner", "#00dcff")
    engine._on_event("ntfy", {"title": "", "topic": "alerts", "message": "Smoke!", "priority": 5, "tags": []})
    n = engine.notices[-1]
    assert n.style == "full" and n.color == "#ff143c" and n.title == "ALERTS"
    before = len(engine.notices)
    engine._on_event("ntfy", {"message": "OPEN", "priority": 4, "tags": ["door", "app-garage"]})
    assert len(engine.notices) == before, "routed messages don't pop up"
    entry = engine.hub.get("custom").value["garage"]
    assert entry["text"] == "OPEN" and entry["icon"] == "door" and entry["expires"]


# ======================================================= home assistant
def test_ha_parsers() -> None:
    st = ha.parse_state(
        {
            "entity_id": "sensor.t",
            "state": "21.4",
            "attributes": {
                "unit_of_measurement": "°C",
                "friendly_name": "Office",
                "device_class": "temperature",
            },
        }
    )
    assert st["value"] == 21.4 and st["unit"] == "°C" and st["name"] == "Office"
    assert ha.parse_state({"entity_id": "light.x", "state": "on", "attributes": {}})["value"] is None
    hist = [[{"state": "20"}, {"state": "unavailable"}, {"state": "21.5"}]]
    assert ha.parse_history(hist) == [20.0, 21.5]
    assert ha.parse_history([]) == [] and ha.parse_history({"x": 1}) == []
    assert ha.mask("abcdefgh") == "••••efgh" and ha.mask("") == ""


async def test_ha_provider_polls_states_and_history(engine) -> None:  # type: ignore[no-untyped-def]
    token = "LONG-LIVED-TOKEN-xyz"
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == f"Bearer {token}"
        seen.append(req.url.path)
        if req.url.path == "/api/states/sensor.power":
            return httpx.Response(
                200,
                json={
                    "entity_id": "sensor.power",
                    "state": "350",
                    "attributes": {"unit_of_measurement": "W"},
                },
            )
        if req.url.path.startswith("/api/history/period/"):
            assert req.url.params["filter_entity_id"] == "sensor.power"
            return httpx.Response(200, json=[[{"state": "100"}, {"state": "200"}, {"state": "300"}]])
        return httpx.Response(404, json={"message": "Entity not found."})

    engine.hub.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    engine.set_integration("homeassistant", {"url": "http://ha.test:8123", "token": token})
    prov = engine.hub.get("homeassistant")
    prov.want("sensor.power", 10, 6)
    prov.want("sensor.missing", 10, 0)
    data = await prov.fetch()
    assert data["sensor.power"]["value"] == 350.0
    assert data["sensor.power"]["history"] == [100.0, 200.0, 300.0, 350.0]
    assert data["sensor.missing"]["missing"] is True
    assert any(p.startswith("/api/history/period/") for p in seen)
    # the app renders the fetched state
    slot = engine._slot("hassentity", PlaylistItem(app="hassentity", settings={"entity": "sensor.power"}))
    prov.value = data
    f = Frame()
    slot.app.render(f, 0.0)
    assert f.px.any()


async def test_ha_errors_never_leak_the_token(engine) -> None:  # type: ignore[no-untyped-def]
    engine.hub.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    engine.set_integration("homeassistant", {"url": "http://ha.test:8123", "token": "SECRET-123456"})
    prov = engine.hub.get("homeassistant")
    prov.want("sensor.x")
    with pytest.raises(RuntimeError) as e:
        await prov.fetch()
    assert "SECRET" not in str(e.value) and "401" in str(e.value)
    assert (await prov.check())["ok"] is False


@pytest.mark.parametrize("glyph", ["mic", "cam", "both"])
def test_onair_clip_is_small(engine, glyph: str) -> None:  # type: ignore[no-untyped-def]
    app = engine._slot("onair", PlaylistItem(app="onair", settings={"glyph": glyph})).app
    assert app.kind() == "clip"
    clip = app.clip_frames()
    assert len(encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)) < 10_000

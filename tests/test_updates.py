"""In-app updates (src/deskdot/updates.py): versions, assets per platform, checksums, install kinds, the flow.

The network is always mocked (httpx.MockTransport); nothing here talks to GitHub.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from deskdot import updates as U
from deskdot.config import Config, Store
from deskdot.server import create_app

DL = U.ASSET_PREFIX + "v3.9.0/"
PAYLOADS = {
    "DeskDot-Setup-3.9.0-x64.exe": b"windows installer bytes",
    "DeskDot-3.9.0-macOS-arm64.dmg": b"mac arm dmg",
    "DeskDot-3.9.0-macOS-x64.dmg": b"mac intel dmg",
    "DeskDot-3.9.0.apk": b"android apk",
}


def _asset(name: str, url: str | None = None) -> dict[str, Any]:
    return {"name": name, "size": len(PAYLOADS.get(name, b"")), "browser_download_url": url or DL + name}


def _release(checksums: str | None = None, extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    assets = [_asset(n) for n in PAYLOADS]
    if checksums is not None:
        assets.append(_asset("checksums.txt"))
    return {
        "tag_name": "v3.9.0",
        "name": "DeskDot 3.9.0",
        "body": "### New\n\n- **A thing**\n  - Before: x\n  - Now: y",
        "html_url": "https://github.com/shivpatel2468/idotmatrix/releases/tag/v3.9.0",
        "published_at": "2026-11-01T00:00:00Z",
        "assets": assets + (extra or []),
    }


def _sums(override: dict[str, str] | None = None) -> str:
    lines = []
    for n, data in PAYLOADS.items():
        sha = (override or {}).get(n) or hashlib.sha256(data).hexdigest()
        lines.append(f"{sha}  {n}")
    return "\n".join(lines) + "\n"


def _transport(
    release: dict[str, Any] | None, checksums: str = "", calls: list[str] | None = None
) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if calls is not None:
            calls.append(url)
        if url == U.LATEST_URL:
            return httpx.Response(404) if release is None else httpx.Response(200, json=release)
        name = url.rsplit("/", 1)[-1]
        if name == "checksums.txt":
            return httpx.Response(200, text=checksums)
        if name in PAYLOADS:
            return httpx.Response(200, content=PAYLOADS[name])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _updater(tmp_path: Path, kind: Any, transport: httpx.MockTransport, handoff: Any = None) -> U.Updater:
    exits: list[int] = []
    up = U.Updater(
        Store(tmp_path / "state.json"),
        tmp_path,
        kind=kind,
        current="3.8.0",
        transport=transport,
        request_exit=lambda: exits.append(1),
        handoff=handoff or (lambda _k, _p: "started"),
    )
    up.exits = exits  # type: ignore[attr-defined]
    return up


# ------------------------------------------------------------------ versions
def test_version_comparison() -> None:
    assert U.is_newer("3.8.1", "3.8.0")
    assert U.is_newer("v3.10.0", "3.9.9")  # numeric, not text
    assert U.is_newer("4.0", "3.99.99")
    assert not U.is_newer("3.8.0", "3.8.0")
    assert not U.is_newer("3.7.9", "3.8.0")
    assert U.is_newer("3.8.0", "3.8.0-beta.2")  # a release beats its pre-release
    assert U.is_newer("3.8.0-beta.10", "3.8.0-beta.2")
    assert not U.is_newer("3.8.0-beta", "3.8.0")
    assert not U.is_newer("nightly", "3.8.0")  # not a version: never "newer"
    with pytest.raises(ValueError):
        U.parse_version("3.x")


# ------------------------------------------------------------------ assets
def test_asset_selection_per_platform() -> None:
    assets = [_asset(n) for n in PAYLOADS] + [_asset("checksums.txt")]
    assert U.pick_asset(assets, "windows")["name"] == "DeskDot-Setup-3.9.0-x64.exe"  # type: ignore[index]
    assert U.pick_asset(assets, "macos", "arm64")["name"] == "DeskDot-3.9.0-macOS-arm64.dmg"  # type: ignore[index]
    assert U.pick_asset(assets, "macos", "x86_64")["name"] == "DeskDot-3.9.0-macOS-x64.dmg"  # type: ignore[index]
    assert U.pick_asset(assets, "android")["name"] == "DeskDot-3.9.0.apk"  # type: ignore[index]
    assert U.pick_asset(assets, "source") is None
    assert U.pick_asset(assets, "web") is None
    # a single universal dmg is used when there's no per-architecture one
    uni = [_asset("DeskDot-3.9.0-macOS.dmg")]
    assert U.pick_asset(uni, "macos", "arm64")["name"] == "DeskDot-3.9.0-macOS.dmg"  # type: ignore[index]


def test_assets_outside_the_repo_are_ignored() -> None:
    evil = [
        _asset("DeskDot-Setup-3.9.0-x64.exe", "https://evil.example/DeskDot-Setup-3.9.0-x64.exe"),
        _asset(
            "DeskDot-3.9.0.apk", "http://github.com/shivpatel2468/idotmatrix/releases/download/v3.9.0/x.apk"
        ),
        _asset(
            "DeskDot-3.9.0.apk", "https://github.com/someone/else/releases/download/v3.9.0/DeskDot-3.9.0.apk"
        ),
    ]
    assert U.pick_asset(evil, "windows") is None
    assert U.pick_asset(evil, "android") is None
    assert not U.trusted_url(U.ASSET_PREFIX + "../../other/x.exe")


# ------------------------------------------------------------------ checksums
def test_checksum_parsing_and_verification(tmp_path: Path) -> None:
    f = tmp_path / "DeskDot-3.9.0.apk"
    f.write_bytes(b"android apk")
    good = hashlib.sha256(b"android apk").hexdigest()
    sums = U.parse_checksums(f"{good}  DeskDot-3.9.0.apk\n{'a' * 64} *dist/Other.exe\nnot a line\n")
    assert sums == {"DeskDot-3.9.0.apk": good, "Other.exe": "a" * 64}
    assert U.verify_file(f, good) and U.verify_file(f, good.upper())
    assert not U.verify_file(f, "0" * 64)


# ------------------------------------------------------------------ install kinds
def test_install_kind_detection(tmp_path: Path) -> None:
    assert U.install_kind(frozen=False, plat="win32") == "source"
    assert U.install_kind(frozen=False, plat="darwin") == "source"
    assert U.install_kind(frozen=True, plat="win32") == "windows"
    assert U.install_kind(frozen=True, plat="darwin") == "macos"
    assert U.install_kind(frozen=True, plat="linux") == "source"
    assert U.install_kind(plat="android") == "android"
    assert U.install_kind(device="android", frozen=False, plat="linux") == "android"
    assert U.install_kind(device="web", frozen=True, plat="win32") == "web"
    assert U.install_kind() == "source"  # the test run itself: a checkout via uv
    (tmp_path / ".git").mkdir()
    assert U.is_git_checkout(tmp_path)
    assert "git pull" in U._source_message(tmp_path)
    assert (
        U.mac_bundle("/Applications/DeskDot.app/Contents/MacOS/DeskDot")
        == Path("/Applications/DeskDot.app").resolve()
    )


# ------------------------------------------------------------------ the flow
async def test_check_caches_for_six_hours(tmp_path: Path) -> None:
    calls: list[str] = []
    up = _updater(tmp_path, "windows", _transport(_release("x"), _sums(), calls))
    info = await up.check()
    assert info["latest"] == "3.9.0" and info["available"] and info["can_install"]
    assert info["assets"][0]["name"] == "DeskDot-Setup-3.9.0-x64.exe"
    assert "Before: x" in info["notes"]
    await up.check()
    assert calls == [U.LATEST_URL]  # cached
    up.store.section("updates")["checked_at"] = time.time() - U.CHECK_EVERY_S - 1
    await up.check()
    assert len(calls) == 2
    assert up.brief()["available"] is True


async def test_no_releases_yet_and_offline(tmp_path: Path) -> None:
    up = _updater(tmp_path, "windows", _transport(None))
    info = await up.check(force=True)
    assert info["latest"] is None and not info["available"] and info["status"] == "idle"

    def boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    up2 = _updater(tmp_path / "b", "windows", httpx.MockTransport(boom))
    info = await up2.check(force=True)
    assert info["status"] == "error" and not info["available"]


@pytest.mark.parametrize(
    ("kind", "name"),
    [("windows", "DeskDot-Setup-3.9.0-x64.exe"), ("android", "DeskDot-3.9.0.apk")],
)
async def test_install_downloads_verifies_and_hands_off(tmp_path: Path, kind: str, name: str) -> None:
    seen: list[tuple[str, Path]] = []

    def handoff(k: str, p: Path) -> str:
        seen.append((k, p))
        return "restart" if k == "windows" else "started"

    up = _updater(tmp_path, kind, _transport(_release("x"), _sums()), handoff)
    out = await up.install()
    assert seen and seen[0][0] == kind and seen[0][1].name == name
    assert seen[0][1].read_bytes() == PAYLOADS[name]
    assert out["result"] == ("restart" if kind == "windows" else "started")


async def test_checksum_mismatch_is_refused(tmp_path: Path) -> None:
    handed: list[Path] = []
    bad = _sums({"DeskDot-Setup-3.9.0-x64.exe": "0" * 64})
    up = _updater(
        tmp_path, "windows", _transport(_release("x"), bad), lambda _k, p: handed.append(p) or "restart"
    )
    with pytest.raises(U.UpdateError, match="checksum"):
        await up.install()
    assert not handed
    assert not (tmp_path / "updates" / "DeskDot-Setup-3.9.0-x64.exe").exists()  # deleted
    assert up.status == "error"


async def test_missing_checksums_is_refused(tmp_path: Path) -> None:
    up = _updater(tmp_path, "android", _transport(_release(None)))
    with pytest.raises(U.UpdateError, match="no checksum"):
        await up.install()


async def test_sidecar_sha256_is_accepted(tmp_path: Path) -> None:
    sha = hashlib.sha256(PAYLOADS["DeskDot-3.9.0.apk"]).hexdigest()
    rel = _release(None, extra=[_asset("DeskDot-3.9.0.apk.sha256")])

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == U.LATEST_URL:
            return httpx.Response(200, json=rel)
        if url.endswith(".sha256"):
            return httpx.Response(200, text=f"{sha}  DeskDot-3.9.0.apk\n")
        return httpx.Response(200, content=PAYLOADS[url.rsplit("/", 1)[-1]])

    up = _updater(tmp_path, "android", httpx.MockTransport(handler))
    assert (await up.install())["result"] == "started"


async def test_source_and_up_to_date_installs_are_refused(tmp_path: Path) -> None:
    up = _updater(tmp_path, "source", _transport(_release("x"), _sums()))
    with pytest.raises(U.UpdateError, match="from source"):
        await up.install()
    current = _release("x")
    current["tag_name"] = "v3.8.0"
    up2 = _updater(tmp_path / "b", "windows", _transport(current, _sums()))
    with pytest.raises(U.UpdateError, match="already the latest"):
        await up2.install()


async def test_redirect_to_plain_http_is_refused(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == U.LATEST_URL:
            return httpx.Response(200, json=_release("x"))
        if url.startswith("https://github.com/"):
            return httpx.Response(302, headers={"location": "http://cdn.example/file"})
        return httpx.Response(200, content=b"x")

    up = _updater(tmp_path, "windows", httpx.MockTransport(handler))
    with pytest.raises(U.UpdateError, match="HTTPS"):
        await up.install()


def test_mac_swap_script_quotes_paths() -> None:
    s = U.mac_swap_script(Path("/tmp/a b/DeskDot.dmg"), Path("/Applications/DeskDot.app"), 42)
    assert "kill -0 42" in s and "'/tmp/a b/DeskDot.dmg'" in s and "open /Applications/DeskDot.app" in s


# ------------------------------------------------------------------ HTTP API
def test_updates_api(tmp_path: Path) -> None:
    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    with TestClient(app) as c:
        info = c.get("/api/updates").json()
        assert info["current"] and info["kind"] == "source" and info["auto_check"] is True
        assert "source" in info["source_hint"]
        assert c.put("/api/updates", json={"auto_check": False}).json()["auto_check"] is False
        r = c.post("/api/updates/install")
        assert r.status_code == 409 and "from source" in r.json()["detail"]
        assert "updates" in c.get("/api/state").json()
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["updates"]["auto_check"] is False

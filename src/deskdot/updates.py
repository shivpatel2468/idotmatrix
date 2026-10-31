"""Updates from inside the app: check GitHub Releases, download the right installer, verify it, hand off.

`GET https://api.github.com/repos/<REPO>/releases/latest` is the only thing we ask, at most every 6 h (and only
while "Check for updates automatically" is on, or when someone presses Check now). Nothing is sent but the request
itself. Installing (docs/API.md § Updates, docs/DEPLOY.md § Releases):

* **Windows** (the installed app): downloads `DeskDot-Setup-<v>-x64.exe`, runs it with `/SILENT`, and the engine
  exits so its files can be replaced; the installer starts DeskDot again.
* **macOS** (the installed app): downloads `DeskDot-<v>-macOS-<arch>.dmg`, swaps the .app in place (or in
  /Applications) after the engine exits and opens the new one; if it can't write there, it opens the dmg instead.
* **Android**: downloads `DeskDot-<v>.apk`; the app's `Updater.kt` opens the system installer (same signing key).
* **From source** (`uv run`, a git checkout, the Pi service): nothing to install — `git pull` and rebuild.
* **Browser** (the web app at idotmatrix.com/app/): nothing to install either — a new build is just the website.
  The check reads the site's own `/app/version.json` (written by scripts/build_webapp.py: version, build id,
  release notes) instead of GitHub, every 30 min, and offers a reload when its build differs from the tab's.

Every download must be an HTTPS asset of this repository's release, and its SHA-256 must match the release's
`checksums.txt` (or a `<asset>.sha256` file next to it); anything else is refused and deleted.
Network calls are async (httpx); hashing and hand-off subprocesses go through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx

from . import __version__

log = logging.getLogger("deskdot.updates")

REPO = "shivpatel2468/idotmatrix"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
#: release assets are served from here (GitHub then redirects to its CDN, also HTTPS)
ASSET_PREFIX = f"https://github.com/{REPO}/releases/download/"
CHECK_EVERY_S = 6 * 3600
#: the browser app asks its own site (a small static file), so it may look more often
WEB_CHECK_EVERY_S = 30 * 60
WEB_FIRST_DELAY_S = 60.0
AUTO_FIRST_DELAY_S = 30.0
AUTO_TICK_S = 3600.0
#: the biggest installer we accept (the Windows one is ~150 MB)
MAX_ASSET_BYTES = 600 * 1024 * 1024

Kind = Literal["windows", "macos", "android", "source", "web"]
Status = Literal["idle", "checking", "downloading", "verifying", "installing", "error"]


class UpdateError(Exception):
    """A refusal or failure with a message for people (shown as-is in the studio)."""


# ---------------------------------------------------------------- versions
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(text: str) -> tuple[int, int, int, tuple[tuple[int, int | str], ...] | None]:
    """'v3.8.0' / '3.8.0-beta.2' → comparable parts. Raises ValueError for anything else."""
    m = _SEMVER.match((text or "").strip())
    if not m:
        raise ValueError(f"not a version: {text!r}")
    pre = None
    if m.group(4):
        pre = tuple((0, int(p)) if p.isdigit() else (1, p) for p in m.group(4).split("."))
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), pre


def _key(text: str) -> tuple[Any, ...]:
    major, minor, patch, pre = parse_version(text)
    # semver: a pre-release sorts before its release; identifiers compare numerically, then by text
    return (major, minor, patch, 1 if pre is None else 0, pre or ())


def is_newer(candidate: str, current: str) -> bool:
    """True when `candidate` is a later version than `current` (False if either isn't a version)."""
    try:
        return _key(candidate) > _key(current)
    except ValueError:
        return False


# ---------------------------------------------------------------- where we run
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def install_kind(*, device: str | None = None, frozen: bool | None = None, plat: str | None = None) -> Kind:
    """How this copy of DeskDot was installed, which decides how it updates."""
    plat = plat or sys.platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if device == "web":
        return "web"  # the browser app updates with the page
    if device == "android" or plat == "android":
        return "android"
    if frozen and plat == "win32":
        return "windows"
    if frozen and plat == "darwin":
        return "macos"
    return "source"


def is_git_checkout(root: Path | None = None) -> bool:
    return ((root or repo_root()) / ".git").exists()


def mac_arch(machine: str | None = None) -> str:
    m = (machine or platform.machine()).lower()
    return "arm64" if m in ("arm64", "aarch64") else "x64"


# ---------------------------------------------------------------- release assets
_ASSET_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "windows": [re.compile(r"^DeskDot-Setup-\d[\w.+-]*-x64\.exe$")],
    "macos-arm64": [
        re.compile(r"^DeskDot-\d[\w.+-]*-macOS-arm64\.dmg$"),
        re.compile(r"^DeskDot-\d[\w.+-]*-macOS\.dmg$"),
    ],
    "macos-x64": [
        re.compile(r"^DeskDot-\d[\w.+-]*-macOS-x64\.dmg$"),
        re.compile(r"^DeskDot-\d[\w.+-]*-macOS\.dmg$"),
    ],
    "android": [re.compile(r"^DeskDot-\d[\w.+-]*\.apk$")],
}


def trusted_url(url: str) -> bool:
    """Only HTTPS downloads of this repository's release assets."""
    return isinstance(url, str) and url.startswith(ASSET_PREFIX) and ".." not in url


def pick_asset(assets: list[dict[str, Any]], kind: str, machine: str | None = None) -> dict[str, Any] | None:
    """The installer for this platform from a release's `assets`, or None."""
    key = f"macos-{mac_arch(machine)}" if kind == "macos" else kind
    for pat in _ASSET_PATTERNS.get(key, []):
        for a in assets:
            if pat.match(str(a.get("name", ""))) and trusted_url(str(a.get("browser_download_url", ""))):
                return a
    return None


def parse_checksums(text: str) -> dict[str, str]:
    """`sha256sum` output ('<hex>  name' or '<hex> *name') → {name: hex}."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line.strip())
        if m:
            out[Path(m.group(2)).name] = m.group(1).lower()
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, expected: str) -> bool:
    return sha256_file(path) == expected.strip().lower()


def _https_only(request: httpx.Request) -> None:
    if request.url.scheme != "https":
        raise UpdateError("Refused a download that wasn't over HTTPS.")


def _source_message(root: Path | None = None) -> str:
    if is_git_checkout(root):
        return (
            "You're running DeskDot from source. To update: `git pull`, then `uv sync` and "
            "`cd web && npm run build`, and restart the engine."
        )
    return (
        "You're running DeskDot from source. Download the new version from GitHub, then restart the engine."
    )


# ---------------------------------------------------------------- the updater
class Updater:
    """One per engine. State lives in the store's `updates` section (auto-check switch + the last answer)."""

    def __init__(
        self,
        store: Any,
        data_dir: Path,
        *,
        kind: Kind | None = None,
        device: str | None = None,
        current: str = __version__,
        on_change: Callable[[], None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        request_exit: Callable[[], None] | None = None,
        handoff: Callable[[Kind, Path], str] | None = None,
        web_version_url: str | None = None,
        build: str | None = None,
    ) -> None:
        self.store = store
        self.dir = Path(data_dir) / "updates"
        self.kind: Kind = kind or install_kind(device=device)
        self.current = current
        self.on_change = on_change or (lambda: None)
        self._transport = transport
        self._request_exit = request_exit or _exit_engine
        self._handoff = handoff or handoff_to_installer
        #: the browser app: where the site publishes its current build, and the build this tab runs
        self.web_version_url = web_version_url
        self.build = build or None
        self.status: Status = "idle"
        self.progress: float | None = None
        self.error: str | None = None
        self.message: str | None = None
        self._lock = asyncio.Lock()
        self._last_emit = 0.0

    # -------------------------------------------------------------- persisted bits
    @property
    def _sec(self) -> dict[str, Any]:
        sec = self.store.section("updates")
        assert isinstance(sec, dict)
        return sec

    @property
    def auto_check(self) -> bool:
        return bool(self._sec.get("auto_check", True))

    def set_auto_check(self, on: bool) -> None:
        self._sec["auto_check"] = bool(on)
        self.store.save_soon()
        self.on_change()

    @property
    def release(self) -> dict[str, Any] | None:
        r = self._sec.get("release")
        return r if isinstance(r, dict) else None

    @property
    def checked_at(self) -> float | None:
        t = self._sec.get("checked_at")
        return float(t) if isinstance(t, int | float) else None

    @property
    def latest(self) -> str | None:
        r = self.release
        return str(r.get("version")) if r and r.get("version") else None

    @property
    def latest_build(self) -> str | None:
        r = self.release
        return str(r.get("build")) if r and r.get("build") else None

    @property
    def available(self) -> bool:
        if self.kind == "web":  # a different build of the site (a new version, or fixes to this one)
            lb = self.latest_build
            return bool(
                lb
                and self.build
                and lb != self.build
                and not is_newer(self.current, self.latest or self.current)
            )
        return bool(self.latest and is_newer(self.latest, self.current))

    def asset(self) -> dict[str, Any] | None:
        r = self.release
        return pick_asset(r.get("assets", []), self.kind) if r else None

    # -------------------------------------------------------------- views
    def info(self) -> dict[str, Any]:
        r = self.release or {}
        a = self.asset()
        return {
            "current": self.current,
            "latest": self.latest,
            "available": self.available,
            "notes": r.get("notes") or "",
            "name": r.get("name"),
            "published_at": r.get("published_at"),
            "url": r.get("html_url") or RELEASES_PAGE,
            "assets": (
                [{"name": a["name"], "size": a.get("size"), "url": a["browser_download_url"]}] if a else []
            ),
            "checked_at": self.checked_at,
            "auto_check": self.auto_check,
            "kind": self.kind,
            "can_install": self.kind in ("windows", "macos", "android") and a is not None,
            "build": self.build,
            "latest_build": self.latest_build,
            "source_hint": _source_message() if self.kind == "source" else None,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "message": self.message,
        }

    def brief(self) -> dict[str, Any]:
        """The small part that rides on the state websocket (top-bar pill, install progress)."""
        return {
            "current": self.current,
            "latest": self.latest,
            "available": self.available,
            "kind": self.kind,
            "latest_build": self.latest_build,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
        }

    def _set(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.on_change()

    def _client(self, timeout: float = 20.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": f"DeskDot/{self.current}", "Accept": "application/vnd.github+json"},
            event_hooks={"request": [_async(_https_only)]},
        )

    # -------------------------------------------------------------- check
    def stale(self, now: float | None = None) -> bool:
        t = self.checked_at
        every = WEB_CHECK_EVERY_S if self.kind == "web" else CHECK_EVERY_S
        return t is None or (now or time.time()) - t >= every

    async def check(self, force: bool = False) -> dict[str, Any]:
        if not force and not self.stale():
            return self.info()
        if self.status in ("downloading", "verifying", "installing"):
            return self.info()
        if self.kind == "web":
            return await self._check_web()
        self._set(status="checking", error=None)
        try:
            async with self._client() as http:
                r = await http.get(LATEST_URL)
            if r.status_code == 404:
                release = None  # no releases published yet
            else:
                r.raise_for_status()
                release = _release_summary(r.json())
            self._sec["release"] = release
            self._sec["checked_at"] = time.time()
            self.store.save_soon()
            self._set(status="idle", error=None)
            if self.available:
                log.info("DeskDot %s is available (this is %s)", self.latest, self.current)
        except (httpx.HTTPError, ValueError, UpdateError) as e:
            log.info("update check failed: %s", e)
            self._set(status="error", error="Couldn't reach GitHub to check for updates.")
        return self.info()

    async def _check_web(self) -> dict[str, Any]:
        """The browser app: read the site's /app/version.json (same origin, never cached)."""
        if not self.web_version_url:
            return self.info()
        self._set(status="checking", error=None)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=15.0) as http:
                r = await http.get(self.web_version_url, headers={"Cache-Control": "no-cache"})
            r.raise_for_status()
            j = r.json()
            if not isinstance(j, dict) or not j.get("build"):
                raise ValueError("version.json has no build")
            self._sec["release"] = {
                "version": str(j.get("version") or self.current),
                "build": str(j["build"]),
                "notes": str(j.get("notes") or ""),
                "name": j.get("name"),
                "published_at": j.get("built_at"),
                "html_url": self.web_version_url.rsplit("/", 1)[0] + "/",
                "assets": [],
            }
            self._sec["checked_at"] = time.time()
            self.store.save_soon()
            self._set(status="idle", error=None)
            if self.available:
                log.info(
                    "a new build of the browser app is out (%s, this tab runs %s)", j["build"], self.build
                )
        except (httpx.HTTPError, ValueError) as e:
            log.info("web update check failed: %s", e)
            self._set(status="error", error="Couldn't reach the website to check for a new version.")
        return self.info()

    async def auto_loop(self) -> None:
        """Background: a check shortly after start, then whenever the last answer is 6 h old (the browser app:
        every 30 min — it only reads its own site's version.json)."""
        if self.kind == "web":
            if not self.web_version_url:
                return
            await asyncio.sleep(WEB_FIRST_DELAY_S)
            while True:
                if self.auto_check and self.stale():
                    with contextlib.suppress(Exception):
                        await self.check()
                await asyncio.sleep(WEB_CHECK_EVERY_S / 2)
        if os.environ.get("DESKDOT_UPDATE_CHECK", "1").strip().lower() in ("0", "false", "no", "off"):
            return
        await asyncio.sleep(AUTO_FIRST_DELAY_S)
        while True:
            if self.auto_check and self.stale():
                with contextlib.suppress(Exception):
                    await self.check()
            await asyncio.sleep(AUTO_TICK_S)

    # -------------------------------------------------------------- install
    async def install(self) -> dict[str, Any]:
        if self.kind == "source":
            raise UpdateError(_source_message())
        if self.kind == "web":
            raise UpdateError(
                "The browser app updates with the website: reload the page to get the new version."
            )
        if self._lock.locked():
            raise UpdateError("An update is already being installed.")
        async with self._lock:
            if self.checked_at is None or time.time() - self.checked_at > 300:
                await self.check(force=True)  # make sure we install what's really the latest
                if self.status == "error":
                    raise UpdateError(self.error or "Couldn't reach GitHub to check for updates.")
            if not self.available:
                raise UpdateError(f"DeskDot {self.current} is already the latest version.")
            asset = self.asset()
            if asset is None:
                raise UpdateError("This release has no installer for your system yet.")
            try:
                path = await self._download(asset)
                self._set(status="verifying", progress=None)
                await self._verify(asset, path)
                self._set(status="installing", progress=None, message=None)
                result = await asyncio.to_thread(self._handoff, self.kind, path)
            except UpdateError as e:
                self._set(status="error", progress=None, error=str(e))
                raise
            except (httpx.HTTPError, OSError) as e:
                log.warning("update failed: %s", e)
                self._set(status="error", progress=None, error="The download failed. Try again in a moment.")
                raise UpdateError("The download failed. Try again in a moment.") from e
            if self.kind in ("windows", "macos") and result == "restart":
                self._set(message="Installing — DeskDot restarts in a moment.")
                asyncio.get_running_loop().call_later(1.5, self._request_exit)
            elif result == "opened":
                self._set(status="idle", message="The installer is open. Drag DeskDot into Applications.")
            elif result == "permission":
                self._set(
                    status="idle",
                    message="Allow DeskDot to install apps (it just opened that setting), then press Install again.",
                )
            elif result == "started":
                self._set(status="idle", message="Android's installer is open: tap Update.")
            elif result == "signature":
                self._set(
                    status="error",
                    error="This download is signed with a different key than your app. "
                    "Uninstall DeskDot once, then install it from GitHub.",
                )
            else:
                self._set(status="idle", message=None)
            return {**self.info(), "result": result}

    async def _download(self, asset: dict[str, Any]) -> Path:
        url = str(asset.get("browser_download_url", ""))
        if not trusted_url(url):
            raise UpdateError("Refused a download from outside DeskDot's GitHub releases.")
        name = Path(str(asset["name"])).name
        self.dir.mkdir(parents=True, exist_ok=True)
        part = self.dir / (name + ".part")
        final = self.dir / name
        total = int(asset.get("size") or 0)
        if total > MAX_ASSET_BYTES:
            raise UpdateError("The download is unexpectedly large; refused.")
        self._set(status="downloading", progress=0.0, error=None, message=None)
        got = 0
        async with self._client(timeout=60.0) as http, http.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or total or 0)
            with part.open("wb") as f:
                async for chunk in r.aiter_bytes(1 << 16):
                    got += len(chunk)
                    if got > MAX_ASSET_BYTES:
                        raise UpdateError("The download is unexpectedly large; refused.")
                    f.write(chunk)
                    now = time.monotonic()
                    if total and now - self._last_emit > 0.25:
                        self._last_emit = now
                        self._set(progress=min(1.0, got / total))
        part.replace(final)
        self._set(progress=1.0)
        return final

    async def _expected_sha(self, name: str) -> str | None:
        assets = (self.release or {}).get("assets", [])
        by_name = {str(a.get("name")): a for a in assets}
        async with self._client() as http:
            for candidate in ("checksums.txt", f"{name}.sha256"):
                a = by_name.get(candidate)
                if not a or not trusted_url(str(a.get("browser_download_url", ""))):
                    continue
                r = await http.get(str(a["browser_download_url"]))
                r.raise_for_status()
                text = r.text
                if candidate.endswith(".sha256"):
                    m = re.match(r"^\s*([0-9a-fA-F]{64})\b", text)
                    if m:
                        return m.group(1).lower()
                else:
                    sha = parse_checksums(text).get(name)
                    if sha:
                        return sha
        return None

    async def _verify(self, asset: dict[str, Any], path: Path) -> None:
        name = path.name
        expected = await self._expected_sha(name)
        if expected is None:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise UpdateError("The release has no checksum for this file, so it wasn't installed.")
        if not await asyncio.to_thread(verify_file, path, expected):
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise UpdateError("The download didn't match its checksum, so it wasn't installed.")


def _async(fn: Callable[[httpx.Request], None]) -> Callable[[httpx.Request], Any]:
    async def hook(request: httpx.Request) -> None:
        fn(request)

    return hook


def _release_summary(j: dict[str, Any]) -> dict[str, Any]:
    tag = str(j.get("tag_name") or "")
    parse_version(tag)  # ValueError for a tag that isn't a version
    return {
        "version": tag.lstrip("v"),
        "tag": tag,
        "name": j.get("name"),
        "notes": str(j.get("body") or "")[:20000],
        "html_url": j.get("html_url"),
        "published_at": j.get("published_at"),
        "assets": [
            {
                "name": a.get("name"),
                "size": a.get("size"),
                "browser_download_url": a.get("browser_download_url"),
            }
            for a in j.get("assets", [])
            if isinstance(a, dict)
        ],
    }


# ---------------------------------------------------------------- hand-off (blocking: runs in a thread)
def handoff_to_installer(kind: Kind, path: Path) -> str:
    """Start the platform's installer. Returns 'restart' (the engine must exit now), 'opened', 'started',
    'permission' or 'signature'."""
    if kind == "windows":
        return _handoff_windows(path)
    if kind == "macos":
        return _handoff_macos(path)
    if kind == "android":
        return _handoff_android(path)
    raise UpdateError("Nothing to install on this system.")


def _quit_launcher() -> None:
    with contextlib.suppress(Exception):
        from .launcher import send_control

        send_control("quit")


def _handoff_windows(path: Path) -> str:
    _quit_launcher()  # the tray app holds files in the install folder too
    flags = 0x00000008 | 0x00000200 | 0x01000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB
    args = [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    try:
        subprocess.Popen(args, creationflags=flags, close_fds=True)
    except OSError:
        subprocess.Popen(args, creationflags=flags & ~0x01000000, close_fds=True)
    return "restart"


def mac_bundle(executable: str | None = None) -> Path | None:
    """`/Applications/DeskDot.app` from `…/DeskDot.app/Contents/MacOS/DeskDot`."""
    p = Path(executable or sys.executable).resolve()
    for parent in p.parents:
        if parent.suffix == ".app":
            return parent
    return None


def mac_swap_script(dmg: Path, target: Path, pid: int) -> str:
    """The shell script that waits for the engine to exit, swaps the .app and opens it again."""

    def q(p: Path | str) -> str:
        return shlex.quote(p.as_posix() if isinstance(p, Path) else p)

    return f"""#!/bin/sh
for i in $(seq 1 60); do kill -0 {pid} 2>/dev/null || break; sleep 0.5; done
MNT=$(mktemp -d /tmp/deskdot-update.XXXXXX)
if hdiutil attach -nobrowse -readonly -mountpoint "$MNT" {q(dmg)} >/dev/null; then
  if [ -d "$MNT/DeskDot.app" ]; then
    rm -rf {q(target)}.old && mv {q(target)} {q(target)}.old 2>/dev/null
    if ditto "$MNT/DeskDot.app" {q(target)}; then rm -rf {q(target)}.old;
    else mv {q(target)}.old {q(target)}; fi
  fi
  hdiutil detach "$MNT" -quiet
fi
open {q(target)}
"""


def _handoff_macos(path: Path) -> str:
    bundle = mac_bundle()
    target = bundle if bundle is not None else Path("/Applications/DeskDot.app")
    if not os.access(target.parent, os.W_OK) or (target.exists() and not os.access(target, os.W_OK)):
        subprocess.run(["open", str(path)], check=False)  # Finder shows the dmg; drag to Applications
        return "opened"
    _quit_launcher()
    script = path.with_suffix(".sh")
    script.write_text(mac_swap_script(path, target, os.getpid()), encoding="utf-8")
    script.chmod(0o755)
    subprocess.Popen(
        ["/bin/sh", str(script)],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "restart"


def _handoff_android(path: Path) -> str:
    from java import jclass  # type: ignore[import-not-found]

    return str(jclass("com.deskdot.app.Updater").install(str(path)))


def _exit_engine() -> None:
    """Ask uvicorn to shut down like Ctrl+C (hand-off runs); hard exit if it hasn't after 20 s."""

    def hard() -> None:
        time.sleep(20)
        os._exit(0)

    threading.Thread(target=hard, daemon=True).start()
    try:
        signal.raise_signal(signal.SIGINT)
    except (OSError, ValueError):
        os._exit(0)

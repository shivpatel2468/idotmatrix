"""Uptime checks: HTTP(S) status + latency, and TCP connect time to host:port.

Target syntax (comma or newline separated, optional ``LABEL=`` prefix)::

    example.com                 -> HTTPS GET https://example.com/
    http://nas.local:8080/health
    tcp://db.local:5432  or  db.local:5432
    NAS=192.168.1.10:445

ICMP ping is not offered: raw ICMP sockets need administrator rights on Windows (and root/capabilities on
Linux), and the engine must not run elevated. ``ping://host`` targets are reported as unsupported; use a TCP
port the host listens on instead (22, 80, 443, 445…).

A target is declared DOWN after ``confirm`` consecutive failures and UP again on the first success; each
transition is recorded as a ``down``/``up`` event (armed after the first check, so start-up never alerts).
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import urlsplit

from ..platforms import current
from .base import Provider
from .radiator import EventLog, safe_error

HISTORY = 30  # latency samples kept per target (sparkline columns)
MAX_TARGETS = 12


def parse_targets(text: str) -> list[dict[str, Any]]:
    """Settings text -> [{"key", "label", "kind": http|tcp|ping, "url"|"host"/"port"}] (unique, capped)."""
    out: list[dict[str, Any]] = []
    for raw in re.split(r"[,\n;]+", text or ""):
        item = raw.strip()
        if not item:
            continue
        label = ""
        if "=" in item and not re.match(r"^[a-z]+://", item, flags=re.I):
            label, item = (x.strip() for x in item.split("=", 1))
        t = _target(item)
        if t is None:
            continue
        t["label"] = (label or t["label"]).upper()[:16]
        if t["key"] not in (o["key"] for o in out):
            out.append(t)
    return out[:MAX_TARGETS]


def short_error(e: BaseException) -> str:
    """Exception -> a word that fits the panel: REFUSED, DNS FAIL, TIMEOUT, TLS ERROR, …"""
    text = f"{type(e).__name__} {e}".lower()
    for needle, word in (
        ("refused", "REFUSED"),
        ("getaddrinfo", "DNS FAIL"),
        ("name or service", "DNS FAIL"),
        ("nodename", "DNS FAIL"),
        ("timeout", "TIMEOUT"),
        ("timed out", "TIMEOUT"),
        ("ssl", "TLS ERROR"),
        ("certificate", "TLS ERROR"),
        ("unreachable", "UNREACHABLE"),
        ("reset", "RESET"),
    ):
        if needle in text:
            return word
    return safe_error(e, limit=40)


def _host_label(host: str) -> str:
    """'www.example.com' -> 'example', 'api.github.com' -> 'github', '192.168.1.10' -> '192.168.1.10'."""
    host = host.lower().strip("[]")
    if re.fullmatch(r"[\d.]+", host) or ":" in host:
        return host
    parts = host.split(".")
    while len(parts) > 2 and parts[0] in ("www", "api", "app", "status", "m"):
        parts = parts[1:]
    return parts[0]


def _target(item: str) -> dict[str, Any] | None:
    low = item.lower()
    if low.startswith(("ping://", "icmp://")):
        host = item.split("://", 1)[1].strip("/")
        return (
            {"key": f"ping:{host}", "kind": "ping", "host": host, "label": _host_label(host)}
            if host
            else None
        )
    if low.startswith("tcp://") or re.fullmatch(r"[A-Za-z0-9.\-]+:\d{1,5}", item):
        hp = item.split("://", 1)[-1].strip("/")
        host, _, port = hp.rpartition(":")
        if not host or not port.isdigit() or not 0 < int(port) < 65536:
            return None
        return {
            "key": f"tcp:{host}:{port}",
            "kind": "tcp",
            "host": host,
            "port": int(port),
            "label": _host_label(host),
        }
    url = item if re.match(r"^https?://", item, flags=re.I) else f"https://{item}"
    parts = urlsplit(url)
    if not parts.hostname or " " in url:
        return None
    return {"key": f"http:{url}", "kind": "http", "url": url, "label": _host_label(parts.hostname)}


def web_unsupported(t: dict[str, Any]) -> str | None:
    """In the browser app: targets a tab can't check (no raw sockets; an https page may not call plain-http LAN
    devices). They show the reason and stay neither up nor down, so they never alert."""
    if current() != "web":
        return None
    if t["kind"] == "tcp":
        return "NO TCP IN BROWSER"
    if t["kind"] == "http" and t["url"].lower().startswith("http://"):
        from ..web_main import is_local_host

        if is_local_host(urlsplit(t["url"]).hostname or ""):
            return "LAN HTTP: NOT IN BROWSER"
    return None


class UptimeProvider(EventLog, Provider[dict[str, Any]]):
    """``value = {"targets": {key: state}, "checked": ts}``; apps call ``configure(targets, …)``.

    state: ``{"key", "label", "kind", "up": bool|None, "status": int|None, "latency": ms|None,
    "history": [ms|None …], "since": ts, "fails": n, "checks": n, "ok": n, "error": str|None}``.
    """

    name = "uptime"
    interval = 30.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._init_events()
        self.targets: list[dict[str, Any]] = []
        self.every = 30.0
        self.timeout = 5.0
        self.confirm = 2
        self.expect = "ok"
        self._state: dict[str, dict[str, Any]] = {}

    def configure(
        self,
        targets: list[dict[str, Any]],
        every: float = 30.0,
        timeout: float = 5.0,
        confirm: int = 2,
        expect: str = "ok",
    ) -> None:
        keys_changed = [t["key"] for t in targets] != [t["key"] for t in self.targets]
        self.targets = targets[:MAX_TARGETS]
        for t in self.targets:  # labels may change without a new key
            if t["key"] in self._state:
                self._state[t["key"]]["label"] = t["label"]
        self.every, self.timeout = max(10.0, float(every)), max(1.0, float(timeout))
        self.confirm, self.expect = max(1, int(confirm)), expect
        if keys_changed:
            self.refresh()

    def next_interval(self) -> float:
        return self.every

    # ------------------------------------------------------------ checks
    async def check_http(self, url: str) -> tuple[bool, int | None, float | None, str | None]:
        if current() == "web":
            return await self.check_http_web(url)
        t0 = time.perf_counter()
        try:
            async with self.hub.http.stream(
                "GET", url, timeout=self.timeout, headers={"Accept": "*/*", "Cache-Control": "no-cache"}
            ) as r:
                ms = (time.perf_counter() - t0) * 1000
                code = r.status_code
        except Exception as e:
            return False, None, None, short_error(e)
        ok = code < 400 if self.expect == "ok" else code < 500 if self.expect == "any" else 200 <= code < 300
        return ok, code, ms, None if ok else f"HTTP {code}"

    async def check_http_web(self, url: str) -> tuple[bool, int | None, float | None, str | None]:
        """In the browser app: a normal request where the site allows web pages (real status code), else an
        opaque "no-cors" request that only tells whether the server answered (status unknown, still UP)."""
        import httpx

        from ..web_main import probe

        t0 = time.perf_counter()
        try:
            r = await self.hub.http.get(url, timeout=self.timeout, headers={"Accept": "*/*"})
        except httpx.TimeoutException:
            return False, None, None, "TIMEOUT"
        except Exception:
            try:
                ms = await probe(url, self.timeout)
            except Exception as e:
                return False, None, None, short_error(e)
            return True, None, ms, None
        ms = (time.perf_counter() - t0) * 1000
        code = r.status_code
        ok = code < 400 if self.expect == "ok" else code < 500 if self.expect == "any" else 200 <= code < 300
        return ok, code, ms, None if ok else f"HTTP {code}"

    async def check_tcp(self, host: str, port: int) -> tuple[bool, int | None, float | None, str | None]:
        t0 = time.perf_counter()
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), self.timeout)
        except TimeoutError:
            return False, None, None, "TIMEOUT"
        except Exception as e:
            return False, None, None, short_error(e)
        ms = (time.perf_counter() - t0) * 1000
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1.0)
        except Exception:
            pass
        return True, None, ms, None

    async def _check(self, t: dict[str, Any]) -> tuple[bool, int | None, float | None, str | None]:
        why = web_unsupported(t)
        if why:
            return False, None, None, why
        if t["kind"] == "http":
            return await self.check_http(t["url"])
        if t["kind"] == "tcp":
            return await self.check_tcp(t["host"], t["port"])
        return False, None, None, "ICMP NEEDS ADMIN"

    def _apply(
        self, t: dict[str, Any], result: tuple[bool, int | None, float | None, str | None], now: float
    ) -> dict[str, Any]:
        ok, code, ms, err = result
        st = self._state.get(t["key"]) or {
            "key": t["key"],
            "kind": t["kind"],
            "up": None,
            "history": [],
            "since": now,
            "fails": 0,
            "checks": 0,
            "ok": 0,
        }
        st["label"] = t["label"]
        st["status"], st["latency"], st["error"] = code, (round(ms, 1) if ms is not None else None), err
        st["checks"] += 1
        st["history"] = (st["history"] + [st["latency"] if ok else None])[-HISTORY:]
        if t["kind"] == "ping" or web_unsupported(t):
            st["up"] = None  # unsupported here: neither up nor down, never alerts
            self._state[t["key"]] = st
            return st
        prev = st["up"]
        if ok:
            st["ok"] += 1
            st["fails"] = 0
            new = True
        else:
            st["fails"] += 1
            new = False if (st["fails"] >= self.confirm or prev is None) else prev
        if new != prev:
            st["since"] = now
            if prev is not None:  # the first result arms, it never alerts
                self._emit("down" if not new else "up", key=t["key"], label=t["label"], error=err)
        st["up"] = new
        self._state[t["key"]] = st
        return st

    async def fetch(self) -> dict[str, Any]:
        targets = list(self.targets)
        now = time.time()
        results = await asyncio.gather(*(self._check(t) for t in targets))
        out = {t["key"]: self._apply(t, r, now) for t, r in zip(targets, results, strict=True)}
        for k in list(self._state):  # forget removed targets
            if k not in out:
                del self._state[k]
        return {"targets": {k: dict(v, history=list(v["history"])) for k, v in out.items()}, "checked": now}

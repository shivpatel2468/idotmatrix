"""ntfy.sh subscription: keyless pushes from a phone (or any script) to the panel.

Subscribes to one or more topics with ntfy's JSON stream (`GET {server}/{topic1,topic2}/json`): one JSON object
per line — `open`, `keepalive` (every ~45 s) and `message` events. Each message is emitted as a hub event
"ntfy" {title, message, priority 1-5, tags, topic, id}; the engine turns it into a panel notification, or, when
it carries a routing tag (default prefix `app-`, e.g. tag `app-garage`), into the custom app `garage`.

Settings live in the store under "ntfy" (see `DEFAULTS`). A reconnect resumes with `since=<last id>`, so no
message is lost across a dropped connection; the first connect only receives new messages.

In the browser app (platform "web") a tab can't hold the endless stream (fetch() hands over the body only when
it ends), so the provider polls instead: `?poll=1&since=<last id | start time>` every `WEB_POLL` seconds, and a
token travels as ntfy's `auth` query parameter (an `Authorization` header needs a CORS preflight ntfy refuses).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any

import httpx

from ..platforms import current
from .base import Provider

log = logging.getLogger("deskdot.ntfy")

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "server": "https://ntfy.sh",
    "topics": "",  # comma-separated
    "token": "",  # optional access token for protected topics / self-hosted servers
    "style": "auto",  # auto (by priority) | banner | full
    "duration": 8,
    "route_prefix": "app-",  # tag "app-<name>" routes the message into custom app <name>
    "lifetime": 3600,  # seconds a routed custom app stays in the rotation
}

_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
WEB_POLL = 10.0  # seconds between polls in the browser app (ntfy.sh allows a request every 5 s on average)


def auth_param(token: str) -> str:
    """ntfy's `?auth=` value: the Authorization header, base64url without padding (docs: "query param")."""
    return base64.urlsafe_b64encode(f"Bearer {token}".encode()).decode().rstrip("=")


def topics_of(raw: str) -> list[str]:
    return [t for t in (x.strip() for x in raw.split(",")) if _TOPIC.match(t)]


def stream_url(server: str, topics: list[str]) -> str:
    return f"{server.rstrip('/')}/{','.join(topics)}/json"


def parse_line(line: str) -> dict[str, Any] | None:
    """One line of the JSON stream -> a normalised message, or None for open/keepalive/garbage."""
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(ev, dict) or ev.get("event") != "message":
        return None
    try:
        prio = int(ev.get("priority") or 3)
    except (TypeError, ValueError):
        prio = 3
    tags = ev.get("tags") or []
    return {
        "id": str(ev.get("id") or ""),
        "topic": str(ev.get("topic") or ""),
        "title": str(ev.get("title") or ""),
        "message": str(ev.get("message") or ""),
        "priority": max(1, min(5, prio)),
        "tags": [str(t) for t in tags] if isinstance(tags, list) else [],
        "time": ev.get("time"),
    }


class NtfyProvider(Provider[dict[str, Any]]):
    name = "ntfy"
    interval = 1.0  # reconnect quickly after a stream ends normally
    retry = 20.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._since: str | None = None
        self._web_start: str | None = None  # browser app: poll for messages newer than this (unix time)
        self.recent: list[dict[str, Any]] = []

    def config(self) -> dict[str, Any]:
        d = dict(DEFAULTS)
        d.update(self.hub.store.get("ntfy") or {})
        return d

    def restart(self) -> None:
        """Settings changed: drop the current stream and reconnect with the new topics."""
        self._since = None
        self._web_start = None
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        if self._refs:
            self._refs -= 1
            self.acquire()  # re-creates the loop task

    def next_interval(self) -> float:
        cfg = self.config()
        if not (cfg["enabled"] and topics_of(cfg["topics"])):
            return 30.0
        return WEB_POLL if current() == "web" else 1.0

    def snapshot(self) -> dict[str, Any]:
        v = self.value or {}
        return {**super().snapshot(), "connected": bool(v.get("connected"))}

    def handle(self, msg: dict[str, Any]) -> None:
        if msg.get("id"):
            self._since = msg["id"]
        self.recent = ([msg, *self.recent])[:10]
        self.hub.emit("ntfy", msg)

    async def fetch(self) -> dict[str, Any]:
        cfg = self.config()
        topics = topics_of(cfg["topics"])
        if not cfg["enabled"] or not topics:
            return {"connected": False, "topics": topics, "recent": self.recent}
        headers = {"Authorization": f"Bearer {cfg['token']}"} if cfg["token"] else {}
        params = {"since": self._since} if self._since else {}
        url = stream_url(cfg["server"], topics)
        if current() == "web":
            return await self._poll(url, topics, cfg["token"])
        timeout = httpx.Timeout(10.0, read=100.0)  # keepalives arrive every ~45 s
        async with self.hub.http.stream("GET", url, params=params, headers=headers, timeout=timeout) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"ntfy {r.status_code} for {','.join(topics)}")
            self.value = {"connected": True, "topics": topics, "recent": self.recent}
            self.error = None
            self.hub.on_change(self.name)
            async for line in r.aiter_lines():
                msg = parse_line(line)
                if msg is not None:
                    self.handle(msg)
                await asyncio.sleep(0)
        return {"connected": False, "topics": topics, "recent": self.recent}

    async def _poll(self, url: str, topics: list[str], token: str) -> dict[str, Any]:
        """Browser app: one `poll=1` request (returns the cached messages since the cursor and closes)."""
        if self._web_start is None:
            self._web_start = str(int(time.time()))  # like the stream: only messages from now on
        params = {"poll": "1", "since": self._since or self._web_start}
        if token:
            params["auth"] = auth_param(token)
        r = await self.hub.http.get(url, params=params, timeout=15.0)
        if r.status_code >= 400:
            raise RuntimeError(f"ntfy {r.status_code} for {','.join(topics)}")
        for line in r.text.splitlines():
            msg = parse_line(line)
            if msg is not None:
                self.handle(msg)
        return {"connected": True, "topics": topics, "recent": self.recent}

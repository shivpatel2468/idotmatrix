"""Mirror the computer's own notifications (Windows toasts, macOS Notification Center) onto the panel.

Both OSes keep delivered notifications in a local SQLite database that the signed-in user can read:

* Windows: %LOCALAPPDATA%/Microsoft/Windows/Notifications/wpndatabase.db (toast XML payloads)
* macOS:   ~/Library/Group Containers/group.com.apple.usernoted/db2/db (binary plists).
           Requires Full Disk Access for the terminal / Python running DotDeck.

The provider polls for rows newer than the last one seen (never replays history) and emits a hub
event "os_notification" {app, title, body}; the engine turns it into an overlay per the user's settings.
"""

from __future__ import annotations

import asyncio
import logging
import os
import plistlib
import re
import sqlite3
import sys
from html import unescape
from pathlib import Path
from typing import Any

from .base import Provider

log = logging.getLogger("dotdeck.notifications")

FRIENDLY = {
    "msteams": "Teams",
    "teams": "Teams",
    "whatsapp": "WhatsApp",
    "outlook": "Outlook",
    "olk": "Outlook",
    "discord": "Discord",
    "slack": "Slack",
    "chrome": "Chrome",
    "msedge": "Edge",
    "firefox": "Firefox",
    "telegram": "Telegram",
    "spotify": "Spotify",
    "mail": "Mail",
    "messages": "Messages",
    "calendar": "Calendar",
    "securitycenter": "Security",
    "defender": "Security",
    "zoom": "Zoom",
    "gmail": "Gmail",
    "instagram": "Instagram",
}


def friendly_app(raw: str) -> str:
    """'MSTeams_8wekyb3d8bbwe!MSTeams' / 'com.tinyspeck.slackmacgap' -> 'Teams' / 'Slack'."""
    low = raw.lower()
    for key, name in FRIENDLY.items():
        if key in low:
            return name
    tail = re.split(r"[!._\\/]", raw)
    words = [
        w for w in tail if w and not re.fullmatch(r"[0-9a-z]{13}|com|app|microsoft|windows|apple", w.lower())
    ]
    return (words[-1] if words else raw)[:14]


def _win_db() -> Path:
    return Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db"))


def _mac_db() -> Path:
    return Path.home() / "Library/Group Containers/group.com.apple.usernoted/db2/db"


def parse_toast(payload: bytes | str) -> tuple[str, str]:
    xml = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    texts = [unescape(t).strip() for t in re.findall(r"<text[^>]*>([^<]*)</text>", xml)]
    texts = [t for t in texts if t]
    return (texts[0] if texts else ""), (" ".join(texts[1:3]) if len(texts) > 1 else "")


class NotificationsProvider(Provider[dict[str, Any]]):
    name = "notifications"
    interval = 2.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._last: int | None = None  # highest row id seen
        self.recent: list[dict[str, Any]] = []

    def announce(self, old: Any, new: Any) -> bool:
        return bool(new and new.get("new"))

    def _query(self) -> list[dict[str, Any]]:
        if sys.platform == "win32":
            path = _win_db()
            sql = (
                "select n.Id, h.PrimaryId, n.Payload from Notification n join NotificationHandler h "
                "on h.RecordId = n.HandlerId where n.Type = 'toast' and n.Id > ? order by n.Id"
            )
        elif sys.platform == "darwin":
            path = _mac_db()
            sql = "select r.rec_id, a.identifier, r.data from record r join app a on a.app_id = r.app_id where r.rec_id > ? order by r.rec_id"
        else:
            raise RuntimeError("OS notifications are supported on Windows and macOS")
        if not path.exists():
            raise RuntimeError(f"notification database not found ({path})")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        try:
            if self._last is None:  # first run: start from "now", never replay history
                q = (
                    "select max(Id) from Notification"
                    if sys.platform == "win32"
                    else "select max(rec_id) from record"
                )
                self._last = int(con.execute(q).fetchone()[0] or 0)
                return []
            rows = con.execute(sql, (self._last,)).fetchall()
        except sqlite3.DatabaseError as e:
            if sys.platform == "darwin":
                raise RuntimeError(
                    "macOS blocks this: give Full Disk Access to the app running DotDeck"
                ) from e
            raise
        finally:
            con.close()
        out = []
        for rid, app, payload in rows:
            self._last = max(self._last or 0, int(rid))
            if sys.platform == "win32":
                title, body = parse_toast(payload)
            else:
                try:
                    req = plistlib.loads(payload).get("req", {})
                    title, body = str(req.get("titl", "")), str(req.get("body", ""))
                except Exception:
                    continue
            if title or body:
                out.append({"id": int(rid), "app": friendly_app(str(app)), "title": title, "body": body})
        return out

    async def fetch(self) -> dict[str, Any]:
        new = await asyncio.to_thread(self._query)
        for n in new:
            self.hub.emit("os_notification", n)
        self.recent = (new[::-1] + self.recent)[:20]
        return {"new": len(new), "recent": self.recent}

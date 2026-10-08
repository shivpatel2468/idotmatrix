"""Turn a raw connect / link error into a reason code and one human next step (docs/STUDIO_UI.md "Connection").

Bluetooth stacks report failures in their own words (bleak on WinRT / BlueZ / CoreBluetooth, Chrome's Web
Bluetooth, the Android bridge). The studio and the web app show the same few situations, so they are classified once
here and published on `DeviceInfo.reason` / `DeviceInfo.hint`:

==============  ===========================================================================
reason          meaning
==============  ===========================================================================
bluetooth_off   this computer's Bluetooth is off or has no adapter
not_found       the panel isn't advertising: off, out of range, or held by another app
busy            not found several times in a row: most likely held by another app
no_answer       found, but the connection didn't complete (timeout, GATT error)
permission      the browser / OS refused Bluetooth access
needs_user      the browser needs a click to pick the panel (Web Bluetooth's user gesture)
link_lost       the link dropped; the device layer is reconnecting by itself
released        the user released the panel (link off); nothing reconnects until they say so
error           anything else
==============  ===========================================================================

Pure functions: no I/O, tested in tests/test_device_connection.py.
"""

from __future__ import annotations

import re

#: consecutive "not found" failures after which the panel is most likely held by another app
BUSY_AFTER = 3

_OTHER_APPS = {
    "ble": "the iDotMatrix phone app, a DeskDot browser tab (idotmatrix.com/app) or the DeskDot Android app",
    "web": "the iDotMatrix phone app, DeskDot on this computer, or the DeskDot Android app",
    "android": "the iDotMatrix phone app, DeskDot on a computer or a DeskDot browser tab",
    "sim": "another app",
}

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("released", re.compile(r"disconnected from the studio|unlinked in the studio|released", re.I)),
    (
        "permission",
        re.compile(r"permission|securityerror|not allowed|access (is )?denied|unauthori[sz]ed", re.I),
    ),
    ("needs_user", re.compile(r"pick your|connect panel|needs? a click|no panel picked", re.I)),
    (
        "bluetooth_off",
        re.compile(
            r"bluetooth (is |was )?(turned )?off|turned off|adapter.*(off|not (found|available|powered))|no bluetooth"
            r"|radio.*off|not powered|device is not ready|powered ?off|bluetooth.*unavailable",
            re.I,
        ),
    ),
    ("busy", re.compile(r"connected to deskdot|in use by another|held by another", re.I)),
    ("link_lost", re.compile(r"link lost|gattserverdisconnected|write failed", re.I)),
    (
        "not_found",
        re.compile(
            r"not found|no longer in range|out of range|unreachable|no such device|isn't advertising", re.I
        ),
    ),
    (
        "no_answer",
        re.compile(r"timed? ?out|didn't answer|did not answer|gatt|networkerror|failed to connect", re.I),
    ),
]


def classify(message: str | None) -> str:
    """The reason code for a raw error message (see the module table)."""
    text = message or ""
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return reason
    return "error"


def hint(reason: str, kind: str = "ble") -> str:
    """One or two sentences: what is going on and what to do about it."""
    others = _OTHER_APPS.get(kind, _OTHER_APPS["ble"])
    retry = "Press Reconnect now, or wait: DeskDot keeps trying."
    if reason == "bluetooth_off":
        where = "this browser's computer" if kind == "web" else "this computer"
        return f"Turn Bluetooth on for {where} (Windows: Settings → Bluetooth & devices). DeskDot connects as soon as it's on."
    if reason == "not_found":
        return (
            f"Is the panel plugged in and within a few metres? A panel talks to one app at a time — close {others}. "
            + retry
        )
    if reason == "busy":
        return (
            f"The panel isn't showing up. It's most likely connected to {others}: close it there (or press "
            "Release the panel in that DeskDot), then Reconnect now. Still nothing? Unplug the panel for 5 seconds."
        )
    if reason == "no_answer":
        return (
            f"The panel didn't finish connecting — often because {others} still holds it: close that first. "
            "Otherwise unplug the panel for 5 seconds; if it keeps failing, turn Bluetooth off and on. "
            + retry
        )
    if reason == "permission":
        if kind == "web":
            return "This browser needs permission to use your panel: press Pick panel and choose your IDM-… panel."
        return "Bluetooth access was refused. Allow Bluetooth for DeskDot / Python in the system settings, then Reconnect now."
    if reason == "needs_user":
        return "Press Pick panel and choose your IDM-… panel in the browser's list (browsers need one click)."
    if reason == "link_lost":
        return "The link dropped (panel unplugged, out of range or asleep). Reconnecting by itself — nothing to do."
    if reason == "released":
        return "You released the panel, so other apps can connect to it. Press Connect to take it back here."
    return retry


def diagnose(message: str | None, kind: str = "ble", attempts: int = 0) -> tuple[str, str]:
    """(reason, hint) for a failure. Repeated "not found" becomes "busy": the usual cause is another app."""
    reason = classify(message)
    if reason == "not_found" and attempts >= BUSY_AFTER:
        reason = "busy"
    return reason, hint(reason, kind)

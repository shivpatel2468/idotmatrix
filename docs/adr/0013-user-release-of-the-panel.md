# ADR 0013: The user may release the panel; the engine never lets go on its own

- **Status:** Accepted
- **Date:** 2026-10-08
- **Extended by:** [ADR 0015](0015-panel-handover-between-deskdots.md) — releases are graceful (the write in flight
  finishes first) and another DeskDot can ask for the panel itself

## Context

Rule 5 says *never disconnect the panel voluntarily*: a dropped link makes the panel blink its pairing screen, and
the old build's habit of disconnecting between jobs made it flicker and lose its picture. The device layer
therefore holds one GATT session for the engine's lifetime and reconnects by itself (`Device._supervise`).

But a panel accepts **one** connection at a time, and people now have several ways to drive it: DeskDot on the
computer, the web app in a browser tab (ADR 0012), the Android app, the vendor's phone app. Moving the panel from
one to another used to mean finding and quitting the other app — the user's top complaint ("I'm having a hard time
finding where it is connected… and it's dicey whether it will connect"). Two forces collide:

- **Rule 5** — no disconnect the user didn't ask for.
- **Handing over** — the only way to let another app connect is for the current holder to disconnect, and the
  holder must then *stop reconnecting*, or it grabs the panel back seconds later (the supervisor retries every
  1–20 s).

The studio already had a "Disconnect…" button behind a confirmation (`POST /api/device/link {enabled:false}`), which
does exactly this, but it was buried in Settings → Device with no explanation of what it was for.

## Decision

- **"Release the panel" is an explicit user action, not a voluntary disconnect.** It is allowed under rule 5
  because the user asked for it, it is behind a confirmation, and the confirmation says what happens: the panel
  shows its pairing screen until another app connects. It lives in the Connection sheet (top bar pill) and in
  Settings → Device; the API is unchanged (`POST /api/device/link {enabled:false}`).
- **Released means released.** While `link_enabled` is false the supervisor makes no attempt at all (tested in
  `tests/test_device_connection.py`), so the other app can connect. The panel comes back only through **Use the
  panel here** (`link {enabled:true}`) or **Reconnect now** (`POST /api/device/reconnect`), which also take it back.
  Not persisted: restarting the engine connects as usual (restarting is the user asking DeskDot to drive it).
- **The engine itself still never lets go.** "Reconnect now" on a link that is down only cuts the back-off wait
  short (`Device.retry_now()`); it never disconnects. A connected "Reconnect" still drops and re-opens the link —
  a user action kept for applying a new packet size — and `only_if_down` skips it.
- **The web app's tab hand-off avoids the disconnect entirely.** Two tabs of one browser share Chrome's GATT link:
  the old tab stops writing after the item in flight (`Device.pause_writes()`, never a half-sent GIF — rule 13),
  keeps its handle until the new tab reports "connected", then lets go, so the panel never sees the link drop.
  If sharing fails, the new tab asks the old one to let go at once and waits for the panel's advertisements.
- **Failures explain themselves** instead of offering a release: `device/diagnose.py` turns raw errors into a
  reason (`bluetooth_off`, `not_found`, `busy`, `no_answer`, `permission`, `needs_user`, `link_lost`, `released`)
  and a next step, published on `state.device` and shown by the studio and the web app.

## Consequences

- Moving the panel between apps is two clicks in the app that has it (Release the panel) and one in the app that
  wants it (Reconnect now / Pick panel), with the pairing screen in between as the honest cost.
- A user can leave DeskDot released by mistake. The pill then reads **Released** (grey LED) and the Connection
  sheet's primary button is **Use the panel here**, so the state is visible and one click undoes it.
- Agents and scripts can release the panel through the same HTTP call; like every API call, that is the user's
  agent acting for them, and the engine treats it as a user action.
- Rule 5 in CLAUDE.md stays as written: the device layer never disconnects on its own initiative.

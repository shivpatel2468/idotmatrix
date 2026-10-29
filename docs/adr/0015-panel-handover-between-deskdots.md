# ADR 0015: Hand the panel over between DeskDots, cleanly, with one button

- **Status:** Proposed (accept after the laptop + phone + browser walk-through on the real panel)
- **Date:** 2026-10-30
- **Extends:** [ADR 0013](0013-user-release-of-the-panel.md) (the user may release the panel)

## Context

The user drives one panel (IDM-039C09) from three places: DeskDot on a Windows laptop (bleak / WinRT), the DeskDot
Android app (Chaquopy + the Kotlin `BleBridge`) and the web app in Chrome (Web Bluetooth). The panel accepts **one**
central at a time. Moving it was "most of the time glitchy" and often ended with unplugging the panel.

The engine's own log (`data/engine.err.log`, 3.2.0, 4–6 Oct) shows what that looked like from the laptop:

| Time | What the log says | What it means |
| --- | --- | --- |
| 22:45:54 | `panel link lost` + `bleak…: unhandled services changed event` | the link dropped (the phone took it, or the panel reset its GATT) |
| 22:46:04 → 23:09:28 | `panel not found (B4:BE:47:03:9C:09)` every 30 s, **50 times** | the panel stopped advertising for 23 minutes |
| 17:15:12 → 17:16:43 | `link lost`, then `connect timed out after 45s` 19 s later, `not found`, `timed out`… | attempts started 1 s after the drop, before the panel re-advertised; the "45 s" was really bleak's own 15 s timeout |
| 20:49:15 | `link lost`, `ack notifications unavailable: …canceled`, `panel connected`, `write failed: not connected` — same second | a connect "succeeded" on a session that was already closing; the studio said connected, the first write failed |
| whole log | 16 connects, 16 link losses, 328 `connect timed out`, 938 `panel not found`, 12 `unhandled services changed` (each right at a link loss) | for every good connect, ~80 failed attempts — most against a panel that wasn't advertising |

Root causes, from that evidence and the code (details in docs/HARDWARE_PROTOCOL.md finding 18):

1. **WinRT kept the panel connected after "disconnect".** Windows keeps a BLE link up while *any* WinRT object of it
   lives — `GattSession`, `BluetoothLEDevice`, or one `GattDeviceService`. bleak closes the session and device when the
   link drops but closes the services only in `disconnect()`, and `BleDevice._disconnect()` skipped `disconnect()`
   whenever `is_connected` was already false (every link loss). A timed-out attempt was worse: the client wasn't
   stored until `connect()` returned, so the supervisor's cleanup never saw it and a fully set-up session with
   `maintain_connection=True` leaked. Either way Windows held the panel, invisibly: it stopped advertising, the phone
   and the browser couldn't find it, and only a power-cycle (or quitting Python) freed it.
2. **Android closed the GATT before disconnecting it.** `BleBridge.disconnect()` called `close()` right after
   `disconnect()`, and a new attempt `close()`d the old GATT without disconnecting at all. On many phones that leaves a
   ghost link in the controller — the same "not advertising until unplugged" symptom. A Python-side connect timeout
   also left the bridge's attempt running, so a late success held the panel for an engine that had given up.
3. **Release cut transfers in half.** `set_link(False)` disconnected at once, even mid-GIF upload. HARDWARE_PROTOCOL
   finding 15 shows an interrupted GIF leaves the firmware ignoring the next one — the next app found a blank panel.
4. **Reconnects raced the panel and each other.** Attempts started 1 s after a drop (the panel needs ~2 s to
   advertise again), every instance retried on the same 1-2-4-…-20 s schedule, and nothing stopped two DeskDots from
   trying at the same moment.
5. **Stale callbacks and caches.** A late disconnect callback from an old session could mark a new link lost, and
   Windows' cached GATT table ("services changed") made `start_notify` fail on links that were already going away.
6. **Web Bluetooth could hang.** `gatt.connect()` had no timeout; while it hung, the page ignored every new attempt
   (`connecting` stayed true) until a reload. `disconnect()` didn't wait for the write in flight or for the link to
   actually drop.

And there was no way for one DeskDot to *ask* another to let go: the user had to find the holder and press Release.

## Decision

**Device layer (all backends):**

- Releasing is graceful: `Device.set_link(False)` pauses the writer, waits for the item in flight (a GIF upload keeps
  waiting for each chunk's ack — rule 13), then disconnects and disposes the session. `reconnect()` does the same.
- Every failed or timed-out attempt calls `_reset_stack()`: the backend drops every GATT object it might still hold.
  BLE: every `BleakClient` is disposed with `disconnect()` (stored before `connect()`), callbacks are bound to their own
  client, services are read uncached (`use_cached_services=False`), and a connect that loses its link during setup
  fails instead of reporting "connected". Android: disconnect first, `close()` when the stack confirms (or after 2 s);
  a Python-side timeout aborts the bridge's attempt. Web: `gatt.connect()` times out after 20 s and is cancelled;
  `disconnect()` lets the write in flight settle and waits until Chrome reports the link down.
- After a drop or release, the next attempt waits `REARM_DELAY` (2.5 s) for the panel to re-advertise; back-off
  delays get ±20 % jitter so two instances never retry in lockstep.
- **Recovery instead of a power-cycle:** after every 4th consecutive failure the supervisor resets the stack, waits up
  to 30 s for the panel's advertisement, connects, and replays gently (power and brightness first, a GIF only after
  the cool-down). Published as `reason: recovering` and `recoveries`.

**Coordination between instances (`src/deskdot/handover.py`, routes in `handover_api.py`):**

- **Discovery:** a UDP broadcast beacon on port 8767 every 4 s (and on every change) — id, name, kind, http port,
  whether it holds the panel (or its browser tab does), since when, and the connect lease it knows. Sent and accepted
  only on private / link-local addresses; off with the studio's *Find other DeskDots on this network* (stored as
  `handover.enabled`) or `lan_handover = false`. Chosen over mDNS: no new dependency (zeroconf isn't in the Android
  build either), one socket, and the payload is the state we need anyway.
- **Lease:** one owner at a time, 30 s expiry. The taker claims it, the holder grants it when it lets go, and beacons
  carry it. While another instance holds the panel or the lease, a supervisor's automatic attempts wait at
  `Device.gate` (`reason: elsewhere`) instead of adding connect attempts to the air. A holder asked twice answers the
  second taker "busy". Explicit user actions are never blocked by a beacon.
- **Pairing, once per pair of installs:** B → `POST /lan/handover/pair` → both studios show the same 6-digit code
  (derived from both nonces) → the user presses **Allow** on A → B's poll receives a random 256-bit key. That is the
  only moment a secret crosses the LAN; keys live in `data/handover.json` (mode 600). Without pairing nothing can
  release anything; the UI says so and offers Pair.
- **Signed hand-over requests:** `POST /lan/handover/release` and `/announce` carry `x-deskdot-peer`, `-ts`, `-nonce`
  and `-sig` = HMAC-SHA256(key, method ‖ path ‖ ts ‖ nonce ‖ sha256(body)); refused when unpaired, older/newer than
  120 s, replayed (nonce cache), not from a private address, or over 10 / min per peer and 30 / min per address.
  `LanGate` lets `/lan/handover/` through from the LAN; the studio API (`/api/…`) stays on this computer.
- **The flow:** B claims the lease → asks A → A finishes the write in flight, disconnects cleanly, marks itself
  released ("Panel moved to B", no auto-reconnect; ADR 0013 semantics) and acks → B waits for the advertisement (≤ 20 s)
  → B's supervisor connects (≤ 50 s, jittered) → B announces. A shows **Take it back**, which is the same flow
  reversed. If A can't be reached, B says who probably has the panel (the last instance that claimed it) and offers
  **Try anyway**: wait for the advertisement, try, and explain what to close if it never comes.
- **The browser tab** can't do UDP, and an https page can't call a phone's http address (mixed content / Private
  Network Access). It talks to DeskDot on the same computer over loopback: `POST /api/handover/tab` reports whether it
  holds the panel (the answer says when someone wants it, and the tab releases gracefully through its own engine),
  and `POST /api/handover/free` asks DeskDot to free the panel for it — releasing its own link, or relaying a signed
  request to the phone. Both answer CORS + PNA only for the web app's origins and refuse any other cross-site Origin.
  Without DeskDot on the computer, the sheet explains how to release the panel on the phone by hand.

## Consequences

- Moving the panel is one button on the device that wants it, with live steps (*Asking Pixel to let go → Released →
  Waiting for the panel → Connected*) and a plain-words error when a step fails. The pairing screen still blinks for
  the second or two between centrals; that is the honest cost of one central.
- A stuck "not advertising" panel is now usually our own leaked session, and the engine clears it itself.
- Pairing is one extra step, once. A passive sniffer on the same Wi-Fi at that moment could learn the key and then
  release the panel — the worst it can do; documented and accepted for a desk lamp. Beacons are unauthenticated
  hints: a spoofed "I hold it" only makes automatic retries wait (explicit actions ignore it).
- Clocks must agree within 2 minutes for signed requests (phones and PCs use network time).
- Windows Firewall: DeskDot's existing "allow on private networks" rule covers the beacon port; on a *Public*
  network profile Windows blocks it, which matches "never on public networks".
- The device layer still never disconnects on its own initiative (rule 5): a hand-over is the user's action on the
  other device, authenticated by pairing.

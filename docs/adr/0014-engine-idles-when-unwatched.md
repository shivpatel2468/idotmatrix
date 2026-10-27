# ADR 0014: The engine idles when nobody is watching; the watch holds locks only on demand

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

On the Fossil Gen 6 (ADR 0012) the engine ran for hours with **no panel in range**. What the lead measured:
`PARTIAL_WAKE_LOCK 'DeskDot::engine'` held for 6 h 13 min, `com.deskdot.app` at about 10 % of total CPU nonstop,
CPU zones at 51–53 °C and the battery at 42–44 °C (warm on the wrist). The log showed
`connect failed: panel not found … retrying in 20s` forever.

Profiled on the watch with the in-process sampler (`GET /api/debug/profile`, `deskdot/profiling.py`; py-spy can't
attach to the 32-bit Chaquopy process without root), plus per-thread `/proc/<pid>/task/*/stat`:

- The `deskdot-engine` thread used **648 of 759 process ticks per minute** (about 11 % of one core) while no panel
  was connected and no client was open. Its stacks were all `Engine._run → _tick`: `app.render` (a game, about 10 ms
  per frame on the A53) and **`Frame.to_png` → PIL PNG encode (43 % of the tick)**. Every frame was encoded for a
  device slot that no link would ever drain.
- With a 20 s retry cap, each panel attempt is an 8 s direct connect followed by a 10 s low-latency scan. With no
  panel, the radio was scanning about a quarter of the time, forever.
- `EngineService` held the partial wake lock, the Wi-Fi lock and a Wi-Fi `requestNetwork` for the service's whole
  life, so the SoC never suspended. (`requestNetwork` actually failed every time: `CHANGE_NETWORK_STATE` was never
  declared.)
- Smaller wake-ups: the device supervisor polled at 1–2 Hz while connected or released, and the studio heartbeat
  ticked every 2 s with no clients.

## Decision

1. **The engine loop is demand-driven** (`Engine.demand()`, all hosts). It ticks only while something consumes its
   output: a connected panel, a frame listener (studio / watch UI / TV / phone preview), or a `hold()` (`lobby`,
   `tv`, `lan`). Otherwise it hides the current app and releases every provider, including the background ones
   (alerts, ntfy, …), then awaits `_wake` with **no timeout**. The panel link's status, listeners joining or leaving
   (`_ListenerSet`) and holds all set `_wake`, so it resumes on the next loop iteration and re-shows the app.
   `GET /api/frame(.png)` renders on demand while idle (the watch Tile).
2. **No PNG for a missing panel.** While the link is down the engine skips encoding and calls
   `Device.forget_visual()`. On connect it re-sends its *current* visual instead of the device replaying a stale one.
3. **Supervisor and heartbeat are event-driven**: they wait on `_link_changed` and "has clients" events instead of
   polling.
4. **Panel back-off** is `retry_base` doubling to `retry_cap`: 20 s on phone and desktop (unchanged), **10 min on the
   watch** (`Config.low_power`, which `android_main.run(..., watch=True)` sets). On the watch every failed attempt
   also parks `BleBridge.standby(mac)`, a `connectGatt(autoConnect=true)` that the Bluetooth controller completes
   by itself when the panel comes back (no scan, no CPU). The engine adopts that link at once. Watch scans are 5 s
   and address-filtered in the controller. Releasing or forgetting the panel cancels the standby.
5. **Locks follow demand on the watch** (`R.bool.is_watch`). `Engine.power_listeners` → `android_main` →
   `EngineService.onPowerDemand(wake, wifi)`:
   - wake lock: held while a panel is linked or a client on another device is connected;
   - Wi-Fi lock plus `requestNetwork`/`bindProcessToNetwork`: held while a lobby or TV link is open, or such a LAN
     client is connected;
   - start-up: a 120 s timed wake lock covers the Python start until the first report.

   The phone keeps both locks for the service's life, as before. The foreground service stays alive, idle.

## Consequences

- Idle with no panel, the watch does no periodic work in DeskDot: no ticks, no provider polling, no scans, no locks.
- Every feature is kept. Opening the watch UI, the studio, a lobby, a TV link or a phone controller, or the panel
  reappearing, resumes the engine within one loop iteration.
- Notices and background alerts are not collected while nobody is there to see them. Live-data apps refetch when
  they are shown again.
- A *LAN* studio can reach an idle watch only while Wi-Fi is up: when the watch screen is on, or while hosting. The
  watch UI's sharing pages hold their own Wi-Fi lock.
- On the watch, a panel that comes back while the standby has lapsed (Bluetooth toggled, controller gave up) waits
  for the next active attempt, at most 10 min. "Reconnect" in the UI starts one at once.

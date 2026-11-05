# ADR 0016: Let the phone sleep when there is nothing to drive

- **Status:** Proposed (accept after a night on battery with the new build on the owner's phone)
- **Date:** 2026-11-05
- **Changes:** [ADR 0011](0011-android-host-app.md) (the app held its locks for the engine's whole life),
  [ADR 0015](0015-panel-handover-between-deskdots.md) (beacons every 4 s, a multicast lock all the time)

## Context

A read-only battery check on the owner's phone (Xiaomi 11i HC, Android 13 custom ROM, battery at 40 % health) covered
14 h 06 m on battery with the screen off. The phone averaged ~55 mA, about 5 % an hour. DeskDot caused most of it:

| What | How much | Why |
| --- | --- | --- |
| `DeskDot::engine` wake lock | 13 h 58 m held, 87 mAh | `EngineService` acquired it in `onCreate` and never let go: the CPU never deep-slept |
| Wi-Fi | 64 mAh | a full Wi-Fi lock (`LOW_LATENCY` / `HIGH_PERF`) for the same time, plus a UDP beacon every 4 s |
| mDNS wakeups | 73,000 packets, 156 mAh | the session-long multicast lock turned off the Wi-Fi chip's multicast filter, so every mDNS packet on the LAN woke the CPU |
| CPU | 53 min | the engine ticked at the app's frame rate whether or not anyone could see a frame |

Meanwhile the log shows the phone often wasn't driving the panel at all: the laptop had it, or "panel not found …
retrying" every ≤ 20 s for hours, 222 low-latency scans. Those scans were unfiltered (`startScan(null, …)`), and
Android delivers no results from an unfiltered scan while the screen is off — so they couldn't have found the panel
anyway.

## Decision

**The engine decides when it needs the CPU; the app holds locks only then.** `deskdot/keepawake.py` evaluates every
2 s (`decide()`, pure) and reports to the app's `PowerGate.kt` (through Chaquopy):

- *Awake* — the app is on screen; a hand-over or pairing runs; another device on the LAN called in the last 2 min;
  something is being written to the panel; the panel is connected and the engine streams live content
  (`Engine.cpu_reason()`: a stream app, overlay, transition, test card, takeover, timed app, playlist of 2+,
  background providers, a bake); or the panel was lost less than 3 minutes ago.
- *Asleep* — released, held by another DeskDot, missing for 3+ minutes, or showing a baked clip / the firmware clock
  with nothing live. A 30 s grace absorbs short gaps (a GIF finishing, the app reopening), except between scheduled
  reconnect attempts.

Asleep, `PowerGate` drops the wake lock **and** the Wi-Fi lock and sets an inexact, Doze-friendly alarm
(`setAndAllowWhileIdle`) for the engine's next look: the next reconnect attempt, a clip that re-bakes with time, or
15 minutes. The alarm takes a 25 s `DeskDot::nudge` lock and pokes the Python event loop.

**The loop's clock counts sleep.** asyncio timers run on `CLOCK_MONOTONIC`, which stops while the phone sleeps: a
3-minute back-off would take hours of wall time, and a woken CPU would still find "2 minutes to go". On Android the
loop is `BootClockLoop` (`CLOCK_BOOTTIME`), so overdue timers run as soon as anything wakes the CPU.

**The BLE link is not touched.** The Bluetooth controller keeps a GATT connection while the CPU sleeps; notifications
and the engine's own writes wake it. Rules 5, 6 and 13 are unchanged: no extra disconnects, no queued frames, the same
pacing and packet sizes. While connected and live nothing changes at all.

**Multicast only when someone listens.** The multicast lock is held while the hand-over setting is on *and* the screen
is on or a hand-over / pairing runs. The phone still *sends* beacons, and release requests reach it over plain HTTP
(`POST /lan/handover/release` to the address in its beacon), so a laptop can always take the panel.

**Slower beacons when nobody listens.** 4 s while the screen is on or another DeskDot was heard within a minute; else
10 s while holding the panel (under the 15 s that 3.10 peers treat as "nearby") and 20 s when not. Beacons now carry
their pace (`every`); a peer stays nearby for 2.5 × that, 15–60 s. A phone asleep with a clip sends no beacons at all,
so "Use the panel here" with no fresh holder now first asks the paired instance that last held the panel.

**Find the panel cheaply.** `BleBridge` remembers the last panel's MAC, connects to it directly, and filters the
fallback scan by it (results arrive with the screen off). Low-latency scans only while the app is on screen; balanced
with the screen on; low-power (a 20 s window) with it off. After 10 minutes of failures the supervisor retries about
every 3 minutes; *Reconnect now*, a holder letting go or opening the app starts over at 1 s.

**Tick slowly when nobody can see.** Released or disconnected with no studio / TV watching, the engine ticks at most
once a second (playlists, night mode and notices still advance).

## Consequences

- A phone that drives a static clip, has released the panel, or can't find it deep-sleeps between events. A phone
  streaming live content behaves exactly as before.
- Time-driven work while asleep (night mode, a clip re-bake) runs on the alarm, up to ~9 minutes late in deep Doze.
- While the phone sleeps holding the panel, other DeskDots stop seeing it as the holder; taking the panel still works
  (they ask the last holder), but their studio shows "probably" instead of "has". A 3.10 laptop doesn't ask; it needs
  the phone awake (open the app) or the user's Release.
- LAN requests (a phone controller, a hand-over) wake the phone through the Wi-Fi chip; the first can be slow while
  it wakes, then it stays awake for 2 minutes.
- Not done: dropping the connection priority from HIGH while a clip plays (radio power) — it changes link physics and
  needs measuring on the panel first.

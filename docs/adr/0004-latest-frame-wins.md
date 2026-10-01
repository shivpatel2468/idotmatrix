# ADR 0004: Latest-frame-wins device scheduler

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

BLE throughput (~5–25 KB/s) is far below what the render loop can produce. A FIFO queue makes the panel fall
behind the studio by seconds — the core of v2's perceived lag.

## Decision

The device keeps one slot per kind of work (commands FIFO, gif slot, merged pixel map, frame slot) and a single
writer drains them in priority order, pacing frames to `max_fps`. New frames replace unsent ones; `frames_dropped`
counts superseded frames.

## Consequences

+ The panel is at most one frame behind; UI interactions feel instant.
+ Commands (brightness, power) never wait behind frames.
− Intermediate frames of fast animations are skipped on the panel — which is why loops are clips (ADR 0005).

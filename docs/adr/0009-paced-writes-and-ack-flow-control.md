# ADR 0009: Pace packets and use the panel's acks for flow control

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

On real hardware, frames larger than one BLE packet never displayed (the "512-byte limit" others reported),
although the panel acknowledged them. Scripted tests with the user watching the panel showed back-to-back
write-without-response packets are dropped; a 30 ms gap fixes it. The reference PNG header's length field was also
wrong for multi-packet images. Waiting for every image ack serialised the link at 2.6 fps.

## Decision

The device base class splits every message into packets separated by `packet_gap` (configurable), writes the true
packet length in the PNG header, subscribes to `fa03` acks, keeps one frame in flight, and waits for the ack of
every 4 KiB GIF chunk. Baked GIFs are kept under a 40 KB budget by shrinking the palette.

## Consequences

+ Every app displays correctly; streaming ~9 fps for UI frames, ~6–7 fps for photos; big GIFs play smoothly.
− Photo-frame fps is bounded by the gap; lowering it needs a new hardware test (documented as a rule in CLAUDE.md).

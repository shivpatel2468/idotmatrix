# ADR 0005: Bake deterministic animations to GIFs the panel plays natively

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Streaming a 12 fps animation over BLE saturates the link and still stutters. The panel can store and loop a GIF by itself.

## Decision

Apps declare `kind()`: `stream`, `clip` or `native`. Clips are rendered once (in a thread), encoded with a single
shared palette, uploaded once per `clip_key()` and then cost nothing. Overlays/transitions temporarily stream and
the clip is re-uploaded afterwards.

## Consequences

+ Perfectly smooth animation, zero steady-state traffic, better battery/radio behaviour.
− A short upload delay when switching to a clip app (hidden by the 0.4 s transition); loops must be designed seamless.

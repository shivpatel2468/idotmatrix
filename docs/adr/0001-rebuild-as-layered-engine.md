# ADR 0001: Rebuild as a layered engine instead of patching v2

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The v2 build was a single 1,563-line `app.py`: globals for state, HTML in a Python string, one polling loop
that mixed network I/O, rendering and BLE writes. It was laggy for structural reasons (blocking calls in async
code, refetching every 1.8 s, FIFO frame pushes, lyrics re-search) and every feature required editing the UI by hand.

## Decision

Rewrite as a package with strict layers — `gfx` (pure), `device` (the only BLE writer), `providers`
(background data), `engine` (what's on screen), `apps` (plugins), `server`, `mcp_server`, and a separate `web/`
studio. The v2 code is kept in `legacy/` for reference only.

## Consequences

+ Each concern is testable in isolation (144 tests on day one, all on a simulator).
+ Lag sources are removed by construction, not by tuning.
− More files; contributors must learn the layer rules (CLAUDE.md, ARCHITECTURE.md).

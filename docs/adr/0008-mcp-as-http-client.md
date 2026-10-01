# ADR 0008: MCP server is a thin client over the engine's HTTP API

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Agents should see and control the panel live. BLE allows one central, and the engine already owns the link and all state.

## Decision

`deskdot-mcp` (stdio) calls the engine's REST API. It exposes intent-level tools (show app, pixel art,
notify, agent state) plus `panel_snapshot`, which returns the current frame as an image so agents can verify results.

## Consequences

+ No second BLE owner, no duplicated logic; works against a remote engine via `DESKDOT_URL`.
− The engine must be running; tools fail with a clear message if it isn't.

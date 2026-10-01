# ADR 0010: Provider events and Autopilot are engine-level, not app-level

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Goal celebrations must fire even when the Scores app isn't visible, and "show Now Playing when Spotify is in front"
spans apps. Putting either inside an app would couple apps to each other and to visibility.

## Decision

Providers emit discrete events through `Hub.emit()`; the engine subscribes and decides (e.g. a `score` event plus
the Scores alert setting → a `celebrate` overlay). The engine holds background providers (`sports`, `window`) only
while a feature needs them. Autopilot rules (foreground process / window-title match → app + settings) are evaluated
first in slot selection, above the playlist.

## Consequences

+ Apps stay pure renderers; cross-app behaviour is visible in one place (`Engine._on_event`, `_autopilot_slot`).
− Background features keep a provider polling; the Settings sheet shows which ones are active.

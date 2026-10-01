# ADR 0007: Studio in React + TypeScript + Vite + Tailwind v4, frames over one WebSocket

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

v2 served a CDN Tailwind page from a Python string and polled five endpoints every 1.8 s. Requirements: an
LED-accurate live preview at up to 20 fps, painting with instant feedback, a design system, offline use.

## Decision

A Vite-built React 19 SPA served from `web/dist` by the engine. One WebSocket carries state JSON (on change) and
raw 3,072-byte RGB frames; frames bypass React and are drawn on a canvas with bloom. Tailwind v4 `@theme` holds
the design tokens; fonts are bundled.

## Consequences

+ Smooth preview with negligible CPU; strict types; design tokens in one place; works offline.
− A Node toolchain for studio development (end users only need the built `dist`).

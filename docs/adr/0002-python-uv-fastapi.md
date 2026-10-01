# ADR 0002: Keep Python for the engine; manage it with uv; serve with FastAPI

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The engine needs BLE on Windows, Windows media-session access and image processing. Alternatives: Node (noble is
fragile on Windows, no first-class WinRT media), Rust (btleplug + windows-rs is solid but slows iteration and the
app SDK would lose Python's accessibility), C# (.NET has WinRT but splits the ecosystem from the existing work).

## Decision

Python 3.13, `bleak` for BLE, `winrt` for media, numpy + Pillow for pixels, FastAPI + uvicorn for HTTP/WS,
pydantic v2 for every boundary, `uv` for interpreter + locked dependencies.

## Consequences

+ Proven BLE stack on this exact panel; plugin authors write plain Python.
+ pydantic schemas double as the studio's form definitions.
− Single-process GIL: fine at 32×32 (renders ≤ 2 ms); heavy work goes to threads.

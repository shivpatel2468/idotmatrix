# ADR 0003: Own the BLE transport and protocol encoders; drop the idotmatrix dependency

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The `idotmatrix` 0.0.9 library works but its `send()` calls `time.sleep()` (blocks the event loop), it
connects inside every call, uses a singleton that swallows constructor errors, writes every GIF chunk with
response and mixes encoding with I/O. It also pulls in `cryptography` for one unused command.

## Decision

Re-implement the protocol as pure functions in `device/protocol.py`, verified byte-for-byte against the library
and pinned by tests, and write our own async transport on `bleak` with reconnect, replay and a scheduler.

## Consequences

+ No blocking, full control of pacing and mode switches, testable without hardware.
− We must maintain the protocol; new firmware features need to be ported by hand (documented in HARDWARE_PROTOCOL.md).

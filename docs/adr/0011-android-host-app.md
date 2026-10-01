# ADR 0011: Host the whole engine on an Android phone as an app (Chaquopy + a Kotlin BLE bridge)

- **Status:** Proposed
- **Date:** 2026-09-30

## Context

The engine owns the panel's only BLE link (rule 4), so the panel only plays while the host runs. The user wants
a spare Android phone to be that host — an app like the vendor's, always connected, no laptop.

Options considered:

- **Termux** runs CPython and has numpy/Pillow, but has no Bluetooth LE access without root. Dead end on its own.
- **python-for-android + bleak's Android backend**: bleak's Android support targets p4a (pyjnius); p4a recipes for
  pydantic-core v2 do not exist and the build toolchain is Linux-only.
- **Rewrite the engine in Kotlin**: loses 89 apps, the providers and the tests. No.
- **A Raspberry Pi** (scripts/install-pi.sh) stays the most robust 24/7 host and remains supported.
- **Chaquopy** (CPython 3.13 embedded in a normal Android app, Gradle plugin) with our own BLE bridge in Kotlin.

Findings (2026-09-30):

- Chaquopy's repository has Android wheels for numpy 1.26.2, Pillow 11.0 and psutil 7.1 (cp313, arm64). The full
  test suite passes on numpy 1.26 (4060 passed), so the `numpy>=2.1` pin is not a real requirement.
- **pydantic-core has no Android wheel anywhere official.** It is a Rust extension; it can be cross-compiled with
  maturin + the Android NDK (a third-party Termux build shows the approach works).
- opencv / soundcard / winrt / syncedlyrics are only used by optional, lazily imported providers (camera, audio
  capture, Windows media, lyrics fallback) that simply report unavailable on Android.
- uvicorn's `[standard]` extras (httptools, uvloop, watchfiles) are optional; plain uvicorn + h11 + websockets
  (pure-Python fallback) serve the studio.

## Decision

Build an Android app in `android/`:

- **Python side unchanged** except a new device backend `device/android.py` (`device = "android"`) that implements
  the three `Device` hooks (`_connect`, `_disconnect`, `_write_packet`) on top of a Kotlin `BleBridge`, plus an
  `android_main` entry point that starts the engine with the app's data dir.
- **Kotlin side**: a foreground `EngineService` (type `connectedDevice`, persistent notification, partial wake
  lock) that starts Python once and keeps it running; `BleBridge` (one GATT session, MTU request, ack
  notifications, one GATT operation in flight — Android's own rule); a `WebView` activity on
  `http://127.0.0.1:8765`; a boot receiver; a battery-optimisation exemption prompt.
- **pydantic-core** cross-compiled once for `android_24_arm64_v8a` / cp313 and vendored as a wheel.
- All device behaviour (pacing, ack flow control, latest-frame-wins, GIF rules) stays in `device/base.py`, shared
  with the desktop, so the hardware findings in HARDWARE_PROTOCOL.md apply unchanged.

## Consequences

+ One APK; the phone is the host; the studio, multiplayer QR and MCP-over-HTTP work as on the laptop.
+ The Android BLE backend is unit-tested on the desktop against a fake bridge.
− We maintain a vendored pydantic-core wheel and must rebuild it when pydantic is upgraded.
− numpy is 1.26 on the phone; code must keep working on numpy 1.26 (tested).
− Android vendors may still kill background apps; the foreground service + battery exemption is the mitigation,
  verified per phone.

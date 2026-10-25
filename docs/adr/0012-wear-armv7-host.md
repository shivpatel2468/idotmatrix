# ADR 0012: Host the engine on the Fossil Gen 6 (Wear OS 3) as a 32-bit `wear` flavor on Python 3.11

- **Status:** Proposed
- **Date:** 2026-10-25

## Context

The owner wants the whole DeskDot engine (ADR 0011) running on their Fossil Gen 6 smartwatch: Wear OS 3 (API 30),
Snapdragon Wear 4100+, 1 GB RAM, round 416×416 AMOLED, BLE 5, Wi-Fi. Their rule: **no compromises, no feature
loss, no quality degradation** — every engine feature that works in the phone build must work on the watch.

Confirmed on the actual watch via `adb` (serial `192.168.1.127:38003`, read-only):

```
ro.product.cpu.abilist = armeabi-v7a,armeabi
ro.build.version.sdk   = 30
ro.product.model       = Fossil Gen 6      (codename "hoki")
MemTotal               = 943 MB   MemAvailable (idle) ~ 210-220 MB
```

**The watch's userspace is 32-bit only — there is no arm64-v8a fallback.** An armeabi-v7a build is mandatory, not
a nice-to-have.

The phone build (ADR 0011) uses Chaquopy 17.0.0 with CPython 3.13, `arm64-v8a` only. The question: can that same
toolchain produce an armeabi-v7a build, and if not, what is the least-compromising alternative?

## Findings

- **Chaquopy dropped the 32-bit ABIs (`armeabi-v7a`, `x86`) for Python 3.12 and later**, starting at Chaquopy
  15.0.1 ([chaquo/chaquopy#1476](https://github.com/chaquo/chaquopy/issues/1476)). Python 3.9–3.11 keep full
  32-bit support; 3.10/3.11 are Chaquopy's last versions with it (maintainers plan to drop 3.10/3.11 only in
  autumn 2027). So **Chaquopy + Python 3.13 + armeabi-v7a does not exist** — option (a) in the brief (build
  CPython 3.13 for armv7 via Chaquopy's own target build scripts) was evaluated and rejected: Chaquopy's target
  Python build is its own multi-week, Linux-hosted toolchain (NDK + a large patch set per CPython version) that
  Chaquopy's own maintainers have not ported to a 32-bit 3.12+ combination; reproducing it here, on a Windows build
  machine, within this task, is not realistic and was not attempted.
- **Chaquopy's Python 3.11 + armeabi-v7a combination is real and current**: `chaquo.com/pypi-13.1` serves
  `numpy-1.26.2-0-cp311-cp311-android_21_armeabi_v7a.whl` and `psutil-7.1.3-0-cp311-cp311-android_24_armeabi_v7a.whl`
  — the *same versions* already vendored for the phone's Python 3.13 build. This is option (b)/(c) merged: a
  32-bit-capable Python version the project's own CPython-version floor already tolerates (see below), not a
  feature-stripping downgrade.
- **Pillow has no cp311 wheel newer than 9.2.0** for either ABI on Chaquopy's repository (the phone's pinned
  11.0.0 only exists for cp312/cp313). Audited every Pillow call site in `src/deskdot` (`Image.Resampling`,
  `Image.Transpose`, `ImageOps.fit`, `ImageOps.exif_transpose`, `ImageFilter.UnsharpMask`/`MedianFilter`/
  `GaussianBlur`, `Image.fromarray`, `Image.frombuffer`) — every one of these APIs has existed since Pillow 9.1.
  9.2.0 is an older *build* of the same library for this one flavor, not a missing capability.
- **The codebase needs only one Python-version concession, and it is purely syntactic.** `requires-python` was
  `>=3.12,<3.14` because of exactly one construct: `def verify[T](...)` in `src/deskdot/casino/fair.py` (PEP 695
  generic-function syntax, Python 3.12+ only). `T` was already a module-level `typing.TypeVar` used elsewhere in
  the same file — the `[T]` was redundant syntax, not a semantic dependency on 3.12. Rewriting it as
  `def verify(...)` (using the existing `TypeVar`) is behaviourally identical. No other 3.12-only construct
  (`itertools.batched`, `type` statements, other PEP 695 generics, `@typing.override`) exists in `src/deskdot`.
  `requires-python` is now `>=3.11,<3.14`, and **the full test suite passes unmodified under Python 3.11**
  (`uv run --python 3.11 --extra mcp pytest -q`, verified in this session).
- pydantic-core (Rust, no official Android build either way) cross-compiles for `armv7-linux-androideabi` the same
  way it does for `aarch64-linux-android` (maturin + the NDK's clang wrappers); `android/tools/build-pydantic-core.sh`
  was generalised with an `ARCH`/`PY_VERSION` switch rather than written as a second parallel script.
- fastapi/starlette/uvicorn/h11/websockets/httpx/python-multipart/tzdata are pure Python and unaffected by the ABI
  or the 3.11-vs-3.13 choice.

## Decision

Add a `wear` product flavor to the existing `:app` module (not a separate `:wear` module — see **Consequences**):

- `minSdk 30` (Wear OS 3), `abiFilters = armeabi-v7a, arm64-v8a`, one universal APK (not split per ABI).
- Chaquopy per-flavor override: `version = "3.11"` (the phone flavor keeps `3.13`, untouched), its own `pip` block
  pinning `pillow==9.2.0` for this flavor only and two pydantic-core wheels (`armeabi_v7a`, `arm64_v8a`, cp311).
- `src/wear/AndroidManifest.xml` overlay: `<uses-feature android:name="android.hardware.type.watch"/>` and
  `com.google.android.wearable.standalone = true`.
- `src/wear/java/com/deskdot/app/MainActivity.kt` replaces the phone's activity with a minimal round-safe
  placeholder screen; `EngineService`, `BleBridge`, `BootReceiver` are unchanged and shared between flavors.
- `src/deskdot/casino/fair.py`: `def verify[T](` → `def verify(` (PEP 695 syntax only; `TypeVar` import already
  present). `pyproject.toml`: `requires-python = ">=3.11,<3.14"`.
- **Network: identical to the phone, not locked down.** The owner's instruction: the watch is a primary host, so
  `lan_studio`, the studio being reachable on the Wi-Fi, and multiplayer controllers joining `/p/<code>` must work
  exactly as they do on the phone — `android_main.py`'s host/port/`lan_studio` handling is untouched. The one
  Wear-specific addition is `EngineService.requestWifiNetwork()` (gated by a new `R.bool.is_watch` resource, `false`
  on `mobile`/`true` on `wear`): Wear OS routes IP traffic over a Bluetooth proxy to the paired phone once the
  screen sleeps, which would silently break LAN hosting even with the panel still connected over BLE. It requests
  a `TRANSPORT_WIFI` network and binds the process to it, on top of the existing (shared) `WifiLock`.

## Consequences

+ No engine feature is cut, no app behaviour changes, to satisfy the 32-bit requirement — the concessions are a
  syntax rewrite (zero behaviour change) and two dependency versions (numpy/psutil identical to the phone; Pillow
  one minor-ish version back, API-complete for every call site DeskDot has).
+ The phone (`mobile`) flavor is untouched: same `minSdk`, same ABI, same Python 3.13, same pip versions, same
  `MainActivity.kt` (moved to `src/mobile/java/...` unchanged, not edited).
+ A single `:app` module with a flavor dimension, not a second `:wear` module: `EngineService`, `BleBridge`,
  `BleListener`, `BootReceiver` and the Chaquopy Python source-set wiring are 100% identical between the two
  targets — the only differences are the launcher activity, the manifest's watch feature/standalone flag, the
  Chaquopy Python version, and which wheels get installed. A second module would duplicate all of that for no
  behavioural gain and risk the two copies drifting.
− **The wear flavor does not yet produce an installable APK.** `android/tools/build-pydantic-core.sh` needs
  `rustup`, `cargo` and `maturin` on the build machine; none were available where this flavor was scaffolded, so
  the two cp311 pydantic-core wheels the `wear` flavor's `build.gradle.kts` references do not exist yet. This is
  the one concrete blocker before `./gradlew assembleWearDebug` succeeds — see android/README.md's Wear section.
− Memory (RSS) on the watch has not been measured — no installable APK exists yet, and the owner's rule ("the lead
  will do installs") kept this session from side-loading anything even if one did. `android_main.py`'s existing
  lazy imports (uvicorn/config/server inside `run()`, not at module import) and the wear activity's lazy WebView
  are the mitigations in place; they are design choices, not measurements, until the APK is built and run.
− The Wi-Fi-stays-up fix (`requestWifiNetwork`/`bindProcessToNetwork`) is based on Wear OS's documented radio
  behaviour, not verified on the actual watch — the same "no installable APK" limitation above applies.
− Two Chaquopy Python versions (3.13 phone, 3.11 wear) means two `buildPython*` entries in `local.properties` and
  two sets of vendored wheels to keep in sync whenever `pydantic`/`pydantic-core` is upgraded.

#!/usr/bin/env python3
"""Interactive CLI Transfer & Motion Calibration Test for DotDeck.

Tests the live hardware link against horizontal tearing, scanline slicing,
and multi-packet BLE buffer drops, and saves optimal transfer timings.
"""

from __future__ import annotations

import sys
import time

import httpx

API_BASE = "http://127.0.0.1:8765"


def main() -> None:
    print("\n" + "=" * 60)
    print("  DotDeck 32×32 Hardware Transfer & Motion Calibration Test")
    print("=" * 60)

    try:
        r = httpx.get(f"{API_BASE}/api/state", timeout=3.0)
        state = r.json()
    except Exception as e:
        print(f"\n[ERROR] Cannot connect to DotDeck server at {API_BASE}: {e}")
        print("Make sure DotDeck is running: 'uv run dotdeck serve'\n")
        sys.exit(1)

    dev = state.get("device", {})
    if dev.get("status") != "connected":
        print(f"\n[WARN] Panel status is '{dev.get('status')}'. Connect your panel first.")
        print(f"Address: {dev.get('address')}, Last error: {dev.get('last_error')}\n")
    else:
        print(f"\n[CONNECTED] Panel: {dev.get('name')} ({dev.get('address')})")
        print(f"MTU Write Size: {dev.get('mtu')} B  |  Measured Link FPS: {dev.get('link_fps')} FPS\n")

    steps = [
        {
            "pattern": "protocol_tear",
            "name": "Step 1: Motion Slicing & Tearing Test",
            "desc": "Displays high-contrast alternating vertical scanlines.",
            "q": "How does the vertical motion line look across the LEDs?",
            "choices": [
                ("Solid & Smooth (No split lines)", {"max_fps": 12.0, "packet_gap_ms": 18.0}),
                ("Occasional split / horizontal tear", {"max_fps": 9.0, "packet_gap_ms": 20.0}),
                ("Stuttering or jittery pause", {"max_fps": 8.0, "packet_gap_ms": 22.0}),
            ],
        },
        {
            "pattern": "protocol_stress",
            "name": "Step 2: Multi-Packet Buffer & Gap Test",
            "desc": "Displays a dense 32x32 gradient requiring 3 full BLE packets (>1200 bytes).",
            "q": "Does the multi-packet gradient display cleanly without flickering or black flashes?",
            "choices": [
                ("Clean & Solid (Fast 15ms gap)", {"packet_gap_ms": 15.0}),
                ("Stable with rare flicker (Balanced 18ms gap)", {"packet_gap_ms": 18.0}),
                ("Flickers or drops frames (Safe 25ms gap)", {"packet_gap_ms": 25.0}),
            ],
        },
        {
            "pattern": "protocol_cut",
            "name": "Step 3: App Transition & Glitch Prevention",
            "desc": "Displays clean-cut border card to verify zero block noise during app switches.",
            "q": "How should app switching behave?",
            "choices": [
                ("Instant Clean Cut (Recommended - Zero Glitches)", {"transition": "cut"}),
                ("Fade Through Black", {"transition": "fade"}),
            ],
        },
    ]

    calibrated = {
        "max_fps": 12.0,
        "packet_gap_ms": 18.0,
        "transition": "cut",
    }

    try:
        for idx, s in enumerate(steps, 1):
            print("-" * 60)
            print(f"[{idx}/3] {s['name']}")
            print(f"     {s['desc']}")
            print("     --> Displaying test pattern on physical panel now...")

            # Push pattern
            httpx.post(f"{API_BASE}/api/calibration/pattern/{s['pattern']}", timeout=5.0)
            time.sleep(1.0)

            print(f"\n{s['q']}")
            for c_idx, (label, _) in enumerate(s["choices"], 1):
                print(f"  [{c_idx}] {label}")

            choice = 1
            try:
                raw = input("\nSelect [1-3] (default 1): ").strip()
                if raw in ("1", "2", "3"):
                    choice = int(raw)
            except (KeyboardInterrupt, EOFError):
                break

            chosen_params = s["choices"][choice - 1][1]
            calibrated.update(chosen_params)
            print(f"Selected: {s['choices'][choice - 1][0]}")

        # Clear pattern
        httpx.delete(f"{API_BASE}/api/calibration/pattern", timeout=5.0)

        print("\n" + "=" * 60)
        print("  Applying Calibrated Settings to Hardware Engine...")
        print("=" * 60)
        print(f"  • Max Streaming Refresh Rate : {calibrated['max_fps']} Hz")
        print(f"  • Inter-Packet Pacing Gap    : {calibrated['packet_gap_ms']} ms")
        print(f"  • Transition Handoff         : {calibrated['transition']}")

        res = httpx.post(f"{API_BASE}/api/calibration/transfer/apply", json=calibrated, timeout=5.0)
        if res.status_code == 200:
            print("\n[SUCCESS] Calibration saved and applied live to your panel!\n")
        else:
            print(f"\n[ERROR] Failed to save calibration: {res.text}\n")

    finally:
        try:
            httpx.delete(f"{API_BASE}/api/calibration/pattern", timeout=3.0)
        except Exception:
            pass


if __name__ == "__main__":
    main()

"""Display Test Suite — activates key apps on the physical display,
waits for BLE transmission/clip baking, captures webcam snapshots,
and records visual metrics.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
import httpx
import cv2

from camera_calibrate import capture_frame, save_snapshot, analyze_panel_image

BASE_URL = "http://127.0.0.1:8765"
OUTPUT_DIR = Path("data/display_tests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

APPS_TO_TEST = [
    ("pixabots", {"bot": "sparky", "accessory": "headphones", "color_scheme": "cyber"}),
    ("clock", {"layout": "bold", "seconds": True, "date": True}),
    ("weather", {"layout": "hero", "units": "c"}),
    ("ambient", {"effect": "aurora"}),
    ("sysmon", {"layout": "gauges"}),
    ("petworld", {"speed": 1}),
]


def test_app(app_id: str, settings: dict | None = None) -> Path:
    print(f"\n--- Testing App: {app_id} ---")
    if settings:
        print(f"Applying settings: {settings}")
        r = httpx.patch(f"{BASE_URL}/api/apps/{app_id}/settings", json=settings, timeout=5.0)
        print(f"Settings status: {r.status_code}")
    
    print(f"Activating app: {app_id}...")
    r = httpx.post(f"{BASE_URL}/api/apps/{app_id}/activate", timeout=5.0)
    print(f"Activate status: {r.status_code}")

    # Wait for baking + BLE transfer to settle
    print("Waiting 3.5s for display transfer...")
    time.sleep(3.5)

    print("Capturing webcam photo...")
    frame = capture_frame(0, warmup_frames=12)
    path = OUTPUT_DIR / f"{app_id}.jpg"
    save_snapshot(frame, path)
    metrics = analyze_panel_image(frame)
    print(f"Saved: {path} | Mean Lum: {metrics['mean_luminance']:.1f} | Glare/Clipping: {metrics['clipping_ratio']*100:.2f}%")
    return path


def main():
    results = {}
    for app_id, settings in APPS_TO_TEST:
        try:
            path = test_app(app_id, settings)
            results[app_id] = path
        except Exception as e:
            print(f"Error testing {app_id}: {e}")

    print("\nAll display tests finished! Saved files:")
    for app, path in results.items():
        print(f"  {app}: {path}")


if __name__ == "__main__":
    main()

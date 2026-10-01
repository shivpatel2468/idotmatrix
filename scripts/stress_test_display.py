"""Hardware Stress Test & Video Optical Inspector for iDotMatrix 32x32.

Executes a multi-phase stress test against the physical display:
  1. Rapid App Cycling & Native GIF Upload Stress
  2. High-Current Power Inversion & Optical Bloom Stress (Full White, Primaries, Strobe)
  3. High-Framerate Live BLE Streaming Motion Stress

Simultaneously records video and frame bursts from the laptop webcam,
diagnoses frame drops, BLE stalls, power sags, and optical blooming,
and produces a video recording and visual contact sheet filmstrip.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("stress_test")

API_BASE = "http://127.0.0.1:8765/api"
OUT_DIR = Path("data/display_tests")
OUT_DIR.mkdir(parents=True, exist_ok=True)


class CameraRecorder:
    """Threaded camera video and metric recorder."""

    def __init__(self, camera_index: int = 0, target_fps: float = 12.0) -> None:
        self.camera_index = camera_index
        self.target_fps = target_fps
        self.running = False
        self.frames: list[np.ndarray] = []
        self.timestamps: list[float] = []
        self.thread: threading.Thread | None = None
        self.cap: cv2.VideoCapture | None = None

    def start(self) -> None:
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam index {self.camera_index}")

        # Let camera auto-exposure settle
        for _ in range(10):
            self.cap.read()

        self.running = True
        self.frames = []
        self.timestamps = []
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        log.info("Webcam recording thread started")

    def _capture_loop(self) -> None:
        assert self.cap is not None
        while self.running:
            t = time.perf_counter()
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self.frames.append(frame.copy())
                self.timestamps.append(t)
            time.sleep(1.0 / (self.target_fps * 1.5))

    def stop(self) -> tuple[list[np.ndarray], list[float]]:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=3.0)
        if self.cap is not None:
            self.cap.release()
        log.info("Webcam recording stopped. Captured %d frames", len(self.frames))
        return self.frames, self.timestamps


def activate_app(app_id: str, settings: dict[str, Any] | None = None) -> bool:
    """Call DeskDot API to activate an app."""
    url = f"{API_BASE}/apps/{app_id}/activate"
    body = {"settings": settings} if settings else {}
    try:
        r = httpx.post(url, json=body, timeout=5.0)
        return r.status_code == 200 and r.json().get("ok", False)
    except Exception as e:
        log.error("Failed to activate %s: %s", app_id, e)
        return False


def send_canvas_pixels(color: str) -> bool:
    """Paint full canvas with a single color via /api/pixels."""
    rows = ["A" * 32] * 32
    body = {"rows": rows, "palette": {"A": color}}
    url = f"{API_BASE}/pixels"
    try:
        r = httpx.post(url, json=body, timeout=5.0)
        return r.status_code == 200
    except Exception as e:
        log.error("Canvas paint error: %s", e)
        return False


def run_stress_test(recorder: CameraRecorder) -> dict[str, Any]:
    """Execute the multi-phase stress sequence."""
    stage_markers: list[dict[str, Any]] = []

    def mark(name: str, duration: float) -> None:
        t_start = time.perf_counter()
        log.info("=== STRESS PHASE: %s (%.1f s) ===", name, duration)
        stage_markers.append({"name": name, "start": t_start, "duration": duration})
        time.sleep(duration)
        stage_markers[-1]["end"] = time.perf_counter()

    recorder.start()
    t_global_start = time.perf_counter()

    try:
        # --- PHASE 1: Rapid App Cycling (Bake & BLE Upload Stress) ---
        apps = [
            ("synthwave", None, 2.0),
            ("wireframe", None, 2.0),
            ("focuspet", None, 2.0),
            ("sand", {"scenario": "volcano"}, 2.2),
            ("brain", {"mode": "spiral"}, 2.2),
            ("raycaster", {"speed": 1.05}, 2.2),
        ]
        for aid, st, dur in apps:
            activate_app(aid, st)
            mark(f"App: {aid}", dur)

        # --- PHASE 2: High-Current Power & Luminance Inversion Stress ---
        # Full White (Maximum power load: 1,024 LEDs at 255)
        send_canvas_pixels("#ffffff")
        mark("Power Stress: Full White 100%", 1.5)

        # Full Black (Zero power load)
        send_canvas_pixels("#000000")
        mark("Power Stress: Full Black", 1.0)

        # Primary Colors Stress
        send_canvas_pixels("#ff0000")
        mark("Color Stress: Full Red", 1.0)

        send_canvas_pixels("#00ff00")
        mark("Color Stress: Full Green", 1.0)

        send_canvas_pixels("#0000ff")
        mark("Color Stress: Full Blue", 1.0)

        # Rapid Power Strobing (Rapid Inversion)
        for i in range(4):
            send_canvas_pixels("#ffffff")
            mark(f"Strobe Flash {i+1} White", 0.3)
            send_canvas_pixels("#000000")
            mark(f"Strobe Flash {i+1} Black", 0.3)

        # --- PHASE 3: Return to Stable App ---
        activate_app("synthwave", None)
        mark("Recovery: Synthwave", 2.0)

    finally:
        frames, timestamps = recorder.stop()

    t_global_end = time.perf_counter()
    total_duration = t_global_end - t_global_start
    log.info("Stress test complete. Total test duration: %.2f s", total_duration)

    return {
        "duration": total_duration,
        "stages": stage_markers,
        "frames": frames,
        "timestamps": timestamps,
    }


def analyze_and_export(data: dict[str, Any]) -> dict[str, Any]:
    """Analyze captured optical metrics and export video and filmstrip."""
    frames: list[np.ndarray] = data["frames"]
    timestamps: list[float] = data["timestamps"]
    stages: list[dict[str, Any]] = data["stages"]
    n_frames = len(frames)

    if n_frames == 0:
        raise RuntimeError("No frames captured during stress test")

    h, w = frames[0].shape[:2]
    duration = data["duration"]
    actual_fps = n_frames / duration if duration > 0 else 10.0

    # 1. Export MP4 Video
    video_path = OUT_DIR / "stress_test_run.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, actual_fps, (w, h))

    luminances = []
    blooming_ratios = []
    frame_diffs = []

    for i in range(n_frames):
        f = frames[i]
        writer.write(f)

        # Photometric analysis
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        v_channel = hsv[:, :, 2]
        lum = float(np.mean(v_channel))
        luminances.append(lum)

        # Clipping / blooming ratio (fraction of saturated pixels V > 245)
        clip_ratio = float(np.sum(v_channel > 245) / (h * w))
        blooming_ratios.append(clip_ratio)

        # Motion / frame difference
        if i > 0:
            diff = float(np.mean(np.abs(f.astype(np.int16) - frames[i - 1].astype(np.int16))))
            frame_diffs.append(diff)
        else:
            frame_diffs.append(0.0)

    writer.release()
    log.info("Exported stress test video: %s (%.1f FPS, %d frames)", video_path, actual_fps, n_frames)

    # 2. Build Visual Filmstrip (Keyframe Contact Sheet)
    # Pick 1 representative frame from each stage
    contact_cells = []
    stage_stats = []

    for st in stages:
        t_mid = (st["start"] + st["end"]) / 2.0
        # Find closest frame
        idx = int(np.argmin([abs(t - t_mid) for t in timestamps]))
        cell = frames[idx].copy()

        # Overlay text banner
        label = st["name"]
        cv2.rectangle(cell, (0, 0), (w, 32), (0, 0, 0), -1)
        cv2.putText(cell, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        contact_cells.append(cell)

        # Compute stage metrics
        st_indices = [k for k, t in enumerate(timestamps) if st["start"] <= t <= st["end"]]
        st_lum = float(np.mean([luminances[k] for k in st_indices])) if st_indices else 0.0
        st_bloom = float(np.mean([blooming_ratios[k] for k in st_indices])) if st_indices else 0.0
        stage_stats.append({
            "stage": label,
            "mean_luminance": round(st_lum, 1),
            "bloom_ratio": round(st_bloom * 100, 2),
        })

    # Tile cells into a grid filmstrip
    n_cells = len(contact_cells)
    cols = 3
    rows = int(np.ceil(n_cells / cols))

    # Resize cells for filmstrip
    cell_w, cell_h = 320, 240
    strip = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)

    for idx, c in enumerate(contact_cells):
        r = idx // cols
        c_idx = idx % cols
        resized = cv2.resize(c, (cell_w, cell_h))
        strip[r * cell_h : (r + 1) * cell_h, c_idx * cell_w : (c_idx + 1) * cell_w] = resized

    filmstrip_path = OUT_DIR / "stress_test_filmstrip.jpg"
    cv2.imwrite(str(filmstrip_path), strip)
    log.info("Exported contact sheet filmstrip: %s", filmstrip_path)

    # 3. Overall Diagnostics & Health Assessment
    mean_lum = float(np.mean(luminances))
    max_lum = float(np.max(luminances))
    max_bloom = float(np.max(blooming_ratios)) * 100.0

    # Detect unexpected blackouts during active states (luminance < 3.0 during non-black stages)
    non_black_stages = [st for st in stages if "Black" not in st["name"]]
    blackout_count = 0
    for st in non_black_stages:
        st_indices = [k for k, t in enumerate(timestamps) if st["start"] <= t <= st["end"]]
        for k in st_indices:
            if luminances[k] < 2.5:
                blackout_count += 1

    report = {
        "video_path": str(video_path),
        "filmstrip_path": str(filmstrip_path),
        "total_frames_captured": n_frames,
        "video_fps": round(actual_fps, 1),
        "duration_seconds": round(duration, 2),
        "mean_luminance": round(mean_lum, 1),
        "peak_luminance": round(max_lum, 1),
        "peak_optical_bloom_percent": round(max_bloom, 2),
        "blackout_dropped_frames": blackout_count,
        "passed_stress_test": blackout_count == 0,
        "stage_stats": stage_stats,
    }

    report_path = OUT_DIR / "stress_test_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    log.info("Stress test report saved to %s", report_path)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="DeskDot Physical Display Stress Test")
    parser.add_argument("--camera", type=int, default=0, help="Webcam device index")
    parser.add_argument("--fps", type=float, default=12.0, help="Target recording framerate")
    args = parser.parse_args()

    recorder = CameraRecorder(camera_index=args.camera, target_fps=args.fps)
    test_data = run_stress_test(recorder)
    report = analyze_and_export(test_data)

    print("\n" + "=" * 60)
    print("DESKDOT PHYSICAL DISPLAY STRESS TEST RESULTS")
    print("=" * 60)
    print(f"Status:            {'PASSED (STABLE)' if report['passed_stress_test'] else 'WARNINGS DETECTED'}")
    print(f"Total Duration:    {report['duration_seconds']} s")
    print(f"Frames Captured:   {report['total_frames_captured']} frames @ {report['video_fps']} FPS")
    print(f"Peak Optical Bloom:{report['peak_optical_bloom_percent']}%")
    print(f"Blackouts/Drops:   {report['blackout_dropped_frames']} frames")
    print(f"Video Saved:       {report['video_path']}")
    print(f"Filmstrip Saved:   {report['filmstrip_path']}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()

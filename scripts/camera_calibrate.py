"""Camera Calibrator — capture the physical iDotMatrix panel via the laptop webcam,
inspect colors and glare, and optimize display calibration.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SNAPSHOT_PATH = Path("data/camera_snapshot.jpg")


def capture_frame(camera_index: int = 0, warmup_frames: int = 15) -> np.ndarray:
    """Capture a stabilized frame from the webcam."""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open webcam index {camera_index}")

    try:
        # Let auto-exposure and auto-white-balance settle
        frame = None
        for _ in range(warmup_frames):
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.05)

        if frame is None or not ret:
            raise RuntimeError("Failed to capture frame from webcam")
        return frame
    finally:
        cap.release()


def save_snapshot(frame: np.ndarray, path: Path = SNAPSHOT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)
    return path.resolve()


def analyze_panel_image(frame: np.ndarray) -> dict[str, float]:
    """Analyze overall lighting, glare, and color balance."""
    # Convert BGR to RGB
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    mean_rgb = rgb.mean(axis=(0, 1))
    max_lum = float(hsv[:, :, 2].max())
    mean_lum = float(hsv[:, :, 2].mean())

    # Detect high-glare/clipping pixels (V > 245)
    clipping_ratio = float((hsv[:, :, 2] > 245).sum() / (frame.shape[0] * frame.shape[1]))

    return {
        "mean_red": float(mean_rgb[0]),
        "mean_green": float(mean_rgb[1]),
        "mean_blue": float(mean_rgb[2]),
        "max_luminance": max_lum,
        "mean_luminance": mean_lum,
        "clipping_ratio": clipping_ratio,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture laptop webcam snapshot of the iDotMatrix panel.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--out", type=str, default=str(SNAPSHOT_PATH), help="Output image file path")
    args = parser.parse_args()

    out_path = Path(args.out)
    print(f"Connecting to webcam index {args.camera}...")
    frame = capture_frame(args.camera)
    saved = save_snapshot(frame, out_path)
    stats = analyze_panel_image(frame)

    print(f"Snapshot saved to: {saved}")
    print(f"Image dimensions: {frame.shape[1]}x{frame.shape[0]}")
    print(f"Luminance - Mean: {stats['mean_luminance']:.1f}, Max: {stats['max_luminance']:.1f}")
    print(f"Color distribution (RGB): R={stats['mean_red']:.1f}, G={stats['mean_green']:.1f}, B={stats['mean_blue']:.1f}")
    if stats["clipping_ratio"] > 0.05:
        print("Note: High glare/clipping detected in frame.")


if __name__ == "__main__":
    main()

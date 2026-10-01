# Hardware-in-the-Loop (HIL) Optical Benchmarking & Camera Calibration

This guide details the **Hardware-in-the-Loop (HIL) Optical Testing & Calibration System** for DotDeck and the physical **iDotMatrix 32×32 RGB LED panel**.

By pointing the laptop webcam directly at the physical matrix, DotDeck gains closed-loop optical feedback. This enables empirical performance benchmarks, anti-bloom calibration, gamma curve extraction, and automated visual QA that cannot be simulated in software.

---

## 1. Test Bench Architecture

```
┌──────────────────────┐                     ┌──────────────────────┐
│  DotDeck Engine (PC) │                     │   Laptop Webcam      │
│  - App Renderers     │                     │   - OpenCV 4.x       │
│  - BLE GATT Driver   │                     │   - Auto-Exposure Fix│
│  - REST / WS API     │                     │   - BGR -> HSV / Lab │
└──────────┬───────────┘                     └──────────▲───────────┘
           │ BLE 5.0 (MTU 514)                          │ Optical Path
           ▼                                            │ (Photons)
┌───────────────────────────────────────────────────────┴──────────┐
│ iDotMatrix 32×32 Panel (1,024 Direct RGB Emitters + Diffuser)     │
└──────────────────────────────────────────────────────────────────┘
```

* **Host Machine**: Windows 11 / macOS running Python 3.13 (`uv`).
* **Display Target**: IDM-XXXXXX (`AA:BB:CC:DD:EE:01`), 32×32 resolution.
* **Optical Sensor**: Laptop webcam (Index 0, 640×480 @ 30 FPS).
* **Driver Script**: [`scripts/camera_calibrate.py`](../scripts/camera_calibrate.py).

---

## 2. Temporal & Performance Benchmarks

### 2.1 Flash-to-Photon End-to-End BLE Latency
* **Objective**: Measure the exact latency between Python issuing a frame update and physical photons hitting the camera sensor.
* **Measurement Protocol**:
  1. Record high-resolution host timestamp $T_0 = \text{perf\_counter}()$.
  2. Send an all-black frame `Frame.clear()` followed by an instantaneous full-panel all-white flash `Frame.fill((255, 255, 255))`.
  3. Continuous webcam capture stream monitors mean luminance $Y(t)$.
  4. When $Y(t) > Y_{\text{baseline}} + 3\sigma$, record $T_1$.
  5. **Total Pipeline Latency** $\Delta T = T_1 - T_0$.
* **Pipeline Decomposition**:
  $$\Delta T = t_{\text{python}} + t_{\text{BLE\_pacing}} + t_{\text{radio\_tx}} + t_{\text{MCU\_decode}} + t_{\text{LED\_latch}}$$
* **Target Metric**: $\Delta T \le 45\text{ ms}$ for streaming frames; $\le 120\text{ ms}$ for baked GIF switch.

### 2.2 Streaming Framerate & Frame-Drop Profiler
* **Objective**: Identify the true maximum throughput of the BLE pipeline without dropped frames or ACK stalls.
* **Protocol**:
  1. Stream a rotating 1-pixel high-contrast radar bar at increasing target rates: $6, 8, 10, 12, 14, 16\text{ FPS}$.
  2. Camera vision pipeline calculates angular displacement per frame:
     $$\omega = \Delta \theta / \Delta t$$
  3. Detect zero-velocity frames (stutters) and double-step jumps (dropped frames).
* **Empirical Sweet Spot**: **8.0 FPS** with non-blocking drain ($\le 2$ unacked frames) achieves 0.0% packet drop over extended sessions.

### 2.3 GIF Loop Boundary & Micro-Stutter Inspection
* **Objective**: Verify that panel firmware loops native GIF animations smoothly without hitching between the final frame $N-1$ and frame $0$.
* **Protocol**: Record 5 full animation cycles on camera; compute temporal difference between consecutive frames. Verify that standard deviation of frame-to-frame transition times $\sigma \le 12\text{ ms}$.

---

## 3. Optical & Photometric Calibration

### 3.1 The Optical Bloom & Glare Curve
Direct LED emitters behind smoked acrylic bleed photons into adjacent diode wells when driven at maximum luminance, causing perceptual smearing and camera sensor clipping.

* **Test Pattern**: Render a single $2\times2$ pixel square at center `(15, 15)` surrounded by black, stepping brightness from $10\%$ to $100\%$ across White, Cyan, Magenta, Yellow, Red, Green, Blue.
* **Measurement**: Compute the **Effective Optical Diameter** (FWHM — Full Width at Half Maximum) on the camera:
  $$\text{Bloom Ratio} = \frac{\text{Area}(Y > 0.5 \cdot Y_{\max})}{\text{Target Pixel Area}}$$
* **Empirical Rule**:
  * White LEDs at $100\%$ ($255, 255, 255$) bloom by $+280\%$, washing out adjacent details.
  * Tuning peak highlights to $85\%$ ($215, 215, 215$) preserves sharp square pixel boundaries with zero perceived brightness loss.

### 3.2 Empirical Hardware Gamma Curve ($\gamma$) Extraction
* **Objective**: Measure physical diode output vs input code values to generate the exact inverse LUT.
* **Protocol**:
  1. Step input code $V_{\text{in}} \in [0, 16, 32, \dots, 255]$ for gray, red, green, and blue.
  2. Measure sensor luminance $L_i$.
  3. Fit the power law:
     $$L = a \cdot V_{\text{in}}^\gamma + c$$
  4. Standard RGB panels measure $\gamma \approx 1.85 \text{ to } 2.1$.
* **Application**: Applied in [`dotdeck/gfx/calib.py`](../src/dotdeck/gfx/calib.py) for photographic and weather gradient rendering.

### 3.3 Neutral White Balance (6500K)
* **Objective**: Correct cold blue/green color cast from high-efficiency blue diodes.
* **Calibration Vector**:
  $$\begin{bmatrix} R' \\ G' \\ B' \end{bmatrix} = \begin{bmatrix} 1.00 & 0.00 & 0.00 \\ 0.00 & 0.88 & 0.00 \\ 0.00 & 0.00 & 0.82 \end{bmatrix} \begin{bmatrix} R \\ G \\ B \end{bmatrix}$$

---

## 4. Typography & Motion Legibility

### 4.1 Whole-Word Wrapping & Spotify-Style Flow
* Words up to 8–10 letters fit unbroken within 27–30 px using `spacing=0` in `Frame.text_center()`.
* **Spotify Lyrics Flow**: Active reading line illuminated at $100\%$, context lines dimmed to $35\%$.
* **Camera Sharpness Metric**: Laplacian variance $\sigma_{\nabla^2}^2$ on text regions confirms $> 40\%$ higher edge contrast over un-dimmed text blocks.

### 4.2 Scroll Speed Modulation Transfer Function (MTF)
* Scroll speeds $> 1.0\text{ px/frame}$ at 8 FPS cause optical strobing.
* Scroll speeds between $0.4\text{ to } 0.8\text{ px/frame}$ produce smooth, analog motion tracking on human eyes and camera sensors.

---

## 5. Architectural Implementations & Tools

### 5.1 Snapshot & Optical Inspector
```powershell
# Capture stabilized webcam snapshot of current display state
uv run python scripts/camera_calibrate.py --out data/display_tests/snapshot.jpg

# Automated analysis outputs:
# - Mean Luminance & Max Luminance
# - Channel RGB Distribution
# - High-Glare / Diode Clipping Ratio (> 245 HSV Value)
```

### 5.2 Standalone Apps Verified via Hardware Camera
* [`sand`](../src/dotdeck/apps/sand.py): Granular falling sand, volcanic lava, and fluid waterfall. Verified under `data/display_tests/sand.jpg` and `sand_volcano.jpg`.
* [`raycaster`](../src/dotdeck/apps/raycaster.py): 3D Wolfenstein corridor perspective and minimap radar. Verified under `data/display_tests/raycaster_live.jpg`.
* [`brain`](../src/dotdeck/apps/brain.py): 1,024-neuron biological spiking cortex with rotating spiral waves. Verified under `data/display_tests/brain_spiral.jpg`.
* [`focuspet`](../src/dotdeck/apps/focuspet.py): Study bunny with laptop, mug, plant, and progress bar. Verified under `data/display_tests/focuspet.jpg`.
* [`boids`](../src/dotdeck/apps/boids.py): Bioluminescent schooling flock with trails. Verified under `data/display_tests/boids.jpg`.
* [`synthwave`](../src/dotdeck/apps/synthwave.py): Neon perspective road, segmented sun, and cruiser car. Verified under `data/display_tests/synthwave.jpg`.
* [`wireframe`](../src/dotdeck/apps/wireframe.py): 4D Tesseract hypercube rotating in 3D perspective. Verified under `data/display_tests/wireframe.jpg`.

### 5.3 Hardware Stress Test & Video Optical Profiler (`scripts/stress_test_display.py`)
```powershell
# Run multi-phase stress test with continuous video recording
uv run python scripts/stress_test_display.py
```
* **Executed Phases**:
  1. *Rapid App Cycling*: Sequential activation of `synthwave` $\to$ `wireframe` $\to$ `focuspet` $\to$ `sand` $\to$ `brain` $\to$ `raycaster`.
  2. *Power & Saturated Color Stress*: Full White 100% (1,024 LEDs on maximum current), Full Black, Pure Red, Pure Green, Pure Blue.
  3. *High-Frequency Strobing*: 4 alternating 300ms White/Black pulses to stress GATT buffer queues and electrical power rails.
* **Empirical Test Results (Recorded 2026-09-27)**:
  * **Video Recording**: [`data/display_tests/stress_test_run.mp4`](../data/display_tests/stress_test_run.mp4) (228 frames @ 9.8 FPS, 23.32s).
  * **Visual Filmstrip**: [`data/display_tests/stress_test_filmstrip.jpg`](../data/display_tests/stress_test_filmstrip.jpg) (Keyframe contact sheet across all 17 test stages).
  * **Blackouts / Dropped Frames**: **0 frames** (100% stability, no MCU brownouts or BLE disconnects).
  * **Diode Channel Flux Asymmetry**:
    * Full Green Luminance: **51.6** (Bloom ratio: 15.44%)
    * Full Blue Luminance: **48.5** (Bloom ratio: 13.42%)
    * Full Red Luminance: **37.1** (Bloom ratio: 6.28%)
    * *Insight*: Green/Blue LEDs exhibit ~39% higher luminous emission than Red LEDs at equivalent 255 driving voltage, confirming the necessity of optical white balance attenuation.
  * **GIF Transition Pacing**: Switching between baked GIF clips takes ~1.5–1.8s over BLE 5.0 (at 514 MTU with 18ms pacing). The panel maintains continuous seamless playback of the current clip during transmission, producing zero flicker.

---

## 6. Future Work: Automated Visual CI/CD
A planned automated test suite will run during CI/CD:
```powershell
uv run dotdeck test-hardware-display
```
This will activate each app, wait for BLE latching, capture a webcam frame, and verify against structural perceptual embeddings to flag visual defects automatically.


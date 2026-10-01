# DeskDot Inspiration, Technical Specifications & Reference Guide

This document is the **central knowledge repository** of reference links, technical specifications, and architectural insights for DeskDot and the **iDotMatrix 32×32 RGB LED panel**.

Every agent developing new features, apps, tools, or graphical effects must consult this document to maintain consistency with the hardware physics, design standards, and proven community solutions.

---

## 1. External Inspirations & Repository Reference

### 1.1 Pablo Stanley's Pixabots
- **Repository**: [`pablostanley/pixabots`](https://github.com/pablostanley/pixabots)
- **Live Demo**: [https://app-pablostanley.vercel.app](https://app-pablostanley.vercel.app)
- **License**: MIT
- **Key Concepts & Value**:
  - **Native 32×32 Sprites**: Handcrafted specifically for a 32×32 pixel grid with strict non-antialiased aesthetics (`image-rendering: pixelated`).
  - **4-Layer Modular Compositor**: Character parts are split into `body`, `heads`, `eyes`, and `top` (hats/antennas), producing **10,752 unique combinations**.
  - **Deterministic Base36 ID System**: 4-character ID (e.g. `a3f9`) uniquely and reversibly generates a distinct character.
  - **16-Tick Super-Loop Animation**: 8-frame bounce schedule at ~72–125 ms per frame with sub-pixel and integer layer Y-offsets, plus synchronized blink schedules.
- **Application to DeskDot**: Used as the foundation for the `pixabots` desktop companion app, asset layers for Canvas, and few-shot exemplars for the Gemini AI Studio.

### 1.2 Kully's Pixel Paint
- **Repository**: [`Kully/pixel-paint`](https://github.com/Kully/pixel-paint)
- **Live Demo**: [https://kully.github.io/pixel-paint/](https://kully.github.io/pixel-paint/)
- **License**: MIT
- **Key Concepts & Value**:
  - **32×32 Specialized Canvas**: Web-based drawing tool specifically constrained to 32×32 sprite dimensions.
  - **Ergonomic Keyboard Shortcuts**: `P` (Pencil), `B` (Bucket / Flood fill), `E` (Eraser), `V` (Eyedropper / Color picker), `G` (Grid toggle), `Z` (Undo), `X` (Redo), `C` (Color swap), `S` (Selection).
  - **Selection & Transform Tool**: Rectangular selection, delete area, move/nudge, and copy area (Alt+drag).
  - **Retro Palette Sets**: NES, PICO-8, GameBoy, and Commodore 64 color ramps.
- **Application to DeskDot**: Directly informs the keyboard ergonomics, undo/redo history stack, and selection/nudge features of the DeskDot web Canvas painter.

### 1.3 Adafruit 32×32 Square Pixel Art Display
- **Guide**: [Adafruit Learning System: 32x32 Square Pixel Art Animation Display](https://learn.adafruit.com/32x32-square-pixel-display/overview)
- **Authors**: Ruiz Brothers (Adafruit)
- **Key Concepts & Value**:
  - **Black Tinted LED Acrylic (Product #4594)**: 2.6 mm smoked cast acrylic placed in front of RGB LEDs absorbs ambient room light, increases contrast by 300%, eliminates PCB glare, and renders inky true blacks.
  - **3D Printed Baffle Grid (`grid.stl`)**: A physical honeycomb spacer between the LED PCB and the acrylic that encloses each 5050/3528 LED in its own chamber, preventing light bleed into adjacent pixels.
  - **3D CAD Enclosure Files**: Open-source STL, STEP, and Fusion 360 models for 32×32 matrix desk stands and frames.
  - **Vertical Sprite Sheet Bitmaps**: Vertical 32×(32×N) sprite sheets (e.g. `parrot-vertical.bmp`, `nyancat-vertical.bmp`).
- **Application to DeskDot**: Provides classic 32×32 meme animations (Party Parrot, Nyan Cat), physical enclosure references, and the gold-standard optical diffusion technique.

### 1.4 Henner Zeller's HUB75 LED Driver
- **Repository**: [`hzeller/rpi-rgb-led-matrix`](https://github.com/hzeller/rpi-rgb-led-matrix)
- **Key Concepts & Value**:
  - **1-Bit Bitmap BDF Font Library**: Handcrafted low-resolution bitmap fonts in `fonts/` (`4x6.bdf`, `5x7.bdf`, `6x10.bdf`, `tom-thumb`, etc.) designed for legibility at low pixel densities.
  - **Perceptual Color Science**: CIE 1931 luminance curve ($L^* \to Y$) and non-linear gamma curves for human eye perception on direct LED emitters.
  - **Architectural Reference**: Hardware driver model for raw HUB75 panels if DeskDot is ever ported to run directly on Raspberry Pi GPIO.

### 1.5 Note on Non-Display Repositories (Disambiguation)
- **`BMsemi/Neuromorphic_X1_32x32`**: A 32×32 analog 1T1R ReRAM in-memory compute (CIM) silicon macro for AI chip fabrication on silicon wafers. While non-display hardware, its concept of a 32×32 array of living synapses directly inspired DeskDot's `brain` app: a 1,024-neuron biological spiking neural network simulation running on the 32×32 LED grid.

### 1.6 Tidbyt Community & Pixlet Architecture
- **Repositories**: [`tidbyt/community`](https://github.com/tidbyt/community) and [`tidbyt/pixlet`](https://github.com/tidbyt/pixlet)
- **Key Concepts & Value**:
  - **Starlark Declarative Framework**: Deterministic app rendering without state accumulation between frames.
  - **Information Density & Micro-Layouts**: Maximizing legibility on 64×32 and 32×32 displays using minimalist 5px typography, high-contrast icons, and tight spacing.
  - **Community Integrations**: Public transit trackers, weather radar, sports ticker feeds, retro stock charts, and desk productivity timers.
- **Application to DeskDot**: Informing compact micro-HUD layouts, deterministic looping paradigms, and autonomous desktop utility apps.

### 1.7 SmartMatrix & Aurora Procedural Visuals
- **Repository**: [`pixelmatix/aurora`](https://github.com/pixelmatix/aurora) & [`pixelmatix/SmartMatrix`](https://github.com/pixelmatix/SmartMatrix)
- **Key Concepts & Value**:
  - **Gold-Standard 32×32 Generative Art**: Smooth trigonometric plasma waves, fluid dynamics, flow fields, and rotating 3D vector polyhedra.
  - **Palette Modulation**: Sine-based and color-ramp interpolation that creates rich, organic gradients without discrete banding.
- **Application to DeskDot**: Directly inspired the `wireframe` 3D vector engine, `synthwave` 3D horizon, and `ambient` light shows.

### 1.8 Granular Physics & Cellular Automata (Powder Toy / Sand)
- **Key Concepts & Value**:
  - **Multi-Element Interaction Rules**: Sand (density settling and 45° angle of repose), Water (horizontal leveling and fluid dispersion), Fire/Smoke (buoyant vertical rise and combustible ignition), Acid (caustic erosion and bubbling dissipation), and Lava (viscous flow and stone quenching).
  - **Sub-Millisecond 32×32 CA Simulation**: Deterministic limit cycles precomputed and cached into native hardware GIFs.
- **Application to DeskDot**: Powers the `sand` app with five distinct interactive scenarios (Hourglass, Volcano, Oasis, Acid Lab, Elemental Crucible).

### 1.9 3D DDA Raycasting on LED Matrices
- **Key Concepts & Value**:
  - **1:1 Column Ray Mapping**: Exactly 32 vertical ray columns cast across a 60° field of view directly map to the 32 physical pixel columns of the matrix.
  - **Distance Attenuation & Directional Shading**: Classic Wolfenstein 3D lighting (darkening distant surfaces and shading X vs Y wall normals) creates striking stereoscopic depth on an LED panel.
- **Application to DeskDot**: Built into the `raycaster` app with autonomous AI waypoint exploration, torch flicker, and minimap radar HUD.

### 1.10 Craig Reynolds Boids Flocking & Bioluminescent Particle Swarms
- **Key Concepts & Value**:
  - **Emergent Biological Movement**: Separation, Alignment, and Cohesion forces calculated across 20–30 agents with toroidal wrapping.
  - **Predator Evasion**: Apex predator pursuit inducing dramatic flock scattering and evasive ripples.
- **Application to DeskDot**: Built into the `boids` app with bioluminescent trails for deep sea schools, starling murmurations, and summer fireflies.

---

## 2. Hardware & Link Technical Specifications

| Parameter | Specification | Notes / Constraint |
| :--- | :--- | :--- |
| **Model** | iDotMatrix 32×32 RGB LED Panel | Advertises as IDM-XXXXXX |
| **MAC Address** | `AA:BB:CC:DD:EE:01` | Pinned in `state.json` / config |
| **Resolution** | 32 × 32 pixels | Exact: 1,024 physical RGB LEDs |
| **Origin** | Top-left `(0, 0)` | Bottom-right `(31, 31)` |
| **Transport** | Bluetooth Low Energy (BLE 5.0) | Central: Windows 11 / macOS Apple Silicon (M1+) |
| **Write Characteristic** | `0000fa02-0000-1000-8000-00805f9b34fb` | Write without response (paced) |
| **Ack / Notify Characteristic**| `0000fa03-0000-1000-8000-00805f9b34fb` | Subscribed on connect; flow control |
| **MTU** | 514 bytes payload (517 total) | Negotiated on connection |
| **Packet Pacing (`packet_gap`)**| 18 ms (`0.018s`) | Minimum gap between chunks to prevent firmware drops |
| **Streaming Frame Pipeline** | Non-blocking drain, max 2 unacked | Sustains 10–12 FPS streaming without 200 ms ACK stalls |
| **GIF Budget** | $\le 40$ KB ($\le 40,960$ bytes) | Panel microcontroller decodes $\le 35$ KB smoothly; larger files stutter |
| **Target Loop Framerate** | **8.0 FPS (125 ms / frame)** | Verified hardware sweet spot (Protocol finding #13) |
| **Per-Frame Displacement** | $\le 0.8$ to $1.0$ px / frame | Displacements $> 1$ px/frame read as harsh judder on discrete physical LEDs |
| **Color Quantization** | Single shared palette (24–32 colors)| Prevents inter-frame color flicker (Protocol finding #4) |

---

## 3. DeskDot Software Architecture & Standards

### 3.1 App Engine (`src/deskdot/engine/`)
- **`render(f: Frame, t: float)`**: Pure, synchronous, and lightning-fast ($< 2$ ms). Never do I/O, network requests, or sleeps inside `render()`.
- **`kind()`**:
  - `"clip"`: Deterministic looping animations. Pre-baked to an optimized GIF via `encode_gif_budget()`, uploaded once over BLE, and played natively by the panel's internal microcontroller. **Link stays 100% idle.**
  - `"stream"`: Live data (clocks, audio visualizers, live scores). Frames streamed as compressed PNGs at throttled intervals ($\le 8$ FPS).
  - `"native"`: Firmware-level built-in clock/scoreboard modes.

### 3.2 Graphics Pipeline (`src/deskdot/gfx/`)
- **Typography**: 1-bit bitmap fonts only (`tiny` 5 px, `small` 7 px, `big` 10 px digits). Never use antialiased or TrueType text on a 32×32 matrix.
- **Color Calibration**: UI designs and pixel art use raw vibrant LED values. Photos/album art pass through `color.calibrate()` (gamma 1.5, white balance, black crush) to prevent washed-out diode glare.

### 3.3 Web Studio & AI Studio (`web/src/`)
- **React 18 + Vite + Tailwind CSS v4**.
- **Live LED Emulator (`LedPanel.tsx`)**: Recreates physical diode bloom, recessed off-pixels, and optical diffusion.
- **Gemini AI Studio (`AiCreator.tsx`)**: Directly connects to Google Gemini API with a domain-specific 32×32 prompt system to generate multi-frame animations and compiles them to native hardware GIFs.

### 3.4 Hardware-in-the-Loop (HIL) Optical Testing (`docs/CAMERA_HIL_TESTING.md`)
- **Webcam Closed-Loop Calibration**: Laptop webcam acts as an optical test bench via `scripts/camera_calibrate.py`.
- **Empirical Measurements**: Measures true flash-to-photon latency, BLE throughput / frame drop rates, optical bloom ratios, and empirical diode gamma curves. See [`docs/CAMERA_HIL_TESTING.md`](CAMERA_HIL_TESTING.md) for full test specifications.


# 🪰 The fruit-fly brain

DeskDot has a fruit-fly brain that watches the panel and plays. It's a **model of the fly's visual circuit**:
the pathway that the **FlyWire** whole-brain connectome maps neuron by neuron.

> In October 2024 the FlyWire consortium, a Princeton-led team whose AI reconstruction and 3D viewer were built
> with **Google Research**, published the first complete wiring diagram of an adult *Drosophila* brain in
> *Nature*: **139,255 neurons and about 54.5 million synapses**.
> ([flywire.ai](https://flywire.ai/) · [Nature 634 (8032)](https://www.nature.com/nature/volumes/634/issues/8032))

## Where you'll see it

| | |
| --- | --- |
| **Fly Brain** app | A fly lives in an arena that fills the panel. It hunts fruit and darts away when a swatter's shadow looms. The panel shows only its world. |
| **Every game** → *Plays itself with* → **Fruit-fly brain** | Instead of the built-in AI, the fly plays from pixels alone, through an eye centred on its own character. Press any key and you take over. |
| **The studio's 3D Fly view** | Opens by itself whenever a fly is playing: the side panels slide shut and the brain fills their space. **Left:** the circuit below as a 3D tower (eye → lamina → T4/T5 → HS/VS → LPLC2 → giant fibre → descending neurons → keys), with signal pulses and spikes. **Right:** a 3D fly on a keyboard. It hops onto each key its neurons press, leaps on the giant-fibre escape (key A), grooms when idle, and its compound eyes show the live eye image. A keystroke log and counts sit underneath. **Graphics** has quality presets (Auto adapts to your GPU), a frame-rate cap, bloom, particles, shadows, themes, cameras, fly looks and keyboard styles. Nothing of the brain is drawn on the panel. |

The studio reads the brain from `GET /api/fly` (≈12 times a second while a fly plays). It returns the 16×16 eye,
lamina ON/OFF and T4/T5 motion maps, HS/VS, looming, giant fibre, the descending neurons' potentials and the last
32 key presses.

## The circuit

```
panel pixels ─▶ eye (16×16 ommatidia, centred on the fly's body)
   ─▶ lamina L1 (ON) / L2 (OFF): brightening and dimming
   ─▶ T4 (ON) / T5 (OFF): Hassenstein–Reichardt motion detectors, four directions
   ─▶ lobula plate HS / VS: wide-field horizontal and vertical motion
   ─▶ LPLC2: looming (expansion around the centre) ─▶ giant fibre ─▶ escape (key A)
   ─▶ descending neurons (leaky integrate-and-fire): steer ← → ↑ ↓ ─▶ one spike = one key press
phototaxis (flies are drawn to light) ─▶ descending neurons
```

| Stage | What it does | In the code |
| --- | --- | --- |
| Eye | 16×16 ommatidia, each 2×2 panel pixels of luminance. When the game says where the fly's body is, the eye is re-centred on it. | `FlyBrain.see` |
| Lamina | Temporal contrast, split into ON (brightening) and OFF (dimming) channels | `step`: `on`, `off` |
| T4 / T5 | Elementary motion detectors: a delayed neighbour multiplied by the present signal, minus the mirror term | `emd()` |
| HS / VS | Rightward, leftward, upward and downward motion summed over the eye | `state.hs_*`, `state.vs_*` |
| LPLC2 → GF | Outward motion on all four sides = something coming at you; the giant fibre fires the escape | `state.looming`, `state.gf` |
| Phototaxis | Commit to the strongest nearby light and turn towards its direction | `state.light` |
| Descending neurons | Leaky integrate-and-fire with a refractory period. Opposite directions inhibit each other. | `state.dn`, `state.spikes` |

The tests check it against the classic experiments ([tests/test_fly.py](../tests/test_fly.py)):
- moving bars drive the matching HS cell and not the opposite one;
- an expanding square fires the giant fibre, and a still scene doesn't;
- a light on one side turns the fly towards it;
- the fly finds fruit;
- one step takes ~0.15 ms.

## What it is, and isn't (yet)

- ✅ The **structure** is the real one: the cell types and the order they're wired in come from fly neuroscience.
  The connectome confirmed this pathway in exquisite detail.
- ❌ It does **not** load the 139,255-neuron connectome, and its weights are hand-tuned, not FlyWire's synapse
  counts. A 32×32 frame at 8 fps doesn't need the whole brain. Simulating it would also be far beyond a 2 ms
  render budget.

## Next steps

1. **Real wiring for the visual pathway:** load the FlyWire Codex exports for the T4/T5 → LPTC → descending-neuron
   cell types, and set the model's weights from their synapse counts. The data is free to download with a FlyWire
   account, under CC-BY 4.0.
2. **A full spiking simulation on the bake thread**, for the Fly Brain app's baked loops, where there's no
   render-time budget.
3. **Learning:** let the fly adapt its weights to win (reward = score), and watch which neurons it relies on.

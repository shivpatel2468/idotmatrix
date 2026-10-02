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
| **Every game** → *Plays itself with* → **Fruit-fly brain** | Instead of the built-in AI, the fly plays from pixels (and the smell of its goal), through an eye centred on its own character. Press any key and you take over. In the studio: **Let the fly play** in the top bar on every page (it lists games when the current app isn't one), in Play mode, in a game's status bar, in the command palette, or press `F`. |
| **The studio's 3D Fly view** | Opens by itself whenever a fly is playing: the side panels slide shut and the brain fills their space. **Left:** the circuit below, live, in one of five brain views (pick in the wing header or Graphics → Scene): **Connectome cloud** (default; thousands of neurons in two optic lobes and the central brain, with synapse tracts carrying pulses), **Tower** (the layers stacked: eye → lamina → T4/T5 → HS/VS → LPLC2 → giant fibre → descending neurons → keys), **Radial wheel** (neuron groups around a ring with chords between them), **Spike raster + scope** (a scrolling raster of every group plus oscilloscope traces of the descending neurons and giant fibre), and **Neural web** (a live force-directed graph). **Right:** a 3D fly on a keyboard. It hops onto each key its neurons press, leaps on the giant-fibre escape (key A), grooms when idle, and its compound eyes show the live eye image. A keystroke log and counts sit underneath. Drag the glowing bars beside the panel to resize either side; the ⤢ buttons open a scene (or **Both**, with the live panel between them) full screen with camera angles including a Cinematic auto-camera. The **Brain** tab tunes the fly itself (presets Calm, Curious, Twitchy, Hunter, Daredevil, or sliders: drawn to light, fear of looming things, jumpiness…; `GET/PATCH /api/fly/config`). **Graphics** has quality presets (Auto adapts to your GPU), a frame-rate cap, bloom, particles, shadows, themes, cameras, fly looks and keyboard styles. Nothing of the brain is drawn on the panel. |

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
phototaxis (flies are drawn to light) + smell (the game's lure) ─▶ descending neurons
taste under the feet (lure, where the game allows) ─▶ proboscis-extension reflex ─▶ key A
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

## Tuning the brain

Every brain (each game the fly plays, and the Fly Brain app) reads one shared config, `deskdot.fly.config.FlyConfig`,
stored in `state.json` under `fly` and changed with `GET/PATCH /api/fly/config` (presets: `GET /api/fly/presets`;
agents: the `fly_brain` MCP tool). The defaults are the original constants, so an untouched config behaves exactly
as before. Changes apply on the brain's next step; the Fly Brain app's clip key includes the config, so its loop
re-bakes.

| Knob | Default | Range | What it changes |
| --- | --- | --- | --- |
| `phototaxis` | 0.3 | 0–1 | drive towards light per step |
| `looming` | 1.0 | 0–3 | LPLC2 gain: how strongly expansion is felt (saccades and giant fibre) |
| `motion` | 1.0 | 0–3 | optomotor gain: how much wide-field motion (HS/VS) steers |
| `leak` | 0.8 | 0.3–0.99 | membrane potential kept per step (how long the fly "remembers" a drive) |
| `threshold` | 1.0 | 0.3–3 | spike threshold of the descending neurons |
| `refractory` | 2 | 0–10 | steps of rest after a spike |
| `noise` | 0.06 | 0–0.5 | spontaneous drive (more = twitchier, more random key presses) |
| `escape` | 1.0 | 0–3 | giant-fibre sensitivity (key A) |
| `lure` | 1.0 | 0–3 | sense of smell: how strongly a game's goal cue attracts (0 = anosmic) |

Presets: **Default**, **Calm** (high threshold, little noise, rarely jumps), **Curious** (drawn to every light and
smell), **Twitchy** (noisy, quick, easily startled), **Hunter** (strong lure, steady aim), **Daredevil** (fires
often, barely escapes). `preset` reports the preset the values match, or `custom`.

## How the fly plays each game

Each game tells the fly two things, through `GameApp` hooks:

- `pilot_anchor()`: where seat 1's own character is, so the eye is centred on its body.
- `fly_lure()`: where its goal is, as `[(x, y, strength)]`. **The lure is a sensory cue, not the AI pressing keys.**
  It is injected into the brain as an *odour source* (flies follow smell as well as light): the antennae's map is
  added to the light map phototaxis chooses from, weighted by `lure`, and the descending neurons still integrate,
  fire (or don't) and press the keys. Turn `lure` to 0 and the fly plays from light and motion alone. The cue is
  never drawn on the panel.
- `fly_feeds` (board and puzzle games): standing on the smell fires the **proboscis-extension reflex** (flies taste
  with their legs and extend the proboscis on sugar), pressed as key A: "eat here" = place, open, drop.
- `fly_keys` / `fly_key()`: map the fly's keys onto the game's controls where a direction alone isn't enough.

The lure is computed cheaply from the game's own state and planners (the ones its built-in AI uses), cached where
it is costly, so `render()` stays fast.

| Game | Eye centred on | Lure (the goal it smells) | Keys |
| --- | --- | --- | --- |
| Snake | the head | the nearest apple (the short way round on wrapping maps) | arrows |
| Pong | the paddle | where the ball will cross the paddle's line (bounces included); the middle while it's away | up/down |
| Breakout | the paddle | where the ball will land (walls bounced) | left/right |
| Flappy | the bird | the middle of the next gap (the cave's narrowest stretch), in the bird's column | up = flap |
| Dino | the dino | the air above the next cactus (jump) or the ground under a mid-height bird (duck), just in time | up / down |
| Racer | the car | the free lane (the look-ahead the AI uses) | left/right |
| Street Surge | the car | the racing line: inside of the coming curve, or the widest gap past slower cars | left/right; GF = nitro |
| Neon Heat | the car | the pickup, the drop-off, or the rival carrying the parcel | arrows |
| Light Cycles | the bike | the way with the most room and the longest clear run (rivals' next cells count as walls) | arrows |
| Invaders | the cannon | beside it, away from falling bullets; else under the lowest invader, then the invader itself | steering up fires |
| Starship | the ship | away from bolts, rocks and diving foes; else under the lowest foe | left/right; GF = bomb |
| Asteroids | the ship | the nearest rock or rival (led by its motion); away from a rock about to hit | screen directions become turns; nose on target = fire (or thrust when fleeing); GF = hyperspace |
| Infinity | the ship | the flyable height a few columns ahead | up/down |
| Maze | the runner (or Hunt ghost) | down the corridor towards the nearest dot that avoids the ghosts | arrows |
| Leaf Leap | the hero | the way on, and up-ahead when the next stretch needs a jump (the game's physics look-ahead) | arrows, up = jump |
| Dig World | the miner | the richest ore in reach; else down and along; towards the sky at dusk | arrows (dig/move) |
| Tetris | the falling piece | the best landing (holes/height/bumpiness plan): above while it needs turning, beside it until it's over the column, then on the piece | up = rotate, feeding reflex = hard drop |
| 2048 | the board's middle | the edge of the best slide (one-ply tidiness + merges) | arrows |
| X and 0 | the cursor | X's best cell (minimax for the variant) | arrows, feeding reflex = place |
| Four Up | the hover disc | the best column (shallow negamax), then straight down into the slot (or up to pop) | left/right, down = drop |
| Mines | the cursor | the nearest cell the solver knows is safe (mines it found are avoided, never flagged) | arrows, feeding reflex = open |

A real key press always takes the game straight back from the fly; the studio's Fly button (top bar, Play mode,
the game's status bar, the command palette, or `F`) hands it over again.

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

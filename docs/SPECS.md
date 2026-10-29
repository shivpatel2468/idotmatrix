# Living specs

DeskDot keeps its intent in **living specs**: `SPEC.md` files that sit beside the code they describe and say what
that part must do and must never do. The idea comes from JetBrains ThinkRail's working style: a connected graph of
specs is the durable source of truth, and every change happens in its own branch and pull request that keeps the
specs true.

## The graph

```
SPEC.md (root: product goal, users, platforms, invariants, the map)
├── src/deskdot/engine/SPEC.md      tick, routing, overlays, state, HTTP / WS, LanGate
├── src/deskdot/device/SPEC.md      the BLE link and its non-negotiables
├── src/deskdot/apps/SPEC.md        the app contract
├── src/deskdot/providers/SPEC.md   live data and API health
├── src/deskdot/casino/SPEC.md      fairness, play-money credits, clock, themes, chips, dolly
├── src/deskdot/tv/SPEC.md          the TV view and its perf budget
├── web/SPEC.md                     the studio
├── web/webapp/SPEC.md              the browser version
├── android/SPEC.md                 the phone host app
├── packaging/SPEC.md               installers, releases, in-app updates
└── netlify/SPEC.md                 idotmatrix.com, functions, CSP, legal copy
```

The root's **Map of child specs** table is the index; a spec that isn't in it doesn't exist as far as the checks go.

## What a spec contains

Each `SPEC.md` has the same sections, kept to one or two screens:

| Section | What goes in it |
| --- | --- |
| Purpose | What this part is for, in a paragraph. Links to the doc that explains *how*. |
| Requirements | Numbered, testable statements: `- **R-<AREA>-<n>** …` followed by `Tests:` with real test paths (`tests/test_x.py::test_name`), or `Tests: none yet (gap)`. |
| Invariants | Things that must never change without a decision: `- **I-<AREA>-<n>** …`. |
| Interfaces | The endpoints, messages and bridges this part owns. |
| Open questions | Known gaps and undecided points. |
| Last verified | `Last verified: YYYY-MM-DD`: the date someone last checked the spec against the code. |

A spec states intent, not implementation. Don't copy code, tables or prose that already live in a doc
(docs/ARCHITECTURE.md, docs/API.md, docs/CASINO.md…); link to them.

Area codes: `ROOT`, `ENG`, `DEV`, `APP`, `PROV`, `CAS`, `TV`, `STU`, `WEB`, `AND`, `REL`, `SITE`. Ids are never
reused: when a requirement is removed, its number stays retired.

## How agents and people use the specs

1. **Before changing an area, read its `SPEC.md`** (and the root). The spec tells you what must stay true and which
   tests prove it.
2. **When intent changes, update the spec in the same pull request**: add, change or retire the requirement, cite
   the test that now enforces it, and bump `Last verified`.
3. **A pull request that changes behaviour without touching the relevant spec is incomplete.** Pure refactors and
   bug fixes that restore the specified behaviour don't need a spec change; say so in the PR.
4. Cite requirement ids in commits and PRs (`R-DEV-4`), so a reviewer can check the change against the intent.
5. A requirement with `Tests: none yet (gap)` is a debt. Closing one means writing the test and citing it.

## The check

`tests/test_specs.py` runs with the normal suite and fails when:

- a spec listed in the root map is missing, or a `SPEC.md` exists that the map doesn't list;
- a cited test file doesn't exist, or a cited `::test_name` isn't defined in it;
- a requirement or invariant id is defined twice, or a requirement cites no test and isn't marked as a gap;
- a spec lacks one of the sections above or a `Last verified` date.

SPEC.md files are left out of the desktop build and the web app's engine archive.

## What changed

<!-- Plain words: what someone using DeskDot will notice, then what changed underneath. -->

## Spec

<!-- Which SPEC.md and requirement ids this touches (docs/SPECS.md), e.g. src/deskdot/device/SPEC.md R-DEV-4.
     Behaviour changed? Then the spec changed in this PR too. Pure refactor or a fix back to the spec? Say so. -->

- Spec(s):
- Requirements / invariants:

## How I checked it

- [ ] `uv run pytest -q` and `uv run ruff check src tests` pass (CI runs them)
- [ ] `cd web && npm run build` passes (if the studio changed)
- [ ] New or changed behaviour has a test, and the spec cites it
- [ ] Looks right in `deskdot preview` / the studio (and on a real panel, if I have one)
- [ ] Docs updated (API.md, the area's doc) if behaviour, API or rules changed
- [ ] No secrets, `deskdot.toml`, `.env*`, `data/` or signing keys committed

## Screenshots

<!-- For UI or panel changes: before / after (studio screenshot, `deskdot preview` PNG, a photo of the panel). -->

## Release notes

<!-- One line for WHATS_NEW.md in plain words ("Before: … / Now: …"), or "none" for internal changes. -->

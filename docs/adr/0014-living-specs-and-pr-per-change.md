# ADR 0014: Living specs beside the code, and one pull request per change

- **Status:** Proposed
- **Date:** 2026-10-29

## Context

DeskDot's rules lived in CLAUDE.md and its design in long docs (ARCHITECTURE, CASINO, TV_VIEW, STUDIO_UI…). They say
*how* things work in detail, but nothing short said *what each part must do and never do*, or which test proves it.
Much of the work is done by AI agents, often several at once in separate worktrees. They read the code, not the
intent, so a change could quietly break a promise nobody wrote down. Changes also landed straight on `main`, so
nothing stopped a change from skipping CI or the docs.

JetBrains ThinkRail's working style answers both: a connected graph of **living specs** as the source of truth for
intent, and an **isolated workspace + pull request** for every change.

## Decision

- Each area has a `SPEC.md` beside its code: Purpose, numbered testable requirements (`R-<AREA>-<n>`) with the tests
  that enforce them, invariants (`I-<AREA>-<n>`), interfaces, open questions, `Last verified`. The root `SPEC.md`
  maps them. Specs link to the existing docs instead of copying them ([SPECS.md](../SPECS.md)).
- `tests/test_specs.py` keeps the graph honest: mapped specs exist, cited tests exist, ids are unique, every
  requirement cites a test or is marked as a gap.
- Every change gets its own branch or worktree and a pull request (template in `.github/`); CI must pass; PRs are
  squash-merged; `main` changes no other way and is never force-pushed. Releases stay tags on `main`.

## Consequences

- Agents and people get a one-screen statement of intent per area and know which tests guard it. Requirements without
  tests show up as visible gaps instead of hiding.
- Specs can rot like any doc. The check catches broken links, and `Last verified` shows staleness, but whether the
  words still match the behaviour depends on review. The PR template asks for it every time.
- More ceremony for tiny fixes (a branch and a PR for a typo). Accepted: squash-merge keeps history as clean as
  before, and CI on every PR catches problems before they land.
- Branch protection on `main` (require a PR and green CI) is a GitHub setting the owner turns on. Until then the rule
  is a convention.

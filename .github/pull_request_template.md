## What changed

## How I checked it
- [ ] `uv run pytest -q` and `uv run ruff check src tests` pass
- [ ] `cd web && npm run build` passes (if the studio changed)
- [ ] Looks right in `deskdot preview` / the studio (and on a real panel, if I have one)
- [ ] No secrets, `deskdot.toml`, `.env*` or `data/` committed

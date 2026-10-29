# Providers spec (`src/deskdot/providers/`)

Parent: [root SPEC.md](../../../SPEC.md). How: [docs/APP_SDK.md](../../../docs/APP_SDK.md) § Reading data,
[docs/PUBLIC_APIS.md](../../../docs/PUBLIC_APIS.md) (what we use and why), [docs/API_HEALTH.md](../../../docs/API_HEALTH.md)
(the latest health run), [DATA_SOURCES.md](../../../DATA_SOURCES.md), [docs/COMPATIBILITY.md](../../../docs/COMPATIBILITY.md).

## Purpose

Fetch live data (network feeds, the OS media session, system counters, camera, screen) in the background so apps can
read a cached `value` without ever waiting. Providers are ref-counted: they poll only while an app or the studio holds
them, linger 30 s after the last release, then stop.

## Requirements

- **R-PROV-1** Every provider that calls the network declares each external endpoint (`Provider.endpoints`: URL, role
  primary / fallback / optional, a sample request and the parser). Tests:
  `tests/test_api_health.py::test_every_network_provider_declares_its_endpoints`.
- **R-PROV-2** `scripts/api_health.py` probes every declared endpoint and runs the provider's own parser: a shape
  change is reported as `SHAPE`, not "OK"; results are written to docs/API_HEALTH.md with the web column.
  Tests: `tests/test_api_health.py::test_checker_sees_shape_changes`, `tests/test_api_health.py::test_probe_classifies_answers`,
  `tests/test_api_health.py::test_checker_web_column`.
- **R-PROV-3** Parsers tolerate junk and recorded real answers; when a primary source fails the fallback takes over
  (e.g. Binance geo-block → mirror, HN Firebase → Algolia). Tests:
  `tests/test_publicapis.py::test_provider_fetches_from_recorded_answers`,
  `tests/test_publicapis.py::test_binance_geo_block_switches_to_the_mirror`,
  `tests/test_api_health.py::test_headlines_fall_back_to_algolia_when_firebase_is_unreachable`,
  `tests/test_api_health.py::test_parse_hn_algolia_tolerates_junk`.
- **R-PROV-4** In the browser every provider host is reachable either by CORS or through the proxy allowlist; LAN-only
  providers never poll in a tab. Tests: `tests/test_web_apps.py::test_every_provider_host_works_from_the_browser`,
  `tests/test_web_apps.py::test_lan_providers_never_poll_in_the_browser`.
- **R-PROV-5** Providers polling faster than ~1 Hz override `announce()` so they don't wake the studio on every
  sample. Tests: `tests/test_radar.py::test_announce_only_on_set_change`.
- **R-PROV-6** A missing OS module or hidden metric never crashes a provider; the app shows unsupported / offline.
  Tests: `tests/test_compat.py::test_system_provider_survives_hidden_metrics`,
  `tests/test_compat.py::test_imports_and_meta_without_platform_modules`.
- **R-PROV-7** Recorded fixtures stay small (they are committed). Tests: `tests/test_api_health.py::test_fixtures_are_small`.
- **R-PROV-8** Polling is ref-counted: `acquire()` starts it, the last `release()` stops it after the linger.
  Tests: none yet (gap) — exercised only indirectly by `tests/test_web_media.py`.

## Invariants

- **I-PROV-1** Providers never raise into the event loop; `value` is the last good value and `error` the last failure.
- **I-PROV-2** No blocking calls: no sync HTTP, no `psutil.cpu_percent(interval>0)`; blocking libraries go through
  `asyncio.to_thread`.
- **I-PROV-3** Built-in providers need no API key or account (keyless public APIs; user-supplied tokens only for the
  user's own services, masked in the API).
- **I-PROV-4** Tests never hit the network: providers get fake values or recorded fixtures.
- **I-PROV-5** A new provider is registered in `providers/__init__.py` and, if it is network-backed, declares its
  endpoints (so API health and the web proxy column cover it).

## Interfaces

`Provider` (`base.py`): `value`, `error`, `acquire()`, `release()`, `announce(old, new)`, `endpoints`, `interval`.
Script: `uv run python scripts/api_health.py` → docs/API_HEALTH.md.

## Open questions

- R-PROV-8 has no direct test of the 30 s linger.
- API health is a manual run (no schedule); results depend on the probing network.

Last verified: 2026-10-29

# Casino spec (`src/deskdot/casino/`, `apps/casino_*.py`, `casino.html`)

Parent: [root SPEC.md](../../../SPEC.md). Design and as-built detail: [docs/CASINO.md](../../../docs/CASINO.md); the
rulebook (generated): [docs/CASINO_RULES.md](../../../docs/CASINO_RULES.md); the TV side: [TV spec](../tv/SPEC.md).

## Purpose

A party mode: friends join from their phones with a QR code, the host sets everyone's starting credits, and the group
plays real casino games against the house (or each other) for **play money**. The panel shows only the table; phones,
the studio and the TV show the rest.

## Requirements

- **R-CAS-1** One provably fair RNG (`fair.py`): commit (SHA-256 of a fresh server seed) before betting, client seed
  from every seated phone + nonce, HMAC-SHA256 stream, rejection sampling (no modulo bias), Fisher–Yates shuffles,
  reveal after settlement, `verify()` recomputes the outcome. Tests:
  `tests/test_casino.py::test_rng_pinned_vector_and_determinism`,
  `tests/test_casino.py::test_rejection_sampling_has_no_modulo_bias`,
  `tests/test_casino.py::test_shuffle_is_a_uniform_permutation`, `tests/test_casino.py::test_verify_round`.
- **R-CAS-2** The house never adapts: outcomes don't depend on bets, balances, history or who plays.
  Tests: `tests/test_casino.py::test_session_verify_and_outcome_ignores_bets`.
- **R-CAS-3** Real rules and true odds: every bet's house edge and every slot machine's RTP is the standard / exact
  value, and the rulebook's payouts match the table spots. Tests:
  `tests/test_casino.py::test_roulette_every_bet_has_the_standard_house_edge`,
  `tests/test_casino.py::test_sevens_exact_expected_values`, `tests/test_casino_slots.py::test_rtp_is_exact_and_in_range`,
  `tests/test_casino_cards.py::test_andar_bahar_exact_probabilities_and_edges`,
  `tests/test_casino_themes.py::test_rulebook_payouts_match_the_spots`.
- **R-CAS-4** The bank: bets go to escrow, settle exactly once, credits are whole numbers and never negative, every
  change is a ledger entry; bad stored data is dropped and open escrow refunded on load. Tests:
  `tests/test_casino.py::test_bank_escrow_settlement_and_never_negative`,
  `tests/test_casino.py::test_settle_exactly_once_and_ledger`,
  `tests/test_casino.py::test_bank_persistence_refunds_open_escrow_and_drops_bad_data`.
- **R-CAS-5** Phases `idle → betting → locked → dealing/spinning → action → result → idle`, host-set deadlines; bets
  are frozen from the lock until settlement; an expired turn takes the safe default.
  Tests: `tests/test_casino.py::test_bets_frozen_from_lock_until_settlement`,
  `tests/test_casino.py::test_round_flow_limits_and_auto_next`.
- **R-CAS-6** Private state (hole cards, a seat's own bets, seeds before reveal) reaches only its own phone; public
  status is the same for every phone, the studio and the TV. Tests:
  `tests/test_casino.py::test_phone_protocol_bet_settle_and_private_state`,
  `tests/test_casino.py::test_phones_betting_at_once_see_the_same_table`,
  `tests/test_tv.py::test_tv_never_gets_private_data`.
- **R-CAS-7** One clock: statuses carry wall-clock anchors (`status.clock`), sockets answer pings with `server_time`,
  so panel, studio, phones and TV flip at the same moment. Tests:
  `tests/test_tv_reveal.py::test_status_clock_anchors_are_public_and_steady`, `tests/js/tv_casino.test.mjs`.
- **R-CAS-8** Table themes: every casino app offers every theme, every theme is LED-safe and renders every view, and
  the studio, phone page and TV mirror the engine's list. Tests:
  `tests/test_casino_themes.py::test_themes_are_led_safe`,
  `tests/test_casino_themes.py::test_every_casino_app_offers_the_themes`,
  `tests/test_casino_themes.py::test_every_theme_renders_every_view`,
  `tests/test_casino_themes.py::test_studio_theme_list_mirrors_the_engine`.
- **R-CAS-9** Chips: the rack follows the table limits (no chip outside min/max, capped, spans the range) and is
  published as `status.chips`; a chip set changes only material, never a denomination's colour or label; `auto` follows
  the table theme. Tests: `tests/test_casino_chips.py::test_chips_outside_the_limits_are_not_offered`,
  `tests/test_casino_chips.py::test_public_status_carries_the_rack_and_follows_the_limits`,
  `tests/test_casino_dolly.py::test_chip_set_follows_the_table_theme_unless_the_host_picks_one`,
  `tests/test_casino_dolly.py::test_every_chip_set_is_drawn_on_the_tv_the_phone_and_the_studio`.
- **R-CAS-10** The roulette dolly is a host setting (default `classic_gold`) published as `status.house.dolly`; an
  unknown stored dolly falls back without losing the rest of the house settings. Tests:
  `tests/test_casino_dolly.py::test_dolly_defaults_to_classic_gold_and_is_a_choice`,
  `tests/test_casino_dolly.py::test_dolly_is_a_host_setting_published_in_the_public_status`,
  `tests/test_casino_dolly.py::test_stored_house_with_an_unknown_dolly_keeps_the_rest`.
- **R-CAS-11** Every table renders every phase fast, empty and with players (checked by eye with 1, 4 and 8). Tests:
  `tests/test_casino.py::test_render_every_phase_fast`, `tests/test_casino.py::test_live_table_with_players`.
- **R-CAS-12** A wallet follows its phone across seats and tables. Tests:
  `tests/test_casino.py::test_wallet_follows_the_phone_across_seats`,
  `tests/test_casino_studio.py::test_lobby_switch_moves_phones_to_the_next_table`.

## Invariants

- **I-CAS-1** Credits are play money: no purchase, cash-out, transfer or exchange to anything of value, ever; no rake.
- **I-CAS-2** All randomness goes through `fair.py`; nothing else may draw outcomes.
- **I-CAS-3** Game rules (`games/*.py`) are pure and draw nothing; panel apps are thin and draw public state only.
- **I-CAS-4** Phase timers run from the render clock — no sleeps.
- **I-CAS-5** The win tier (`net ÷ stake`: ≥ 30 JACKPOT, ≥ 10 MEGA WIN, ≥ 3 BIG WIN) is one function shared by the TV
  and the phone page.

## Interfaces

Phone protocol over `WS /ws/p/{code}` (bet, action, seed, profile; `status` / `private` messages) — docs/CASINO.md § 4;
studio ops through `/api/apps/{id}/actions/*`; `status.{phase, ends_in, clock, chips, chip_set, house, result, …}`;
`/api/play/lobby*`.

## Open questions

- I-CAS-1 has no automated test (nothing in the API can move credits out today; enforced by review). The website build
  adds an 18+ gate and "play money" copy ([netlify spec](../../../netlify/SPEC.md)); main has the "Play money only" line.

Last verified: 2026-10-29

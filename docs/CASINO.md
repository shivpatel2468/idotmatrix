# 🎰 Casino mode: design spec

The goal: take the panel to a party. Friends join from their phones with the same QR code as multiplayer games.
The host sets everyone's starting credits, and the group plays real casino games against the house (or each other,
in poker-style games). Credits rise and fall across every game in the session.

- **The panel shows only the table.** That means the wheel, the dice, the cards and the result, big and clear at 32×32.
- **Phones (and the host's laptop) show the rest:** the player's own credits, the betting layout, chips and private
  cards.

This spec is the contract every part follows: engine, panel apps, phone page, studio. Read CLAUDE.md first.

## 1. Fairness (non-negotiable)

- **One RNG for everything**, `src/deskdot/casino/fair.py`. It is provably fair, with a commit–reveal per round:
  - Before betting opens, the round has a fresh **server seed** (`secrets.token_bytes(32)`). Its SHA-256 hash is
    published to every phone and to the studio.
  - The **client seed** is the concatenation of every seated player's seed (each phone generates one when it joins
    and may re-roll it), plus the round **nonce**.
  - The outcome stream is `HMAC-SHA256(server_seed, f"{client_seed}:{nonce}:{counter}")` in 32-bit chunks. Integers
    in a range use **rejection sampling** (no modulo bias). Shuffles are **Fisher–Yates** on that stream.
  - After settlement the server seed is revealed. `fair.verify(...)` recomputes the outcome, and the studio and phone
    show a "Verify" link with the seed, hash, client seed and nonce.
- **The house never adapts.** Outcomes never depend on bets, balances, history or who is playing. Tests assert this.
- **Real rules.** Each game follows its standard rulebook, with the payouts below. The studio shows the true house
  edge of each bet, and the slot machine shows its exact RTP, computed from its reel strips and pay table.
- Bets move into escrow (the **bank**) when placed and are settled exactly once. Credits are whole numbers and never
  go negative. Every change is a ledger entry: `{round, game, seat, delta, reason}`.

## 2. Engine layout (`src/deskdot/casino/`)

| File | What |
| --- | --- |
| `fair.py` | The seed / commit / reveal / verify logic. `Rng.randint(lo, hi)`, `.shuffle(seq)`, `.choice(seq)`. |
| `bank.py` | Wallets per player id: credits, escrow, ledger, stats (won, lost, biggest win). The host can set base credits and adjust a wallet (each adjustment is logged). Persisted in the store under `casino`; bad stored data is dropped (rule 15). |
| `cards.py` | Cards, decks, shoes (n decks, cut card), poker 5/7-card hand evaluator, Teen Patti 3-card ranking, baccarat values. |
| `table.py` | `CasinoGame` base: a pydantic `Rules` model, phase machine, `place_bet()`, `action()`, `tick(now)`, `public_state()`, `private_state(seat)`, `settle()`. |
| `session.py` | `CasinoSession`: players (bound to lobby seats and the studio host seat), bank, the current game, house settings (base credits, min/max bet, timers), round history (with fairness proofs) and the leaderboard. Drives phase timers from the app's render clock (no sleeps). |
| `games/*.py` | One file per game. These are pure rules, fully unit-tested, with no drawing. |

**Phases:** `idle → betting (deadline) → locked → dealing/spinning → action (turn, per-turn deadline, poker-style
games) → result → idle`.
- The host sets every deadline.
- An expired turn takes the safe default: stand, check if free, otherwise fold.

## 3. Panel apps (`src/deskdot/apps/casino_*.py`, `category = "casino"`)

- **One `App` per game**, which is thin. `render()` draws the game's public state and must stay pure and fast (rules 1–3).
- Add `"casino"` to the `Category` literal (engine) and to the studio's `AppMeta` category union.
- **Legibility first:**
  - Use big numerals (the `big` font), strong red/black/green and gold, and keep text margins.
  - Show the result for at least 3 s with a win flash.
  - Keep dark tones ≥ 45 per channel (the user's gamma).
  - Cards are 7×10 px with the rank glyph plus a suit pip, red or white.
- Every table must be checked with `uv run deskdot preview <id> --out x.png` (and looked at) in every phase, and with
  1, 4 and 8 players.

## 4. Protocol

- **Phones** join with the existing `/p/{code}` QR. When the lobby's app is in category `casino`, `GET /p/{code}`
  serves `src/deskdot/casino.html` (the phone casino page) instead of `controller.html`.
  - It uses the same WebSocket `/ws/p/{code}`, the same `hello`/`profile`/`roster`, and the same seat reserve on
    reconnect.
  - The phone sends `{"type": "casino", "op": "...", ...}`, forwarded as `engine.action(app, "casino", {...,
    "player": seat})`.
  - Bet ops: `bet {spot, amount}`, `unbet {spot}`, `clear`, `rebet`, `seed {client_seed}`. Game ops depend on the
    game, for example `hit/stand/double/split/surrender/insurance`, `fold/check/call/raise {amount}`,
    `pack/chaal/blind/show/sideshow`, `pull` (slots).
  - Server → phone: `state` carries the public status, plus **`private` for that seat only**: credits, own bets,
    own cards, legal actions, turn deadline. Add an optional `App.private_status(seat)` hook (default `None`) and merge
    it in `push_state`.
  - Hole cards **never** appear in the public status.
- **Studio (host):** `POST /api/apps/{id}/actions/casino` with host ops: `start_round`, `settings {…}`,
  `credits {seat, set|add}`, `kick`, `pause`, `reset_session`, `verify {round}`. The host can also take a seat and
  play from the laptop with the same ops (`player: "host"`).

## 5. Phone page (`casino.html`)

- A single self-contained file, mobile-first, matching the controller's dark style.
- The warm casino palette: felt green, gold, red, and the brand rose #ff3f78 / tangerine #ff7419 / gold #ffcc33.
- **Always visible:** name, avatar, credits (animated count up and down), the phase and countdown.
- **Bet controls:** a chip rack (1, 5, 25, 100, 500, all-in) with tap-to-place. Undo / clear / rebet are always reachable.
- **Per game:**
  - **Roulette:** a full clickable table layout. Tap a number for a straight bet; tap a line or corner for
    split/street/corner/six-line; outside bets for dozens, columns, red/black, odd/even, low/high. Placed chips show
    on the layout, the wheel result is highlighted, and recent results stream across.
  - **7 Up 7 Down:** three big zones (UNDER 7, LUCKY 7, OVER 7).
  - **Blackjack:** own hand(s) with totals; buttons for hit / stand / double / split / surrender / insurance, enabled
    only when legal.
  - **Baccarat:** Player / Banker / Tie zones plus pair side bets.
  - **Slots:** the player's own machine. A **lever to pull** (drag down and release, with haptics) and reels that
    animate in sync with the panel. Pay table on a tap.
  - **Hold'em:** own hole cards, the board, pot, call amount, a fold / check / call / raise slider and all-in.
  - **Teen Patti:** blind/seen state, see cards, chaal (stake shown), pack, show, sideshow.
  - **Andar Bahar:** Andar / Bahar zones with the joker shown.
  - **Big Six:** zones for every wheel symbol with its payout.
- **Results:** win/loss as a toast with the amount, then a "Verify this round" sheet.
- **Fair-play:** haptics on bet, lock, win; reduced-motion respected; no zooming or text selection.

## 6. Studio casino mode

- **Entering:** when the current app is a casino game, the studio enters **casino mode** with its own entrance:
  - the side drawers slide shut, as in the Fly view;
  - a marquee of chasing bulbs lights around the stage and gold chips cascade once;
  - the left and right wings slide in.
- **Left wing: casino settings, casino games only.**
  - House: base credits, min/max bet, timers.
  - Per-game rules, every option below.
  - Each bet's house edge, and the slot RTP.
  - Presets: "Friendly night", "Vegas", "High rollers".
- **Right wing: the players.** Seats with avatar and credits (live), a leaderboard, adjust/top-up, kick, the round
  history with "Verify", and a "Play from this laptop" mini-controller.
- **Centre:** the panel mirror plus the host bar: game picker (casino games), Start round / Next, the countdown,
  pause, and the QR for joining.
- **Leaving:** exits back to the normal studio.

## 7. Games, rules and payouts

| Game | Rules (standard) | Pays | Host options |
| --- | --- | --- | --- |
| **Roulette** | European single zero (default) or American 0/00 | Straight 35:1, split 17:1, street 11:1, corner 8:1, six line 5:1, first four 8:1 (EU) / top line 0-00-1-2-3 6:1 (US), dozen 2:1, column 2:1, red/black, odd/even, low/high 1:1 | wheel type, La Partage (EU even-money half back on 0), bet timer, table min/max |
| **7 Up 7 Down** | two dice, sum 2–12 | under 7 1:1, over 7 1:1, exactly 7 4:1 (or 5:1) | 7 payout, bet timer |
| **Blackjack** | 1–8 deck shoe, cut card ≈ 75 % | blackjack 3:2 (or 6:5), win 1:1, insurance 2:1, push returns | decks, S17/H17, BJ payout, double (any two / 9–11), double after split, splits up to 3 (4 hands), split aces one card, surrender (late/none), dealer peek, turn timer |
| **Baccarat** | Punto Banco, standard third-card rules | Player 1:1, Banker 1:1 minus 5 % (or no-commission: banker win on 6 pays 1:2), Tie 8:1 (or 9:1), Player/Banker pair 11:1 | commission mode, tie payout, decks, bet timer |
| **Slots** | 3 reels × 3 rows, 5 paylines, reel strips + pay table, uniform stops | per pay table; the exact RTP is computed and shown | machine theme, bet per line, lines, volatility preset (picks the reel-strip set; RTP shown) |
| **Texas Hold'em** | no-limit, 2–10 players, button rotation, blinds, side pots, showdown | pot(s) to the best 5 of 7, ties split | blinds, blind increase, turn timer, rake (default 0) |
| **Teen Patti** | boot, blind/seen (chaal: blind 1× stake, seen 2×), pack, show (2 left), sideshow; trail > pure sequence > sequence > colour > pair > high card (A-K-Q top sequence, A-2-3 next) | pot to the winner | boot, max blind rounds, pot limit, turn timer |
| **Andar Bahar** | joker drawn, cards dealt alternately (first card to Andar) until a rank match | Andar 0.9:1, Bahar 1:1 | first-card side, bet timer |
| **Big Six wheel** | 54 segments: 1×24, 2×15, 5×7, 10×4, 20×2, joker×1, logo×1 | 1:1, 2:1, 5:1, 10:1, 20:1, joker/logo 40:1 | bet timer |

Rock Paper Scissors is a regular **game** (category `games`, a `GameApp`), not part of the casino. It has AI vs AI
(attract), player vs AI and player vs player modes, best-of options, and pixel-hand pickers on phones.

## 8. As built (wave 1) — deviations and how to add a game

Wave 1 shipped the core (`fair`, `bank`, `cards`, `table`, `session`), **Roulette** and **7 Up 7 Down**, the protocol
and `casino.html`. Where it differs from or sharpens the sections above, this section wins.

**Fairness details.**
- The client seed is the seated players' seeds **in seat order joined with `.`** (host first); with no seeds it is
  `deskdot`. Seeds are 1–64 printable ASCII characters without `:`. It is fixed at the lock, so a seed sent during
  betting counts for that round.
- The nonce is the session's round counter (persisted, never reused). Words are read big-endian, 8 per HMAC block.
- Roulette draws `pocket = randint(0, N-1)`, an index into the wheel order (`EU_WHEEL` / `US_WHEEL`); dice draw
  `randint(1, 6)` twice, first die first. The phone re-implements SHA-256, HMAC and the RNG in JavaScript and checks a
  revealed round on its own (hash, the hash it saw before betting, the re-computed outcome, its seed included);
  `tests/test_casino.py` pins a vector both sides agree on. **A new game must add `replay(rng, rules)` to its phone
  module with exactly the same draw order as `draw()`.**
- Recent rounds (seed, hash, client seed, nonce, outcome, rules) are in the public `status.history`.

**Round machine.**
- Betting opens with **no deadline; the first chip starts the countdown** (`house.bet_seconds`), so nothing spins for
  nobody. The round also locks when every player with chips pressed **done**, or when the host sends `lock`.
- `locked` lasts 1 s ("NO MORE BETS"), then `spinning` (the reveal phase; dice use it too). **From the lock until
  settlement every bet is frozen**: `bet`, `unbet`, `clear`, `rebet` and `done` are refused outside `betting` and change
  nothing (tested for every phase). The phone greys the chips and the board and shows a "bets locked" banner.
- `result` shows for `house.result_seconds`, then betting reopens (`auto_next`, default on) or the table idles.
- `unbet` takes an optional `amount` (the phone's Undo removes the last chip); a spot never keeps less than the
  table minimum. A chip over the table maximum tops the spot up to the maximum.
- Payouts are whole credits, rounded down (only matters for La Partage on an odd stake).
- Leaving a casino app closes its table: open bets are refunded; a locked round is paid (its outcome was fixed).
  An engine restart mid-round refunds escrow at load.

**Players and settings.**
- Wallets are keyed by a **pid** the server derives from the phone's client id (`multiplayer.player_pid`, one-way),
  sent as `pid` in the `seat` action. A phone that comes back later — even on another seat — finds its credits.
  The studio is pid `"host"`.
- Lobbies seat up to 8 phones (`max_players = 9`, seat 1 = host). The panel shows the join QR while the lobby is
  open **and** the table waits for its first chip; `POST /api/play/lobby/start` hides it for good.
- **House settings** (base credits, min/max per spot, timers, auto-next) live in the session (`House`, host op
  `settings`), shared by every casino game. **Game rules** are the app's pydantic Settings (studio form), mirrored
  by the game's `Rules` model with the same field names. Every casino app also has a `view` setting (group
  "Preview"): `live`, a self-playing `demo` loop, or one frozen phase (`betting`, `locked`, `spinning`, `result`,
  `board`, `lobby`, `paused`) — use it with `deskdot preview <id> --settings '{"view":"spinning"}' --t 3`.
- `AppContext.shared(key, factory)` gives every casino app the same `CasinoSession` (persisted in store section
  `casino`). `App.private_status(seat)` is the engine hook behind the phone's `private` state.
- The roulette spin is streamed at 10 fps (not a baked clip): the ball's path is solved backwards from the outcome
  so it lands exactly in the drawn pocket.

**Adding a game** (Blackjack, Baccarat, Slots, Hold'em, Teen Patti, Andar Bahar, Big Six):
1. `casino/games/<game>.py`: subclass `CasinoGame`, `@register_game`, set `id`, `name`, `Rules`, `spin_seconds`;
   implement `spots()`, `draw(rng)`, `returns(outcome)`, `outcomes()` (exact probabilities → the house edges are
   computed, tests check them) and `summary(outcome)` → `{label, tone}`. Import it in `casino/games/__init__.py`.
   Card games: shuffle a `cards.Shoe` with the round's `rng` (record in the outcome which round shuffled it), and
   override `on_locked` (deal → `dealing` / `action`), `game_op` (hit, stand, fold, …), `play_tick` (turn deadlines:
   `house.turn_seconds`, safe default on expiry), `payout` / `stakes`, and `private_state` (own cards, legal ops,
   turn deadline). Hole cards go only in `private_state`, never in `public_state`.
2. `apps/casino_<game>.py`: subclass `apps._casino.CasinoApp`, set `Game`, `Settings` (subclass `CasinoSettings`
   + the rules fields), and draw `draw_table(f, v, now)` (spin / deal / result). Override `tile()` and
   `hero_result()` for the betting / results board. Add it to `apps/__init__.py`.
3. `casino.html`: `registerGame("<game id>", {title, spinTitle, resultTitle(r), mount(el, ctx), update(ctx),
   unmount(), replay(rng, rules), describe(outcome), paytable(ctx)})`. Use `ctx.bet(spot)`, `ctx.unbet(spot)`,
   `ctx.send(op, payload)`, `ctx.pub`, `ctx.priv`, `ctx.betting`, `chipStyle(n)`, `short(n)`, `fmt(n)`. The core owns
   the HUD, chip rack, undo / clear / rebet / done, the result card and the Verify sheet.
4. Tests: exact EV of every bet by enumeration, outcomes independent of bets, frozen bets, render speed in every view.

**Studio casino mode (as built, `web/src/components/casino/`).**
- `useCasinoView()` is true while the app on the panel has `category == "casino"` and the host hasn't pressed
  *Leave casino* for it (a gold **Casino** key on the normal stage brings it back). It wins over the Fly view: the
  drawers shut through the same `.drawer[data-closed]` mechanism and `Stage` renders `CasinoStage` instead.
- Entrance: wings slide in (0.38 s after the drawers start closing), the marquee bulbs light one by one then chase
  (faster on a win), gold chips fall once. `prefers-reduced-motion`: static bulbs, no cascade, no slides.
- Data: the state stream plus a 0.9 s poll of the host op `view` (fresh status, the host seat's private view, the
  leaderboard with pids, and — when the rules change — the spots and avatar art). Everything is generic: rules are
  rendered from the app's schema (hints by field name in `LeftWing.tsx`), odds from `status.edges` (+ `status.rtp`
  when a game publishes it), the laptop controller from the spots (a roulette number grid when the spots look like
  a wheel) and `private.ops` (game ops become buttons).
- Switching tables with a room open uses `POST /api/play/lobby/switch`, so phones stay seated.
- Presets set the house and suggest rules by field name; a rule is applied only if the current game has that field
  and accepts the value.

## 9. As built (wave 2: Hold'em, Teen Patti, Andar Bahar, Big Six)

Where this differs from §7, this section wins. Rules: `casino/games/{holdem,teenpatti,andarbahar,bigsix}.py`
(module docstrings cite the rule books); panel: `apps/casino_*.py`; tests: `tests/test_casino_cards.py`.

**Player-vs-player tables** (`casino/games/_pvp.py`, panel base `apps/_pvpapp.py`).
- `betting` is the "next hand" lobby. Phones are dealt in automatically when they sit (`sit {on}` toggles; the
  studio host opts in with `sit`). The deal countdown starts once two players are in (`house.bet_seconds`, 3 s when
  everybody seated is in). `bet`/`unbet`/`clear`/`rebet`/`done` are refused: money goes in with the moves.
- The lock shuffles one deck with the round's RNG: `outcome = {"deck": "AS KD …"}` (Fisher–Yates of
  `cards.new_deck()`, replayed by the phone). Then `dealing` (animation beats) ↔ `action` (one turn,
  `house.turn_seconds`; expired: Hold'em checks if free else folds, Teen Patti packs; an unanswered sideshow is
  refused).
- Every chip goes to escrow as it is bet; settlement pays the pots once through the bank (sum of nets = −rake).
  Leaving mid-hand voids the hand (everything refunded); a decided hand is paid.
- Hole cards are only in the owner's `private`; a blind Teen Patti player gets no cards until `see`. Shown hands
  become public at a showdown. After settlement the seed is revealed, so the whole deck order is recomputable —
  inherent to provably fair card games.
- Players who can't cover one big blind / one boot sit out until topped up.

**Texas Hold'em** — no-limit, 2–10. Button moves one seat per hand; heads-up the button posts the small blind and
acts first pre-flop. Min bet = BB; min raise = the last full raise; a short all-in doesn't reopen the betting for
players who already acted (unless the raises since add up to a full raise). Side pots per all-in level
(`build_pots`); ties split, odd chip to the first winner left of the button. Rake (default 0, %, cap) only from
contested pots at a showdown. Blinds can double every N hands. Ops: `fold check call raise {amount: raise-to}
allin`.

**Teen Patti** (pagat.com + the common Indian limits) — boot; blind chaal 1× stake / raise 2×, seen 2× / 4× (a
raise doubles the stake, never above the chaal limit); `see` anytime; must see after `max_blind_rounds` blind bets.
Show only with two left: blind pays 1×, seen 2×, a seen player can't show against a blind one; equal hands → the
player who did **not** pay wins. Sideshow: a seen player pays their chaal and asks the previous live player (seen,
has bet; ≥ 3 players left) — refuse, or accept: the two see each other's cards (`private.peeks`), the lower packs,
equal → the asker packs. Pot limit forces a show of everyone left (exact ties split). A short player may go all-in;
they compete only for the pot as it stood then (`snapshot_pots`; blind/seen stakes differ by design, so poker's
matched-level side pots don't apply). Ops: `see chaal raise pack show sideshow accept refuse`.

**Andar Bahar** — joker = top card of the shuffled deck; alternate deals from the first side until the joker's
rank appears. The joker is turned **at the lock**, not before betting (it has to come from the committed round;
the odds don't depend on its rank). P(first side wins) = 429/833 = 51.50 %. **The first side pays 0.9:1, the other
1:1** (first card to Andar = the standard Andar 0.9:1 / Bahar 1:1); with the first card to Bahar the payouts swap,
so no option ever gives the player an edge. Edges: 0.9:1 side 179/8330 = **2.149 %**, 1:1 side 25/833 =
**3.001 %**. Card-count side bets (cards dealt, joker excluded): 1–5 2.5:1, 6–10 3.3:1, 11–15 4.6:1, 16–25 3.3:1,
26–30 14.5:1, 31–35 24.5:1, 36–40 49:1, 41–49 118:1 — fair odds less 5 %, rounded down; exact edges 5.1–6.7 %.
The deal takes 2.3–10.6 s (pace adapts to the count); the result waits for the last card.

**Big Six** — 54 segments in `bigsix.WHEEL` (spread evenly, joker and logo opposite); `segment = randint(0, 53)`.
Edges: 1 → 11.11 %, 2 → 16.67 %, 5 → 22.22 %, 10 → 18.52 %, 20 → 22.22 %, joker/logo → 24.07 %. The panel wheel
decelerates at a constant rate and is solved backwards from the outcome (tested to stop under the clapper on the
drawn segment for every segment).

**Panel art.** Cards are 7×10 (`apps/_cardart.py`: rounded slate face, rank rows 1–5, 5×3 pip rows 7–9, red /
white ink; red lattice backs). The Hold'em board and Teen Patti show rows use the 5×10 `narrow` cut so five fit.
PvP previews replay a bot-played demo hand (`view`: demo, betting, locked, dealing, action, result, board, lobby,
paused); the edge ring is the turn clock in the acting player's colour.

## 10. As built (wave 2: Blackjack, Baccarat, Slots)

Rules: `casino/games/{blackjack,baccarat,slots}.py` · panel: `apps/casino_{blackjack,baccarat,slots}.py` (cards drawn
with the shared `apps/_cardart.py`) · phone: the "house games" block of `casino.html` (`HG.*` helpers) · tests:
`tests/test_casino_{blackjack,baccarat,slots,house_phone}.py`.

**Shared pieces.**
- `cards.DealingShoe` deals one card at a time with a *lazy Fisher–Yates* on the round's `Rng`: card k is
  `j = randint(0, n-1)` over the cards left (listed in `CARD_KINDS` order), the card at `j` is dealt and the last
  card takes its place — exactly the cards a full Fisher–Yates shuffle would put at the bottom (tested). The phone's
  `HG.shoe` mirrors it line for line.
- `CasinoGame.replay_with(rules, rng, stored)` (default: `replay`) lets a game whose round depends on more than its
  seeds verify against the stored outcome; `session.verify` calls it and the phone passes the stored outcome as
  `replay(rng, rules, outcome)`'s third argument. `tests/test_casino_house_phone.py` runs the page's JavaScript in
  Node against real rounds of all three games.

**Blackjack.** One shoe lasts many rounds (cut card at `penetration` %, also reshuffled when fewer than 12 cards per
hand are left). Each round restarts the lazy shuffle on the cards still in the shoe — the same distribution as one
shuffle per shoe, but every round verifiable on its own: the outcome records `shoe` (the composition at the start,
one digit per card kind), `shuffled`, every card dealt in order (`cards`), the hands, the dealer and the move `log`;
the phone also checks the chain (this shoe = the previous round's minus its cards). Order: one card each in seat
order (host first), dealer up card, second cards, hole card face down → insurance (dealer ace, half the bet, 2:1,
timer `min(12, turn_seconds)`, default *no*) → peek (US, ace or ten up) → turns in seat order, hand by hand, timer
`house.turn_seconds`, default *stand* → dealer turns the hole card and draws (S17/H17; no draws when only
blackjacks / busts / surrenders are left) → settlement. Splits: equal value (10-J allowed), up to `max_splits`
(4 hands), split aces one card each, no resplit, 21 after a split pays 1:1; a split hand gets its second card when
play reaches it. Late surrender only as the first decision of an unsplit hand. Without peek (European no-hole-card)
a dealer blackjack found at the end takes doubles and splits too, and a surrendered hand loses all. Doubles, splits
and insurance are staked from the wallet during play (the main bet itself stays frozen like every bet). Closing
the table mid-hand plays it out with the safe defaults and pays it (never voided). The studio's edge is an
estimate from rule-effect tables (base 0.40 % for 6D S17 DAS no-surrender peek 3:2; default rules 0.32 %);
insurance's edge is exact (7.40 % at 6 decks). A 60 000-hand basic-strategy run through the engine lands within
4 SE of it. Payouts round down (bet even amounts for exact 3:2).

**Baccarat.** A fresh `decks`-deck shoe every coup (continuous shuffle → exact textbook odds). Outcome:
`{player, banker, p, b, winner, natural, ppair, bpair}`; deal order P1 B1 P2 B2 P3 B3. `edges()` enumerates every
card-value sequence exactly: 8 decks → Banker 1.06 % (no-commission 1.46 %), Player 1.24 %, Tie 14.36 % at 8:1
(4.84 % at 9:1), pairs 10.36 %. The coup reveals card by card during `dealing` (`public.cards`); the reveal time
depends on the number of cards. Banker pays 0.95:1 rounded down (bet in 20s for an exact 5 %).

**Slots.** Themes `classic`, `neon` (wild star, any-7s / any-bars), `space` (any ships, star lead); volatility
`low/medium/high` picks the reel-strip set (`STRIPS`, with blank stops). Exact RTP by enumerating every stop
combination (all nine presets 95.00–96.25 %, e.g. classic medium 95.708 %, hit rate 26 %); a 300 000-spin
simulation is within 4 SE. No shared betting phase: the table stays in `betting`, every player has their own
sealed next round (`private.sealed`: nonce + hash) before pulling; `pull {bet}` (bet per line from
`machine.bets`, × the host's lines, within the table limits) locks it with the client seeds, stakes it and queues
the spin. The panel plays the queue one spin at a time (reels stop at 1.5 / 2.1 / 2.7 s); each stop is revealed
publicly only as that reel stops, the spin settles and the seed is revealed at the last stop. A queued spin can't
be changed or repeated, and bet ops are refused. Closing the machine pays every queued spin. The phone gets the
same pixel symbols (`machine.sprites`) and lands its reels on the revealed stops; lever = drag down and release
(≥ 60 %), with a SPIN button.

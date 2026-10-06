# Casino rulebook

How to play and the rules of every casino game and Rock Paper Scissors. **Generated** from
`src/deskdot/casino/rulebook.py` (the same text the phones and the studio show) — edit that file, then run
`uv run python -m deskdot.casino.rulebook > docs/CASINO_RULES.md`. Design spec: [CASINO.md](CASINO.md).

## Roulette

*Guess where the ball lands: one number, a group of numbers, or a colour.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick a chip in the rack at the bottom. The rack shows only the chips this table allows (between the table minimum and maximum, e.g. 1K, 2K, 5K at a high-roller table), plus **ALL** for everything you have.
3. Tap or drag a chip onto the table: a number for a straight bet, the line between two numbers for a split, the point where four numbers meet for a corner, the outer edge of a row for a street (two rows: six line), or an outside box (red/black, odd/even, dozens, columns). Hold a finger on a spot to see what it covers and what it pays.
4. Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're ready — the table locks at zero or once everyone is done.
5. **No more bets** — the panel spins the wheel. Winning bets are paid to your credits automatically.

### The wheel

- **European** (default): 37 pockets, 0–36. **American**: 38 pockets, 0, 00 and 1–36. The host picks the wheel.
- 18 numbers are red, 18 black; 0 and 00 are green. The ball lands in one pocket; every bet that covers that number wins.

### Inside bets

- **Straight** — one number: pays **35:1**.
- **Split** — two touching numbers (also 0/1, 0/2, 0/3, and 0/00 on the American wheel): pays **17:1**.
- **Street** — a row of three (also the trios 0-1-2 and 0-2-3; American 0-00-2 and 00-2-3): pays **11:1**.
- **Corner** — four numbers in a square: pays **8:1**.
- **Six line** — two rows, six numbers: pays **5:1**.
- **First four** 0-1-2-3 (European only): pays **8:1**. **Top line** 0-00-1-2-3 (American only): pays **6:1**.

### Outside bets

- **Dozen** (1–12, 13–24, 25–36) and **Column**: pay **2:1**.
- **Red / Black**, **Odd / Even**, **1–18 / 19–36**: pay **1:1**.
- 0 and 00 are none of these: every outside bet loses on a zero.
- **La Partage** (host option, European only): when the ball lands on 0, even-money bets get half their stake back.

### House edge

- European: **2.70 %** on every bet (1.35 % on even-money bets with La Partage).
- American: **5.26 %** on every bet, **7.89 %** on the top line.

### Table basics

- You play against the house with play-money credits. Everyone starts with the credits the host sets.
- Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.
- Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up to the maximum.
- Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when everyone with chips down has tapped **Done**, or when the host locks it.
- From **No more bets** until the result, every bet is frozen: no new chips, no undo.
- Wins are paid in whole credits, rounded down.
- If the host closes the table while betting is open, every open bet is refunded. A round that already locked is always played out and paid.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## 7 Up 7 Down

*Two dice: will the total be under 7, exactly 7, or over 7?*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick a chip in the rack at the bottom. The rack shows only the chips this table allows (between the table minimum and maximum, e.g. 1K, 2K, 5K at a high-roller table), plus **ALL** for everything you have.
3. Tap one of the three zones: **UNDER 7**, **LUCKY 7** or **OVER 7**. You can bet on more than one.
4. Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're ready — the table locks at zero or once everyone is done.
5. The panel rolls two dice. The zone that matches the total pays out.

### Bets and payouts

- **Under 7** — the total is 2, 3, 4, 5 or 6: pays **1:1**.
- **Over 7** — the total is 8, 9, 10, 11 or 12: pays **1:1**.
- **Lucky 7** — the total is exactly 7: pays **4:1** (or **5:1** if the host sets it).
- A 7 loses both Under and Over; any other total loses Lucky 7.

### Odds

- 15 of the 36 dice combinations are under 7, 15 are over, 6 make 7.
- House edge: **16.67 %** on Under / Over and on Lucky 7 at 4:1; Lucky 7 at 5:1 is a fair bet (0 %).

### Table basics

- You play against the house with play-money credits. Everyone starts with the credits the host sets.
- Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.
- Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up to the maximum.
- Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when everyone with chips down has tapped **Done**, or when the host locks it.
- From **No more bets** until the result, every bet is frozen: no new chips, no undo.
- Wins are paid in whole credits, rounded down.
- If the host closes the table while betting is open, every open bet is refunded. A round that already locked is always played out and paid.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Blackjack

*Beat the dealer: get closer to 21 without going over.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick a chip and tap the betting circle. Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're ready — the table locks at zero or once everyone is done.
3. Everyone gets two cards face up; the dealer shows one card. Your hand total is on your phone.
4. On your turn tap **Hit** (another card), **Stand**, **Double** (double the bet, take exactly one card), **Split** (a pair into two hands) or **Surrender** (give up half). Only legal moves light up.
5. When everyone has played, the dealer turns the hidden card and draws. Wins are paid automatically.

### Card values

- 2–10 count their number, J Q K count 10, an ace counts 11 or 1 (a hand with an ace counted as 11 is **soft**).
- **Blackjack** is an ace and a 10-value card as your first two cards. 21 after a split is not a blackjack.
- Over 21 is a **bust**: the hand loses at once, even if the dealer busts later.

### Payouts

- Win: **1:1**. Blackjack: **3:2** (or **6:5** if the host sets it). A tie (**push**) returns your bet.
- **Insurance**: when the dealer shows an ace you may bet half your bet that the dealer has blackjack; it pays **2:1**. The default is no insurance.
- Payouts are rounded down to whole credits — bet even amounts for an exact 3:2.

### Your moves

- **Double**: on your first two cards (any two by default, or only a hard 9, 10 or 11 if the host sets it); you get exactly one more card. Doubling after a split is a host option (on by default).
- **Split**: two cards of the same value (10 and J count) become two hands, each with your bet. Up to 3 splits (4 hands) by default. Split aces get one card each and can't be split again.
- **Surrender** (late, on by default): as your first decision on an unsplit hand, give up and get half your bet back.
- Doubles, splits and insurance are paid from your credits during play. When your turn timer runs out you **stand**.

### The dealer

- Draws to 17, and **stands on soft 17** (or hits it, if the host sets it). The dealer has no choices.
- **Peek** (on by default): with an ace or a 10 showing, the dealer checks for blackjack before anyone plays, so you can only lose your first bet to it. Without peek, a dealer blackjack takes doubles and splits too.
- The shoe holds 6 decks by default (1–8). A new shoe starts when the cut card comes out.

### Table basics

- You play against the house with play-money credits. Everyone starts with the credits the host sets.
- Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.
- Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up to the maximum.
- Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when everyone with chips down has tapped **Done**, or when the host locks it.
- From **No more bets** until the result, every bet is frozen: no new chips, no undo.
- Wins are paid in whole credits, rounded down.
- If the host closes the table while betting is open, every open bet is refunded. A round that already locked is always played out and paid.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Baccarat

*Bet on which hand ends closer to 9: Player or Banker — or a tie.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick a chip in the rack at the bottom. The rack shows only the chips this table allows (between the table minimum and maximum, e.g. 1K, 2K, 5K at a high-roller table), plus **ALL** for everything you have.
3. Tap **PLAYER**, **BANKER** or **TIE**, and if you like a pair side bet. Player and Banker are just the two hands' names — you can back either.
4. Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're ready — the table locks at zero or once everyone is done.
5. The panel deals both hands by fixed rules — there is nothing to decide. The hand closest to 9 wins.

### Counting

- Aces count 1, 2–9 their number, 10 J Q K count 0. Only the last digit of the total counts (7 + 8 = 15 counts as 5).
- A two-card 8 or 9 is a **natural**: both hands stand.

### Third cards (automatic)

- The Player hand draws on 0–5 and stands on 6–7.
- If the Player stood, the Banker draws on 0–5 and stands on 6–7.
- If the Player drew a third card, the Banker draws on 0–2; on 3 unless that card was an 8; on 4 if it was 2–7; on 5 if it was 4–7; on 6 if it was 6–7; and stands on 7.

### Payouts

- **Player**: **1:1**.
- **Banker**: **0.95:1** (5 % commission). In **no-commission** mode a Banker win with 6 pays **1:2** and every other Banker win **1:1**.
- **Tie**: **8:1** (or **9:1**). On a tie, Player and Banker bets are returned (push).
- **Player pair / Banker pair**: that hand's first two cards are the same rank: **11:1**.

### House edge (8 decks)

- Banker 1.06 % (no-commission 1.46 %), Player 1.24 %, Tie 14.36 % at 8:1 (4.84 % at 9:1), pairs 10.36 %. Every coup is dealt from a freshly shuffled shoe.

### Table basics

- You play against the house with play-money credits. Everyone starts with the credits the host sets.
- Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.
- Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up to the maximum.
- Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when everyone with chips down has tapped **Done**, or when the host locks it.
- From **No more bets** until the result, every bet is frozen: no new chips, no undo.
- Wins are paid in whole credits, rounded down.
- If the host closes the table while betting is open, every open bet is refunded. A round that already locked is always played out and paid.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Andar Bahar

*A joker card is turned up — which side gets the matching rank first?*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick a chip in the rack at the bottom. The rack shows only the chips this table allows (between the table minimum and maximum, e.g. 1K, 2K, 5K at a high-roller table), plus **ALL** for everything you have.
3. Tap **ANDAR** (inside) or **BAHAR** (outside). You can also bet on how many cards it takes.
4. Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're ready — the table locks at zero or once everyone is done.
5. At the lock the joker is turned up. Cards are dealt to Andar and Bahar in turn until one matches the joker's **value — any suit** (a 7♥ joker is matched by any 7) — that side wins.

### The deal

- One 52-card deck is shuffled; the top card is the **joker** (the game card).
- Cards are dealt one at a time, alternately, starting with **Andar** (the host may start with Bahar), until a card of the joker's rank appears. The side it lands on wins.
- A match is by **value only — the suit never matters**: with a 7♥ joker the first 7♠, 7♦ or 7♣ wins (and K matches K, A matches A). That is the standard Andar Bahar rule: 3 of the 51 cards left can end the game.
- Host option **Winning card: exact card** — only the joker's identical twin (same value **and** suit) wins. One deck has no second 7♥, so the cards are dealt from a second, fresh shuffled deck; the twin is equally likely anywhere in it, so each side wins exactly half the time, both pay **0.95:1** (house edge 2.5 %) and the card-count bands run to 52.

### Payouts

- The side that gets the first card wins slightly more often (51.5 %), so it pays **0.9:1**; the other side pays **1:1**. With the first card to Andar: Andar 0.9:1, Bahar 1:1.
- House edge: 2.15 % on the first side, 3.00 % on the other.

### Card-count side bets

- Bet on how many cards are dealt (the joker doesn't count, the matching card does):
- 1–5 **2.5:1** · 6–10 **3.3:1** · 11–15 **4.6:1** · 16–25 **3.3:1** · 26–30 **14.5:1** · 31–35 **24.5:1** · 36–40 **49:1** · 41–49 **118:1**.
- Each band pays its fair odds less about 5 % (exact edges 5.1–6.7 %). The host can switch side bets off.

### Table basics

- You play against the house with play-money credits. Everyone starts with the credits the host sets.
- Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.
- Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up to the maximum.
- Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when everyone with chips down has tapped **Done**, or when the host locks it.
- From **No more bets** until the result, every bet is frozen: no new chips, no undo.
- Wins are paid in whole credits, rounded down.
- If the host closes the table while betting is open, every open bet is refunded. A round that already locked is always played out and paid.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Big Six

*Spin the money wheel: bet on the symbol where the clapper stops.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick a chip in the rack at the bottom. The rack shows only the chips this table allows (between the table minimum and maximum, e.g. 1K, 2K, 5K at a high-roller table), plus **ALL** for everything you have.
3. Tap the symbol you think the wheel will stop on: **1**, **2**, **5**, **10**, **20**, **Joker** or **Logo**. Rarer symbols pay more.
4. Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're ready — the table locks at zero or once everyone is done.
5. The panel spins the wheel; the leather clapper picks the winning segment.

### The wheel

- 54 equal segments: 24 × 1, 15 × 2, 7 × 5, 4 × 10, 2 × 20, 1 joker, 1 logo.
- Each segment is equally likely.

### Payouts

- A symbol pays its number: **1:1**, **2:1**, **5:1**, **10:1**, **20:1**.
- **Joker** and **Logo** pay **40:1**.
- House edge: 1 → 11.11 %, 2 → 16.67 %, 5 → 22.22 %, 10 → 18.52 %, 20 → 22.22 %, joker / logo → 24.07 %.

### Table basics

- You play against the house with play-money credits. Everyone starts with the credits the host sets.
- Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.
- Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up to the maximum.
- Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when everyone with chips down has tapped **Done**, or when the host locks it.
- From **No more bets** until the result, every bet is frozen: no new chips, no undo.
- Wins are paid in whole credits, rounded down.
- If the host closes the table while betting is open, every open bet is refunded. A round that already locked is always played out and paid.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Slots

*Your own 3-reel machine: pull the lever and line up symbols.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Pick your **bet per line**. A spin costs bet per line × the number of paylines (set by the host).
3. Pull the **lever** down and let go (or tap **SPIN**). Your phone shows the next spin's sealed hash before you pull.
4. The panel plays everyone's spins in turn: reels stop left to right, wins light up.
5. Your credits update when the last reel stops. Tap the pay table to see what each symbol pays.

### The machine

- 3 reels × 3 rows. Up to 5 **paylines**: 1 middle row, 2 top row, 3 bottom row, 4 and 5 the two diagonals. The host plays 1, 3 or 5 lines.
- Each line pays its best win × your bet per line. Wins on several lines add up.
- Every reel stop is equally likely; the reel strips decide how often each symbol shows.

### Machines

- **Classic fruits**: three of a kind pays (7s 100, bars 40, bells 18, plums 14, oranges 10, lemons 8, cherries 10); one cherry from the left pays 2, two cherries 5.
- **Neon 7s**: the star is **wild** (it stands in for any symbol); three stars 200, gold 7s 100, red 7s 50, blue 7s 25, triple bars 15, double bars 10, bars 5; any mix of 7s 10, any mix of bars 2.
- **Space**: three aliens 200, UFOs 50, rockets 25, planets 15, stars 15, moons 10, comets 5; any mix of ships 4; one star from the left pays 1, two stars 4.
- Pays are × the bet per line. The **Payouts** tab shows the exact table for this machine.

### Return to player

- The RTP is computed exactly from the reel strips and the pay table (every preset 95–96.5 %) and shown in the Payouts tab. **Volatility** (host option) picks the strips: low = frequent small wins, high = rarer, bigger ones.
- There is no shared betting round: each pull is its own provably fair round. Once you pull, that spin is locked.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Texas Hold'em

*No-limit poker: make the best five-card hand, or make everyone else fold.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**. You're dealt into the next hand automatically.
2. Once two or more players are in, a hand is dealt: your **two private cards** appear only on your phone.
3. On your turn choose **Fold**, **Check**, **Call**, **Raise** (slider, ½ pot, pot) or **All-in**. The bar shows your turn clock.
4. Five shared cards come out on the panel — the flop (3), the turn and the river — with a betting round after each.
5. The best five-card hand from your two cards and the five shared cards wins the pot.

### Blinds and betting

- The button moves one seat every hand. The two players after it post the **small** and **big blind** (5 / 10 by default). Heads-up, the button posts the small blind and acts first before the flop.
- No-limit: a bet is at least the big blind; a raise is at least the size of the last bet or raise. You can go all-in for any amount at any time.
- A short all-in raise doesn't reopen the betting for players who already acted.
- Blinds can double every N hands (host option). An expired turn **checks** if it's free, otherwise **folds**.

### Winning

- If everyone else folds you win the pot without showing.
- Otherwise, after the river every live hand is shown; the best five of seven cards wins. Ties split the pot (odd chip to the first winner left of the button).
- **Side pots**: an all-in player can only win what they matched from each opponent; the rest forms side pots for the others.
- Rake (host option, default 0): a share of each contested pot, only after a flop, capped.

### Hand ranking (best first)

- Straight flush · Four of a kind · Full house · Flush · Straight · Three of a kind · Two pair · One pair · High card. An ace plays high or low in a straight (A-2-3-4-5).

### Table basics

- You play against the other players, not the house: every chip you bet goes into the pot, and the winner takes it. The house only deals (and takes a rake only if the host sets one).
- You are dealt into the next hand when you sit down. **Sit out next hand** / **Deal me in** toggles it.
- A hand starts once at least two players are in (a short countdown first).
- Your cards are only ever on your own phone; the panel shows the shared table.
- Every turn has a timer. When it runs out the game makes the safe move for you.
- Players who can't cover the big blind (Hold'em) or the boot (Teen Patti) sit out until the host tops them up.
- If the host closes the table mid-hand, the hand is void and every chip goes back to its owner.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Teen Patti

*Three-card brag, the Indian way: bet blind or seen, then show.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**. You're dealt into the next hand automatically.
2. Everyone puts in the **boot**; you get three cards face down — you start **blind**.
3. Tap **See cards** any time to look (you then play **seen**, at double the stake).
4. On your turn: **Chaal** (call), **Raise**, **Pack** (fold), and with two players left **Show**; seen players can ask the previous player for a **Sideshow**.
5. The last player in, or the best hand at the show, takes the pot.

### Betting

- The **stake** starts at the boot. **Chaal**: a blind player puts in **1×** the stake, a seen player **2×**. **Raise** doubles it: blind 2×, seen 4×, and the stake doubles.
- The stake never goes above the **chaal limit**. After 4 blind bets (host option) you must see your cards.
- **Pack** folds; your chips stay in the pot. An expired turn packs.

### Show and sideshow

- **Show**: only when two players are left. Blind pays 1× the stake, seen pays 2×. A seen player can't ask a blind player for a show. Equal hands: the player who did **not** pay for the show wins.
- **Sideshow**: with three or more players left, a seen player pays their chaal and asks the previous player still in (seen, already bet) to compare privately. They may refuse; if they accept, the lower hand packs — equal hands, the asker packs.
- When the pot reaches the **pot limit**, everyone left shows and the best hand wins (exact ties split).

### Hand ranking (best first)

- **Trail** (three of a kind) · **Pure sequence** (straight flush) · **Sequence** (straight) · **Colour** (flush) · **Pair** · **High card**.
- A-K-Q is the top sequence and A-2-3 the second.

### Table basics

- You play against the other players, not the house: every chip you bet goes into the pot, and the winner takes it. The house only deals (and takes a rake only if the host sets one).
- You are dealt into the next hand when you sit down. **Sit out next hand** / **Deal me in** toggles it.
- A hand starts once at least two players are in (a short countdown first).
- Your cards are only ever on your own phone; the panel shows the shared table.
- Every turn has a timer. When it runs out the game makes the safe move for you.
- Players who can't cover the big blind (Hold'em) or the boot (Teen Patti) sit out until the host tops them up.
- If the host closes the table mid-hand, the hand is void and every chip goes back to its owner.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Housie

*Tambola, the Indian way: buy tickets, the caller draws 1–90 — first to complete a pattern wins.*

**How to play**

1. Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**.
2. Buy **1 or more tickets** with the **+ / −** stepper (the host sets the price and the limit); the first ticket sold starts the buy-in clock. Tap **I'm ready** when you're done.
3. When the calling starts your tickets appear on your phone. The caller draws a number every few seconds; the panel shows it big, your phone **daubs** it on your tickets (turn auto-daub off to mark by hand).
4. Complete a pattern — **Early Five**, a **line**, the **Four Corners** or the **Full House** — and tap its glowing **Claim** button before the next number is called.
5. The server checks your ticket against the numbers called. A Full House ends the game; the prizes are paid from the pot.

### Tickets

- A ticket is a 3 × 9 grid with **15 numbers, 5 in every row**. Column 1 holds 1–9, column 2 10–19 … column 9 holds 80–90; each column has 1–3 numbers, smallest at the top.
- Tickets are sold only during the buy-in. Once the calling starts nobody can buy, sell or swap a ticket.
- Every ticket and the whole order of the 90 calls come from the sealed round (see Provably fair) — the host can't pick them.

### Prizes

- **Early Five**: the first ticket with any 5 numbers called.
- **Top Line**, **Middle Line**, **Bottom Line**: all 5 numbers of that row.
- **Four Corners**: the first and last numbers of the top and bottom rows.
- **Full House**: all 15 numbers. It ends the game.
- The host can switch any prize off. The game also ends once every prize is won, or after all 90 numbers.

### Claims

- Tap **Claim** for a prize: the server checks that ticket against the numbers called so far.
- A false claim is a **bogey**: it is rejected. The host may add a penalty — that ticket can't win that prize any more, or the ticket is out of the game.
- Claims made on the **same call** (before the next number) share the prize, split per winning ticket. After the next number is called the prize is closed.
- The host can switch on **auto-claim**: the server claims for everyone the moment a pattern completes.

### Payouts

- Players play for the pot: every ticket sold goes in. The house keeps only the **rake** the host sets (0 % by default).
- The rest is the prize pool, split by the prize shares (host option; default: Early Five **10 %**, Top Line **15 %**, Middle Line **15 %**, Bottom Line **15 %**, Four Corners **10 %**, Full House **35 %**).
- Shares are of the enabled prizes; credits are rounded down and the odd credits go to the Full House.
- A prize nobody claims is shared back to every ticket holder in proportion to their tickets.
- If the host closes the table before the game is decided, every ticket is refunded.

### Provably fair

- Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.
- Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the result. The house never looks at bets, balances or history.
- After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result yourself.

## Rock Paper Scissors

*The party classic, 1 v 1: ROCK… PAPER… SCISSORS… SHOOT!*

**How to play**

1. Scan the QR code on the panel, pick a name, colour and character, and join.
2. When it's your match, tap one of the three big hands: **Rock**, **Paper** or **Scissors**. Your pick is locked and stays secret.
3. Pick before the timer runs out (8 seconds by default), or a random hand is picked for you.
4. The panel pumps the fists and reveals both hands at once on SHOOT!
5. Win enough rounds to take the match; in a tournament, keep winning to become champion.

### Who wins

- **Rock** blunts **Scissors**, **Scissors** cut **Paper**, **Paper** wraps **Rock**.
- The same hand on both sides is a draw: nobody scores — just pick again in the next round.

### Matches

- A match is best of 1, 3, 5 or 7 rounds (the host picks; best of 3 by default): the first to win a majority takes it.
- Modes: **You vs AI**, **1 v 1** (keyboard + phone, or two phones), **Tournament** (3–8 players) and **AI vs AI** (the attract screen).

### Tournaments

- **Knockout**: a random bracket; byes go straight through when the field isn't a power of two. Lose a match and you're out.
- **Round robin**: everyone plays everyone once. Standings: match wins, then round difference, then rounds won.
- Matches between two AI players are simulated so the party keeps moving.

### Fair play

- Picks stay secret until both hands are revealed — phones only learn who has locked in.
- The AI picks from a secure random source at the start of each round and only learns from finished rounds: it never sees your current pick.

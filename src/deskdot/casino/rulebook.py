"""The rulebook: "How to play" and the rules of every casino game (and Rock Paper Scissors), in ONE place.

The phone casino page, the RPS phone controller and the studio's casino wings all show this text, and
docs/CASINO_RULES.md is generated from it (``uv run python -m deskdot.casino.rulebook > docs/CASINO_RULES.md``;
`tests/test_rulebook.py` checks the doc is up to date). Every payout here must match the paytables in
``casino/games/*.py`` — the tests check the key ones against the real `Spot` table.

Text is plain, with ``**bold**`` as the only markup (phones and the studio render it). Keys are the game ids
(`CasinoGame.id`, ``"rps"`` for Rock Paper Scissors).
"""

from __future__ import annotations

import sys
from typing import Any

Section = tuple[str, tuple[str, ...]]

#: shared by every house-banked table (roulette, 7 up 7 down, baccarat, andar bahar, big six, blackjack)
HOUSE_BASICS: Section = (
    "Table basics",
    (
        "You play against the house with play-money credits. Everyone starts with the credits the host sets.",
        "Payouts are written **to 1**: a 2:1 win gives back your stake plus twice your stake.",
        "Every spot has a minimum and a maximum bet (set by the host). A chip above the maximum tops the spot up "
        "to the maximum.",
        "Betting opens with no clock: **the first chip starts the countdown**. The round also locks early when "
        "everyone with chips down has tapped **Done**, or when the host locks it.",
        "From **No more bets** until the result, every bet is frozen: no new chips, no undo.",
        "Wins are paid in whole credits, rounded down.",
        "If the host closes the table while betting is open, every open bet is refunded. A round that already "
        "locked is always played out and paid.",
    ),
)

#: shared by the player-vs-player card tables (Texas Hold'em, Teen Patti)
PVP_BASICS: Section = (
    "Table basics",
    (
        "You play against the other players, not the house: every chip you bet goes into the pot, and the winner "
        "takes it. The house only deals (and takes a rake only if the host sets one).",
        "You are dealt into the next hand when you sit down. **Sit out next hand** / **Deal me in** toggles it.",
        "A hand starts once at least two players are in (a short countdown first).",
        "Your cards are only ever on your own phone; the panel shows the shared table.",
        "Every turn has a timer. When it runs out the game makes the safe move for you.",
        "Players who can't cover the big blind (Hold'em) or the boot (Teen Patti) sit out until the host tops "
        "them up.",
        "If the host closes the table mid-hand, the hand is void and every chip goes back to its owner.",
    ),
)

FAIRNESS: Section = (
    "Provably fair",
    (
        "Before betting opens the panel seals the round: it publishes the SHA-256 hash of a secret server seed.",
        "Your phone's own seed is mixed in when betting closes, so nobody — not even the host — can pick the "
        "result. The house never looks at bets, balances or history.",
        "After the round the seed is revealed. Tap your avatar → **Verify on this phone** to recompute the result "
        "yourself.",
    ),
)

JOIN = "Scan the QR code on the panel with your phone camera, pick a name, colour and character, and tap **Sit down**."
CHIPS = "Pick a chip value in the rack at the bottom (1, 5, 25, 100, 500 or ALL)."
LOCK = (
    "Your first chip starts the countdown. **Undo**, **Clear** and **Rebet** fix your bets; tap **Done** when you're "
    "ready — the table locks at zero or once everyone is done."
)

# --------------------------------------------------------------------------------------------- the guides
GUIDES: dict[str, dict[str, Any]] = {
    "roulette": {
        "title": "Roulette",
        "tagline": "Guess where the ball lands: one number, a group of numbers, or a colour.",
        "how": (
            JOIN,
            CHIPS,
            "Tap the table to bet: a number for a straight bet, the line between two numbers for a split, a "
            "corner for four numbers, or an outside box (red/black, odd/even, dozens, columns). Hold a finger on "
            "a spot to see what it covers and what it pays.",
            LOCK,
            "**No more bets** — the panel spins the wheel. Winning bets are paid to your credits automatically.",
        ),
        "rules": (
            (
                "The wheel",
                (
                    "**European** (default): 37 pockets, 0–36. **American**: 38 pockets, 0, 00 and 1–36. The host "
                    "picks the wheel.",
                    "18 numbers are red, 18 black; 0 and 00 are green. The ball lands in one pocket; every bet "
                    "that covers that number wins.",
                ),
            ),
            (
                "Inside bets",
                (
                    "**Straight** — one number: pays **35:1**.",
                    "**Split** — two touching numbers (also 0/1, 0/2, 0/3, and 0/00 on the American wheel): "
                    "pays **17:1**.",
                    "**Street** — a row of three (also the trios 0-1-2 and 0-2-3; American 0-00-2 and 00-2-3): "
                    "pays **11:1**.",
                    "**Corner** — four numbers in a square: pays **8:1**.",
                    "**Six line** — two rows, six numbers: pays **5:1**.",
                    "**First four** 0-1-2-3 (European only): pays **8:1**. **Top line** 0-00-1-2-3 (American "
                    "only): pays **6:1**.",
                ),
            ),
            (
                "Outside bets",
                (
                    "**Dozen** (1–12, 13–24, 25–36) and **Column**: pay **2:1**.",
                    "**Red / Black**, **Odd / Even**, **1–18 / 19–36**: pay **1:1**.",
                    "0 and 00 are none of these: every outside bet loses on a zero.",
                    "**La Partage** (host option, European only): when the ball lands on 0, even-money bets get "
                    "half their stake back.",
                ),
            ),
            (
                "House edge",
                (
                    "European: **2.70 %** on every bet (1.35 % on even-money bets with La Partage).",
                    "American: **5.26 %** on every bet, **7.89 %** on the top line.",
                ),
            ),
            HOUSE_BASICS,
            FAIRNESS,
        ),
    },
    "sevens": {
        "title": "7 Up 7 Down",
        "tagline": "Two dice: will the total be under 7, exactly 7, or over 7?",
        "how": (
            JOIN,
            CHIPS,
            "Tap one of the three zones: **UNDER 7**, **LUCKY 7** or **OVER 7**. You can bet on more than one.",
            LOCK,
            "The panel rolls two dice. The zone that matches the total pays out.",
        ),
        "rules": (
            (
                "Bets and payouts",
                (
                    "**Under 7** — the total is 2, 3, 4, 5 or 6: pays **1:1**.",
                    "**Over 7** — the total is 8, 9, 10, 11 or 12: pays **1:1**.",
                    "**Lucky 7** — the total is exactly 7: pays **4:1** (or **5:1** if the host sets it).",
                    "A 7 loses both Under and Over; any other total loses Lucky 7.",
                ),
            ),
            (
                "Odds",
                (
                    "15 of the 36 dice combinations are under 7, 15 are over, 6 make 7.",
                    "House edge: **16.67 %** on Under / Over and on Lucky 7 at 4:1; Lucky 7 at 5:1 is a fair bet "
                    "(0 %).",
                ),
            ),
            HOUSE_BASICS,
            FAIRNESS,
        ),
    },
    "blackjack": {
        "title": "Blackjack",
        "tagline": "Beat the dealer: get closer to 21 without going over.",
        "how": (
            JOIN,
            "Pick a chip and tap the betting circle. " + LOCK,
            "Everyone gets two cards face up; the dealer shows one card. Your hand total is on your phone.",
            "On your turn tap **Hit** (another card), **Stand**, **Double** (double the bet, take exactly one "
            "card), **Split** (a pair into two hands) or **Surrender** (give up half). Only legal moves light up.",
            "When everyone has played, the dealer turns the hidden card and draws. Wins are paid automatically.",
        ),
        "rules": (
            (
                "Card values",
                (
                    "2–10 count their number, J Q K count 10, an ace counts 11 or 1 (a hand with an ace counted "
                    "as 11 is **soft**).",
                    "**Blackjack** is an ace and a 10-value card as your first two cards. 21 after a split is not "
                    "a blackjack.",
                    "Over 21 is a **bust**: the hand loses at once, even if the dealer busts later.",
                ),
            ),
            (
                "Payouts",
                (
                    "Win: **1:1**. Blackjack: **3:2** (or **6:5** if the host sets it). A tie (**push**) returns "
                    "your bet.",
                    "**Insurance**: when the dealer shows an ace you may bet half your bet that the dealer has "
                    "blackjack; it pays **2:1**. The default is no insurance.",
                    "Payouts are rounded down to whole credits — bet even amounts for an exact 3:2.",
                ),
            ),
            (
                "Your moves",
                (
                    "**Double**: on your first two cards (any two by default, or only a hard 9, 10 or 11 if the "
                    "host sets it); you get exactly one more card. Doubling after a split is a host option (on by "
                    "default).",
                    "**Split**: two cards of the same value (10 and J count) become two hands, each with your "
                    "bet. Up to 3 splits (4 hands) by default. Split aces get one card each and can't be split "
                    "again.",
                    "**Surrender** (late, on by default): as your first decision on an unsplit hand, give up and "
                    "get half your bet back.",
                    "Doubles, splits and insurance are paid from your credits during play. When your turn timer "
                    "runs out you **stand**.",
                ),
            ),
            (
                "The dealer",
                (
                    "Draws to 17, and **stands on soft 17** (or hits it, if the host sets it). The dealer has no "
                    "choices.",
                    "**Peek** (on by default): with an ace or a 10 showing, the dealer checks for blackjack before "
                    "anyone plays, so you can only lose your first bet to it. Without peek, a dealer blackjack "
                    "takes doubles and splits too.",
                    "The shoe holds 6 decks by default (1–8). A new shoe starts when the cut card comes out.",
                ),
            ),
            HOUSE_BASICS,
            FAIRNESS,
        ),
    },
    "baccarat": {
        "title": "Baccarat",
        "tagline": "Bet on which hand ends closer to 9: Player or Banker — or a tie.",
        "how": (
            JOIN,
            CHIPS,
            "Tap **PLAYER**, **BANKER** or **TIE**, and if you like a pair side bet. Player and Banker are just "
            "the two hands' names — you can back either.",
            LOCK,
            "The panel deals both hands by fixed rules — there is nothing to decide. The hand closest to 9 wins.",
        ),
        "rules": (
            (
                "Counting",
                (
                    "Aces count 1, 2–9 their number, 10 J Q K count 0. Only the last digit of the total counts "
                    "(7 + 8 = 15 counts as 5).",
                    "A two-card 8 or 9 is a **natural**: both hands stand.",
                ),
            ),
            (
                "Third cards (automatic)",
                (
                    "The Player hand draws on 0–5 and stands on 6–7.",
                    "If the Player stood, the Banker draws on 0–5 and stands on 6–7.",
                    "If the Player drew a third card, the Banker draws on 0–2; on 3 unless that card was an 8; on "
                    "4 if it was 2–7; on 5 if it was 4–7; on 6 if it was 6–7; and stands on 7.",
                ),
            ),
            (
                "Payouts",
                (
                    "**Player**: **1:1**.",
                    "**Banker**: **0.95:1** (5 % commission). In **no-commission** mode a Banker win with 6 pays "
                    "**1:2** and every other Banker win **1:1**.",
                    "**Tie**: **8:1** (or **9:1**). On a tie, Player and Banker bets are returned (push).",
                    "**Player pair / Banker pair**: that hand's first two cards are the same rank: **11:1**.",
                ),
            ),
            (
                "House edge (8 decks)",
                (
                    "Banker 1.06 % (no-commission 1.46 %), Player 1.24 %, Tie 14.36 % at 8:1 (4.84 % at 9:1), "
                    "pairs 10.36 %. Every coup is dealt from a freshly shuffled shoe.",
                ),
            ),
            HOUSE_BASICS,
            FAIRNESS,
        ),
    },
    "andarbahar": {
        "title": "Andar Bahar",
        "tagline": "A joker card is turned up — which side gets the matching rank first?",
        "how": (
            JOIN,
            CHIPS,
            "Tap **ANDAR** (inside) or **BAHAR** (outside). You can also bet on how many cards it takes.",
            LOCK,
            "At the lock the joker is turned up. Cards are dealt to Andar and Bahar in turn until one matches the "
            "joker's rank — that side wins.",
        ),
        "rules": (
            (
                "The deal",
                (
                    "One 52-card deck is shuffled; the top card is the **joker** (the game card).",
                    "Cards are dealt one at a time, alternately, starting with **Andar** (the host may start with "
                    "Bahar), until a card of the joker's rank appears. The side it lands on wins.",
                ),
            ),
            (
                "Payouts",
                (
                    "The side that gets the first card wins slightly more often (51.5 %), so it pays **0.9:1**; "
                    "the other side pays **1:1**. With the first card to Andar: Andar 0.9:1, Bahar 1:1.",
                    "House edge: 2.15 % on the first side, 3.00 % on the other.",
                ),
            ),
            (
                "Card-count side bets",
                (
                    "Bet on how many cards are dealt (the joker doesn't count, the matching card does):",
                    "1–5 **2.5:1** · 6–10 **3.3:1** · 11–15 **4.6:1** · 16–25 **3.3:1** · 26–30 **14.5:1** · "
                    "31–35 **24.5:1** · 36–40 **49:1** · 41–49 **118:1**.",
                    "Each band pays its fair odds less about 5 % (exact edges 5.1–6.7 %). The host can switch "
                    "side bets off.",
                ),
            ),
            HOUSE_BASICS,
            FAIRNESS,
        ),
    },
    "bigsix": {
        "title": "Big Six",
        "tagline": "Spin the money wheel: bet on the symbol where the clapper stops.",
        "how": (
            JOIN,
            CHIPS,
            "Tap the symbol you think the wheel will stop on: **1**, **2**, **5**, **10**, **20**, **Joker** or "
            "**Logo**. Rarer symbols pay more.",
            LOCK,
            "The panel spins the wheel; the leather clapper picks the winning segment.",
        ),
        "rules": (
            (
                "The wheel",
                (
                    "54 equal segments: 24 × 1, 15 × 2, 7 × 5, 4 × 10, 2 × 20, 1 joker, 1 logo.",
                    "Each segment is equally likely.",
                ),
            ),
            (
                "Payouts",
                (
                    "A symbol pays its number: **1:1**, **2:1**, **5:1**, **10:1**, **20:1**.",
                    "**Joker** and **Logo** pay **40:1**.",
                    "House edge: 1 → 11.11 %, 2 → 16.67 %, 5 → 22.22 %, 10 → 18.52 %, 20 → 22.22 %, joker / "
                    "logo → 24.07 %.",
                ),
            ),
            HOUSE_BASICS,
            FAIRNESS,
        ),
    },
    "slots": {
        "title": "Slots",
        "tagline": "Your own 3-reel machine: pull the lever and line up symbols.",
        "how": (
            JOIN,
            "Pick your **bet per line**. A spin costs bet per line × the number of paylines (set by the host).",
            "Pull the **lever** down and let go (or tap **SPIN**). Your phone shows the next spin's sealed hash "
            "before you pull.",
            "The panel plays everyone's spins in turn: reels stop left to right, wins light up.",
            "Your credits update when the last reel stops. Tap the pay table to see what each symbol pays.",
        ),
        "rules": (
            (
                "The machine",
                (
                    "3 reels × 3 rows. Up to 5 **paylines**: 1 middle row, 2 top row, 3 bottom row, 4 and 5 the "
                    "two diagonals. The host plays 1, 3 or 5 lines.",
                    "Each line pays its best win × your bet per line. Wins on several lines add up.",
                    "Every reel stop is equally likely; the reel strips decide how often each symbol shows.",
                ),
            ),
            (
                "Machines",
                (
                    "**Classic fruits**: three of a kind pays (7s 100, bars 40, bells 18, plums 14, oranges 10, "
                    "lemons 8, cherries 10); one cherry from the left pays 2, two cherries 5.",
                    "**Neon 7s**: the star is **wild** (it stands in for any symbol); three stars 200, gold 7s "
                    "100, red 7s 50, blue 7s 25, triple bars 15, double bars 10, bars 5; any mix of 7s 10, any "
                    "mix of bars 2.",
                    "**Space**: three aliens 200, UFOs 50, rockets 25, planets 15, stars 15, moons 10, comets 5; "
                    "any mix of ships 4; one star from the left pays 1, two stars 4.",
                    "Pays are × the bet per line. The **Payouts** tab shows the exact table for this machine.",
                ),
            ),
            (
                "Return to player",
                (
                    "The RTP is computed exactly from the reel strips and the pay table (every preset 95–96.5 %) "
                    "and shown in the Payouts tab. **Volatility** (host option) picks the strips: low = frequent "
                    "small wins, high = rarer, bigger ones.",
                    "There is no shared betting round: each pull is its own provably fair round. Once you pull, "
                    "that spin is locked.",
                ),
            ),
            FAIRNESS,
        ),
    },
    "holdem": {
        "title": "Texas Hold'em",
        "tagline": "No-limit poker: make the best five-card hand, or make everyone else fold.",
        "how": (
            JOIN + " You're dealt into the next hand automatically.",
            "Once two or more players are in, a hand is dealt: your **two private cards** appear only on your "
            "phone.",
            "On your turn choose **Fold**, **Check**, **Call**, **Raise** (slider, ½ pot, pot) or **All-in**. The "
            "bar shows your turn clock.",
            "Five shared cards come out on the panel — the flop (3), the turn and the river — with a betting "
            "round after each.",
            "The best five-card hand from your two cards and the five shared cards wins the pot.",
        ),
        "rules": (
            (
                "Blinds and betting",
                (
                    "The button moves one seat every hand. The two players after it post the **small** and **big "
                    "blind** (5 / 10 by default). Heads-up, the button posts the small blind and acts first "
                    "before the flop.",
                    "No-limit: a bet is at least the big blind; a raise is at least the size of the last bet or "
                    "raise. You can go all-in for any amount at any time.",
                    "A short all-in raise doesn't reopen the betting for players who already acted.",
                    "Blinds can double every N hands (host option). An expired turn **checks** if it's free, "
                    "otherwise **folds**.",
                ),
            ),
            (
                "Winning",
                (
                    "If everyone else folds you win the pot without showing.",
                    "Otherwise, after the river every live hand is shown; the best five of seven cards wins. "
                    "Ties split the pot (odd chip to the first winner left of the button).",
                    "**Side pots**: an all-in player can only win what they matched from each opponent; the rest "
                    "forms side pots for the others.",
                    "Rake (host option, default 0): a share of each contested pot, only after a flop, capped.",
                ),
            ),
            (
                "Hand ranking (best first)",
                (
                    "Straight flush · Four of a kind · Full house · Flush · Straight · Three of a kind · Two "
                    "pair · One pair · High card. An ace plays high or low in a straight (A-2-3-4-5).",
                ),
            ),
            PVP_BASICS,
            FAIRNESS,
        ),
    },
    "teenpatti": {
        "title": "Teen Patti",
        "tagline": "Three-card brag, the Indian way: bet blind or seen, then show.",
        "how": (
            JOIN + " You're dealt into the next hand automatically.",
            "Everyone puts in the **boot**; you get three cards face down — you start **blind**.",
            "Tap **See cards** any time to look (you then play **seen**, at double the stake).",
            "On your turn: **Chaal** (call), **Raise**, **Pack** (fold), and with two players left **Show**; "
            "seen players can ask the previous player for a **Sideshow**.",
            "The last player in, or the best hand at the show, takes the pot.",
        ),
        "rules": (
            (
                "Betting",
                (
                    "The **stake** starts at the boot. **Chaal**: a blind player puts in **1×** the stake, a seen "
                    "player **2×**. **Raise** doubles it: blind 2×, seen 4×, and the stake doubles.",
                    "The stake never goes above the **chaal limit**. After 4 blind bets (host option) you must "
                    "see your cards.",
                    "**Pack** folds; your chips stay in the pot. An expired turn packs.",
                ),
            ),
            (
                "Show and sideshow",
                (
                    "**Show**: only when two players are left. Blind pays 1× the stake, seen pays 2×. A seen "
                    "player can't ask a blind player for a show. Equal hands: the player who did **not** pay for "
                    "the show wins.",
                    "**Sideshow**: with three or more players left, a seen player pays their chaal and asks the "
                    "previous player still in (seen, already bet) to compare privately. They may refuse; if they "
                    "accept, the lower hand packs — equal hands, the asker packs.",
                    "When the pot reaches the **pot limit**, everyone left shows and the best hand wins (exact "
                    "ties split).",
                ),
            ),
            (
                "Hand ranking (best first)",
                (
                    "**Trail** (three of a kind) · **Pure sequence** (straight flush) · **Sequence** (straight) "
                    "· **Colour** (flush) · **Pair** · **High card**.",
                    "A-K-Q is the top sequence and A-2-3 the second.",
                ),
            ),
            PVP_BASICS,
            FAIRNESS,
        ),
    },
    "rps": {
        "title": "Rock Paper Scissors",
        "tagline": "The party classic, 1 v 1: ROCK… PAPER… SCISSORS… SHOOT!",
        "how": (
            "Scan the QR code on the panel, pick a name, colour and character, and join.",
            "When it's your match, tap one of the three big hands: **Rock**, **Paper** or **Scissors**. Your pick "
            "is locked and stays secret.",
            "Pick before the timer runs out (8 seconds by default), or a random hand is picked for you.",
            "The panel pumps the fists and reveals both hands at once on SHOOT!",
            "Win enough rounds to take the match; in a tournament, keep winning to become champion.",
        ),
        "rules": (
            (
                "Who wins",
                (
                    "**Rock** blunts **Scissors**, **Scissors** cut **Paper**, **Paper** wraps **Rock**.",
                    "The same hand on both sides is a draw: nobody scores — just pick again in the next round.",
                ),
            ),
            (
                "Matches",
                (
                    "A match is best of 1, 3, 5 or 7 rounds (the host picks; best of 3 by default): the first to "
                    "win a majority takes it.",
                    "Modes: **You vs AI**, **1 v 1** (keyboard + phone, or two phones), **Tournament** (3–8 "
                    "players) and **AI vs AI** (the attract screen).",
                ),
            ),
            (
                "Tournaments",
                (
                    "**Knockout**: a random bracket; byes go straight through when the field isn't a power of "
                    "two. Lose a match and you're out.",
                    "**Round robin**: everyone plays everyone once. Standings: match wins, then round "
                    "difference, then rounds won.",
                    "Matches between two AI players are simulated so the party keeps moving.",
                ),
            ),
            (
                "Fair play",
                (
                    "Picks stay secret until both hands are revealed — phones only learn who has locked in.",
                    "The AI picks from a secure random source at the start of each round and only learns from "
                    "finished rounds: it never sees your current pick.",
                ),
            ),
        ),
    },
}

CASINO_ORDER = (
    "roulette",
    "sevens",
    "blackjack",
    "baccarat",
    "andarbahar",
    "bigsix",
    "slots",
    "holdem",
    "teenpatti",
)


def guide(game_id: str) -> dict[str, Any] | None:
    """One game's guide as JSON: ``{id, title, tagline, how: [step], rules: [{h, items: [text]}]}``."""
    g = GUIDES.get(game_id)
    if g is None:
        return None
    return {
        "id": game_id,
        "title": g["title"],
        "tagline": g["tagline"],
        "how": list(g["how"]),
        "rules": [{"h": h, "items": list(items)} for h, items in g["rules"]],
    }


def casino_rulebook() -> dict[str, dict[str, Any]]:
    """Every casino game's guide, keyed by game id (a casino room can switch tables, so phones get them all)."""
    return {k: g for k in CASINO_ORDER if (g := guide(k)) is not None}


def rulebook_for(app_cls: Any) -> dict[str, dict[str, Any]]:
    """What a phone's ``hello`` carries (sent once per connection, not with every state push): every casino
    game's guide for a casino room, the app's own guide for a game that has one (RPS), else nothing."""
    if getattr(app_cls, "category", None) == "casino":
        return casino_rulebook()
    g = guide(str(getattr(app_cls, "id", "")))
    return {g["id"]: g} if g else {}


def markdown() -> str:
    """docs/CASINO_RULES.md, generated from `GUIDES`."""
    out = [
        "# Casino rulebook",
        "",
        "How to play and the rules of every casino game and Rock Paper Scissors. **Generated** from",
        "`src/deskdot/casino/rulebook.py` (the same text the phones and the studio show) — edit that file, then run",
        "`uv run python -m deskdot.casino.rulebook > docs/CASINO_RULES.md`. Design spec: [CASINO.md](CASINO.md).",
        "",
    ]
    for k in (*CASINO_ORDER, "rps"):
        g = GUIDES[k]
        out += [f"## {g['title']}", "", f"*{g['tagline']}*", "", "**How to play**", ""]
        out += [f"{i}. {s}" for i, s in enumerate(g["how"], 1)]
        out.append("")
        for h, items in g["rules"]:
            out += [f"### {h}", ""]
            out += [f"- {s}" for s in items]
            out.append("")
    return "\n".join(out)


if __name__ == "__main__":  # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[attr-defined]
    sys.stdout.write(markdown())

import { useEffect } from "react";
import { sfx, stopSfx } from "../../lib/sound";
import { localChipAt } from "./chipfx";
import { type CasinoStatus, secondsLeft, useCasino } from "./state";

/**
 * The casino table's sound (docs/STUDIO_UI.md "Sound"), derived only from the public status the studio already
 * receives — so the host hears every player's chips too: chips going down (totals rising), the bell when betting
 * opens, the last three seconds ticking, "no more bets", the game's own reveal (wheel / reels / dice / cards), and
 * the result (win · big win · lose). Mounted by CasinoStage, so it only sounds while casino mode is open.
 */
type Kind = "wheel" | "reels" | "dice" | "cards";
const kindOf = (game: string | undefined): Kind =>
  game === "roulette" || game === "bigsix" ? "wheel" : game === "slots" ? "reels" : game === "sevens" ? "dice" : "cards";
const sum = (t: Record<string, number> | undefined) => Object.values(t ?? {}).reduce((a, b) => a + (Number(b) || 0), 0);
const later = (ms: number, f: () => void) => window.setTimeout(f, ms);

export function useCasinoSounds(app: string | null) {
  useEffect(() => {
    if (!app) return;
    let prev: CasinoStatus | null = useCasino.getState().status;
    let lastTick = 0;
    const timers: number[] = [];
    const off = useCasino.subscribe((s, p) => {
      if (s.entered !== p.entered && s.entered) sfx("chips-stack", { volume: 0.7 }); // the entrance chip cascade
      const st = s.status;
      if (!st || st === prev) return;
      const was = prev;
      prev = st;
      if (!was || was.game !== st.game) return;
      const kind = kindOf(st.game);
      const minBet = st.house?.min_bet ?? 1;
      // chips placed (anyone's): the table's totals going up
      if (st.phase === "betting" && was.phase === "betting") {
        const d = sum(st.totals) - sum(was.totals);
        const mine = performance.now() - localChipAt < 900; // the host's own chips clack when their flight lands (chipfx)
        if (d > 0 && !mine) sfx(d >= minBet * 5 ? "chips-stack" : "chip", { pan: Math.random() * 0.8 - 0.4 });
        else if (d < 0 && !mine) sfx("chip", { volume: 0.5 });
      }
      if (st.phase === was.phase && st.round === was.round) return;
      const ph = st.phase;
      if (ph === "betting") sfx("round-open");
      else if (ph === "locked") sfx("no-more-bets");
      else if (ph === "spinning") sfx(kind === "reels" ? "reel-spin" : kind === "dice" ? "dice-roll" : "wheel-spin");
      else if (ph === "dealing") {
        [0, 140, 280, 420].forEach((ms) => timers.push(later(ms, () => sfx("card-deal", { pan: (ms / 420) * 0.6 - 0.3 }))));
      } else if (ph === "action") sfx("card-flip");
      else if (ph === "result") {
        let at = 0;
        if (kind === "wheel") {
          stopSfx("wheel-spin");
          sfx("ball-drop");
          at = 520;
        } else if (kind === "reels") {
          stopSfx("reel-spin");
          [0, 170, 340].forEach((ms) => timers.push(later(ms, () => sfx("reel-stop", { pan: ms / 340 - 0.5 }))));
          at = 420;
        } else if (kind === "cards") {
          sfx("card-flip");
          at = 160;
        }
        const winners = st.result?.winners ?? [];
        const best = winners.reduce((m, w) => Math.max(m, w.net), 0);
        const anyBets = sum(was.totals) > 0 || (was.bettors?.length ?? 0) > 0;
        timers.push(later(at, () => {
          if (winners.length) sfx(best >= minBet * 10 ? "big-win" : "win");
          else if (anyBets) sfx("lose");
        }));
      }
    });
    // the last three seconds of betting tick
    const iv = window.setInterval(() => {
      const { status, at } = useCasino.getState();
      if (status?.phase !== "betting" || status.paused) return;
      const left = secondsLeft(status.ends_in, at, status.clock?.ends_at);
      const n = left == null ? 0 : Math.ceil(left);
      if (n >= 1 && n <= 3 && n !== lastTick) sfx("tick");
      lastTick = n;
    }, 120);
    return () => {
      off();
      clearInterval(iv);
      timers.forEach(clearTimeout);
      stopSfx("wheel-spin");
      stopSfx("reel-spin");
    };
  }, [app]);
}

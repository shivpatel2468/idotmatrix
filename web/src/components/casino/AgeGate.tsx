import { useEffect, useState } from "react";
import { CASINO_GATE, acceptCasinoGate, casinoGateAccepted, casinoGateDeclined, declineCasinoGate } from "../../lib/legal";
import { leaveCasino } from "./state";

/**
 * The play-money / 18+ gate (legal review L4), shown once per browser when the studio enters the casino view.
 * Accepting is remembered per device (lib/legal.ts CASINO_GATE_KEY); declining leaves the casino and is remembered
 * for the session, so another casino table doesn't pull the studio back in (the "Back to the casino" key asks again).
 */
export function CasinoAgeGate() {
  const [open, setOpen] = useState(() => !casinoGateAccepted());
  useEffect(() => {
    if (open && casinoGateDeclined()) leaveCasino();
  }, [open]);
  if (!open || casinoGateDeclined()) return null;
  const accept = () => {
    acceptCasinoGate();
    setOpen(false);
  };
  const leave = () => {
    declineCasinoGate();
    leaveCasino();
  };
  return (
    <div className="cz-gate" role="dialog" aria-modal="true" aria-labelledby="cz-gate-t" onKeyDown={(e) => e.key === "Escape" && leave()}>
      <div className="cz-gate-card">
        <div className="cz-gate-chip" aria-hidden><span>18+</span></div>
        <h2 id="cz-gate-t">{CASINO_GATE.title}</h2>
        <ul className="cz-gate-points">
          <li><span className="ok">✓</span> Free play chips, set by the host</li>
          <li><span className="no">✕</span> No cash value · no prizes · no buying or cashing out</li>
          <li><span className="ok">✓</span> For fun only, 18 and over</li>
        </ul>
        <p className="cz-gate-text">
          These casino games use play credits only. Credits are free and have <b>no cash value</b>. They can't be bought,
          sold, transferred, won as prizes or exchanged for anything, and that includes settling up between friends.
          Playing for real money, or paying out credits in cash afterwards, is gambling and may be illegal where you live.
          In India, real-money online games are banned under the Promotion and Regulation of Online Gaming Act, 2025. By
          continuing you confirm you are <b>18 or older</b> and will play only for fun.
        </p>
        <button className="cz-gold cz-gate-yes" onClick={accept} autoFocus>{CASINO_GATE.accept}</button>
        <button className="cz-gate-no" onClick={leave}>{CASINO_GATE.leave}</button>
        <p className="cz-gate-links">
          <a href="/privacy.html" target="_blank" rel="noopener">Privacy</a> · <a href="/terms.html" target="_blank" rel="noopener">Terms</a>
        </p>
      </div>
    </div>
  );
}

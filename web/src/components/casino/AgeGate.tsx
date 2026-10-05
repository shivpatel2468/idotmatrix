import { useEffect, useState } from "react";
import { CASINO_GATE, acceptCasinoGate, casinoGateAccepted, casinoGateDeclined, declineCasinoGate } from "../../lib/legal";
import { Modal } from "../Overlays";
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
    <Modal open onClose={leave} title={CASINO_GATE.title} width={480}>
      <div className="space-y-4 text-[13.5px] leading-relaxed text-ink-2">
        <p>
          These casino games use play credits only. Credits are free and have <b className="text-ink-1">no cash value</b>.
          They can't be bought, sold, transferred, won as prizes or exchanged for anything, and that includes settling up
          between friends. Playing for real money, or paying out credits in cash afterwards, is gambling and may be illegal
          where you live. In India, real-money online games are banned under the Promotion and Regulation of Online Gaming
          Act, 2025. By continuing you confirm you are <b className="text-ink-1">18 or older</b> and will play only for fun.
        </p>
        <div className="flex flex-wrap gap-2">
          <button className="key key-ember" onClick={accept} autoFocus>{CASINO_GATE.accept}</button>
          <button className="key" onClick={leave}>{CASINO_GATE.leave}</button>
        </div>
        <p className="text-[11.5px] text-ink-3">
          <a className="underline" href="/privacy.html" target="_blank" rel="noopener">Privacy</a> ·{" "}
          <a className="underline" href="/terms.html" target="_blank" rel="noopener">Terms</a>
        </p>
      </div>
    </Modal>
  );
}

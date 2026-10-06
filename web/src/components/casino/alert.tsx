import { CircleAlert } from "lucide-react";
import { useEffect } from "react";
import { create } from "zustand";
import { toast, useStore } from "../../lib/store";

/**
 * The casino's centred error toast (docs/STUDIO_UI.md, casino mode): every bet rejection the engine sends the host
 * ("Table min is 500", "Table max is …", "Not enough credits", "Bets are closed", …) and every casino op that fails,
 * big and centred over the table in the theme's accent — a pop-in with a short shake, a tinted flash behind it,
 * gone after ~2.2 s or on a tap. The same text the phones show. Fixed overlay: it never pushes layout.
 */
type Alert = { id: number; text: string; at: number };
const useAlert = create<{ cur: Alert | null }>(() => ({ cur: null }));
let seq = 0;
let mounted = 0;

/** Show `text` as the centred casino alert (a corner toast when the casino view isn't on screen). */
export function casinoAlert(text: string) {
  const t = String(text || "").trim();
  if (!t) return;
  if (!mounted) return void toast(t, "error");
  // one alert at a time: a new (or the same) message replaces it and pops in again instead of stacking
  useAlert.setState({ cur: { id: ++seq, text: t, at: performance.now() } });
}

/** When the last alert with this text was shown (the host-notice watcher skips what the op reply already showed). */
export function shownRecently(text: string, ms = 4000): boolean {
  const cur = useAlert.getState().cur;
  return !!cur && cur.text === text && performance.now() - cur.at < ms;
}

export function CasinoAlert() {
  const cur = useAlert((s) => s.cur);
  useEffect(() => {
    mounted++;
    // while the casino view is on screen, any error the studio raises (a failed setting, the room, a table switch …)
    // comes here too instead of the corner toast the host can't see past the table
    const off = useStore.subscribe((s, prev) => {
      if (s.toasts === prev.toasts) return;
      const seen = new Set(prev.toasts.map((t) => t.id));
      const fresh = s.toasts.filter((t) => !seen.has(t.id) && t.tone === "error");
      if (!fresh.length) return;
      const ids = new Set(fresh.map((t) => t.id));
      useStore.setState({ toasts: s.toasts.filter((t) => !ids.has(t.id)) });
      casinoAlert(fresh[fresh.length - 1].text);
    });
    return () => {
      mounted--;
      off();
    };
  }, []);
  useEffect(() => {
    if (!cur) return;
    const t = window.setTimeout(() => useAlert.setState((s) => (s.cur?.id === cur.id ? { cur: null } : s)), 2200);
    return () => window.clearTimeout(t);
  }, [cur]);
  if (!cur) return null;
  const close = () => useAlert.setState({ cur: null });
  return (
    <div className="cz-alert-wrap" key={cur.id}>
      <span className="cz-alert-flash" aria-hidden />
      <button type="button" className="cz-alert" role="alert" aria-live="assertive" onClick={close} title="Dismiss">
        <CircleAlert size={30} strokeWidth={2.4} aria-hidden />
        <b>{cur.text}</b>
      </button>
    </div>
  );
}

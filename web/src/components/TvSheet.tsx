import { useEffect, useState } from "react";
import { Check, Copy, MonitorPlay, RefreshCw, Tv, Wifi, X } from "lucide-react";
import { api } from "../lib/api";
import { toast, useStore } from "../lib/store";
import type { TvInfo } from "../lib/types";
import { QrCode } from "./Multiplayer";
import { Modal } from "./Overlays";

/**
 * "Show on TV" (docs/TV_VIEW.md): opens the TV link and shows its QR code, the address to type, the TV code and how
 * many screens are watching. A smart TV, Fire TV, tablet or second laptop opens the address and shows the panel —
 * and the bespoke game / casino scenes — full screen, read-only.
 */
export function TvSheet() {
  const open = useStore((s) => s.tvOpen);
  const set = useStore((s) => s.set);
  const web = useStore((s) => s.meta?.platform === "web");
  const [tv, setTv] = useState<TvInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const close = () => set({ tvOpen: false });

  // opening the sheet opens the link (or returns the one already open); poll the viewer count while it shows
  useEffect(() => {
    if (!open) return;
    let alive = true;
    api.openTv().then((r) => alive && setTv(r)).catch(() => alive && setTv(null));
    const t = window.setInterval(() => {
      api.tv().then((r) => alive && setTv(r.tv)).catch(() => {});
    }, 2000);
    return () => { alive = false; window.clearInterval(t); };
  }, [open]);

  const copy = async () => {
    if (!tv?.url) return;
    try {
      await navigator.clipboard.writeText(tv.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      toast("Couldn't copy — select the address instead", "error");
    }
  };
  const renew = async () => {
    setBusy(true);
    try { setTv(await api.openTv(true)); toast("New TV code — screens on the old one were disconnected", "ok"); } finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true);
    try { await api.closeTv(); setTv(null); toast("TV link stopped", "ok"); close(); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={close} title="Show on TV" width={480}>
      <div className="flex flex-col gap-4">
        <p className="flex gap-2.5 text-[12.5px] leading-snug text-ink-2">
          <MonitorPlay size={16} className="mt-px shrink-0 text-ember" />
          <span>Open this address in any browser — a smart TV, Fire TV, a tablet or another laptop. It shows the panel big,
            and games and casino tables full screen. It only watches; nothing on the TV can change the panel.</span>
        </p>
        {tv && !tv.lan_ready && (
          <div className="rounded-[10px] border border-bad/40 bg-bad/10 p-3 text-[12px] leading-snug text-ink-1">
            <b className="font-[620] text-bad">Other screens can't reach this computer.</b> DeskDot only listens to this computer.
            Set <code>host = "0.0.0.0"</code> in <code>deskdot.toml</code> and restart DeskDot.
          </div>
        )}
        {tv?.url ? (
          <div className="flex flex-col items-center gap-3 text-center">
            <QrCode text={tv.url} size={208} />
            <div className="text-[12.5px] text-ink-2">Scan with the TV's or a phone's camera — or type:</div>
            <button onMouseDown={(e) => e.preventDefault()} onClick={copy} title="Copy the address"
              className="flex max-w-full items-center gap-2 rounded-[8px] border border-line bg-chassis-0 px-2.5 py-1.5 font-mono text-[12.5px] text-ink-1 hover:border-line-2">
              <span className="truncate select-all">{tv.url.replace(/^https?:\/\//, "")}</span>
              {copied ? <Check size={12} className="shrink-0 text-ok" /> : <Copy size={12} className="shrink-0 text-ink-3" />}
            </button>
            <div className="flex items-center gap-5">
              <div className="flex items-baseline gap-2">
                <span className="engrave">TV code</span>
                <span className="font-mono text-[24px] font-[700] tracking-[0.28em] text-ember">{tv.code}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="led" data-on={tv.viewers > 0 ? "ok" : undefined} />
                <span className="font-mono text-[11px] text-ink-2">
                  {tv.viewers === 0 ? "No screen watching yet" : tv.viewers === 1 ? "1 screen watching" : `${tv.viewers} screens watching`}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid h-[260px] place-items-center text-[12.5px] text-ink-3"><Tv size={28} className="animate-pulse" /></div>
        )}
        <p className="flex gap-2 text-[11px] leading-snug text-ink-3">
          <Wifi size={13} className="mt-px shrink-0" />
          {web ? (
            <span>The TV links straight to this tab, so keep it open (very strict networks may block the direct link).</span>
          ) : (
            <span>The screen must be on the same Wi-Fi as this computer. The first time, Windows may ask to allow DeskDot on the network — choose <b className="font-[600] text-ink-2">Allow</b>.</span>
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <button className="key !h-10 flex-1" disabled={busy || !tv} onClick={renew} title="Make a new code; screens on the old one disconnect">
            <RefreshCw size={13} /> New code
          </button>
          <button className="key !h-10 flex-1" disabled={busy || !tv} onClick={stop} title="Close the TV link and disconnect every screen">
            <X size={13} /> Stop TV link
          </button>
        </div>
      </div>
    </Modal>
  );
}

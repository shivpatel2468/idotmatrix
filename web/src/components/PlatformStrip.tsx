import { X } from "lucide-react";
import { api } from "../lib/api";
import { EMPTY_LIST, useStore } from "../lib/store";
import type { CustomAppInfo, IndicatorState } from "../lib/types";
import { Icon } from "./Icon";

const EMPTY_INDICATORS: Record<string, IndicatorState> = {};
const openIntegrations = () => useStore.setState({ settingsOpen: true, settingsTab: "integrations" });

/** Where indicator N sits on the 32×32 grid (mirrors engine/persistent.indicator_origin). */
function origin(slot: number, size: number): [number, number] {
  const x = 32 - size;
  const y = slot === 1 ? 0 : slot === 2 ? Math.floor((32 - size) / 2) : 32 - size;
  return [x, y];
}

function describe(i: IndicatorState) {
  const mode = i.blink ? `blink ${i.blink} ms` : i.fade ? `fade ${i.fade} ms` : "steady";
  return `${i.color} · ${mode}${i.remaining_s != null ? ` · ${Math.ceil(i.remaining_s)} s left` : ""}`;
}

/** Hover / click targets over the indicator LEDs on the stage preview. */
export function IndicatorHotspots() {
  const inds = useStore((s) => s.state?.engine.indicators ?? EMPTY_INDICATORS);
  return (
    <div className="pointer-events-none absolute inset-0 z-[6]">
      {Object.entries(inds).map(([slot, ind]) => {
        const [x, y] = origin(+slot, ind.size);
        const pad = 1.2; // cells of slack around the square
        return (
          <button key={slot} title={`Indicator ${slot} · ${describe(ind)} — click to edit`} onClick={openIntegrations}
            className="pointer-events-auto absolute rounded-[3px] border border-transparent transition hover:border-white/70"
            style={{
              left: `${((x - pad) / 32) * 100}%`, top: `${((y - pad) / 32) * 100}%`,
              width: `${((ind.size + pad * 2) / 32) * 100}%`, height: `${((ind.size + pad * 2) / 32) * 100}%`,
            }} />
        );
      })}
    </div>
  );
}

/** Under the stage: what the platform features are doing right now, with one-click clear. */
export function PlatformStrip() {
  const onair = useStore((s) => s.state?.engine.onair);
  const takeover = useStore((s) => s.state?.engine.takeover);
  const inds = useStore((s) => s.state?.engine.indicators ?? EMPTY_INDICATORS);
  const custom = useStore((s) => (s.state?.engine.custom ?? EMPTY_LIST) as CustomAppInfo[]);
  const entries = Object.entries(inds);
  if (!onair?.active && takeover !== "eyebreak" && !entries.length && !custom.length) return null;
  return (
    <div className="surface flex w-full flex-wrap items-center gap-2 px-4 py-2.5 text-[12px] animate-rise">
      {onair?.active && (
        <span className="flex items-center gap-2 rounded-md border border-bad/40 bg-bad/10 px-2 py-1 font-mono text-[10.5px] text-bad">
          <span className="led" data-on="bad" /> ON AIR {onair.simulated ? "· preview" : `· ${Object.values(onair.apps).flat().join(", ")}`}
          {onair.simulated && <button title="Stop preview" onClick={() => api.onairSimulate(0)}><X size={12} /></button>}
        </span>
      )}
      {takeover === "eyebreak" && (
        <span className="flex items-center gap-2 rounded-md bg-chassis-0 px-2 py-1 font-mono text-[10.5px] text-ok">
          <Icon name="eye" size={12} /> eye break
        </span>
      )}
      {entries.map(([slot, ind]) => (
        <span key={slot} title={describe(ind)} className="flex items-center gap-1.5 rounded-md bg-chassis-0 px-2 py-1 font-mono text-[10.5px] text-ink-2">
          <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: ind.color, boxShadow: `0 0 8px ${ind.color}` }} />
          ind {slot}
          <button className="text-ink-4 hover:text-ink-1" title={`Clear indicator ${slot}`} onClick={() => api.clearIndicator(+slot)}><X size={12} /></button>
        </span>
      ))}
      {custom.map((c) => (
        <span key={c.name} title={`Custom app · ${c.duration}s in the rotation${c.expires_in != null ? ` · expires in ${c.expires_in}s` : ""}`}
          className="flex max-w-[220px] items-center gap-1.5 rounded-md bg-chassis-0 px-2 py-1 font-mono text-[10.5px] text-ink-2">
          <Icon name="webhook" size={12} className="shrink-0 text-ink-4" />
          <span className="text-ink-1">{c.name}</span>
          <span className="truncate text-ink-3">{c.text}</span>
          <button className="shrink-0 text-ink-4 hover:text-ink-1" title={`Remove ${c.name}`} onClick={() => api.removeCustom(c.name)}><X size={12} /></button>
        </span>
      ))}
      <button className="key key-ghost ml-auto" onClick={openIntegrations}><Icon name="plug-zap" size={13} /> Integrations</button>
    </div>
  );
}

import clsx from "clsx";
import { Check, RotateCcw, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { type Calib, FIELDS, type FieldKey, type FieldMeta, IDENTITY, channelGains, sameLook } from "../../lib/calib";
import { MATCHES, MATCH_HINT, MATCH_LABEL, useLook } from "../../lib/look";
import { toast } from "../../lib/store";
import { Slider, Toggle } from "../controls";
import { PanelSketch, ScreenReference, useClearOnUnmount, VideoChips, CAL_VIDEO_FALLBACK } from "./parts";

const GROUPS: [string, FieldKey[]][] = [
  ["Tone", ["gamma", "contrast", "black_level", "lift"]],
  ["Colour", ["saturation", "temperature", "level"]],
  ["White balance (RGB gains)", ["red", "green", "blue"]],
  ["Per-channel gamma", ["gamma_red", "gamma_green", "gamma_blue"]],
];
const META = Object.fromEntries(FIELDS.map((f) => [f.key, f])) as Record<FieldKey, FieldMeta>;

/**
 * Every calibration knob with bounds, a reset and a hint. Changes play live on the panel as a test video (a wipe
 * against the saved calibration when "Compare" is on) and are saved only with "Save" — saving re-bakes every
 * clip, and the panel dislikes frequent GIF uploads (HARDWARE_PROTOCOL.md #16).
 */
export function CalAdvanced({ saved, start, onDone }: { saved: Calib; start?: Calib | null; onDone: () => void }) {
  useClearOnUnmount();
  const [c, setC] = useState<Calib>(start ?? saved);
  const [video, setVideo] = useState("card");
  const [compare, setCompare] = useState(false);
  const match = useLook((s) => s.match);
  const setMatch = useLook((s) => s.setMatch);
  const dirty = !sameLook(c, saved);

  useEffect(() => {
    api.calibTest(compare ? { video, a: saved, b: c, layout: "wipe", split: 16, labels: ["NOW", "NEW"] } : { video, a: c }).catch(() => undefined);
  }, [c, video, compare, saved]);

  const set = (k: FieldKey, v: number) => setC((x) => ({ ...x, [k]: v, preset: "custom" }));
  const save = async () => {
    await api.calibration({ ...c, preset: c.preset && c.preset !== "custom" && sameLook(c, saved) ? c.preset : "custom" });
    toast("Calibration saved", "ok");
    onDone();
  };
  const gains = channelGains(c);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        <ScreenReference size={144} split={compare ? 16 : undefined} />
        <PanelSketch a={compare ? saved : c} b={compare ? c : null} size={104} caption={compare ? "Now | new as sent" : "Sent to the panel"} />
        <div className="min-w-[200px] flex-1 space-y-2">
          <VideoChips videos={CAL_VIDEO_FALLBACK} value={video} onChange={setVideo} />
          <label className="flex items-center gap-2 text-[12px] text-ink-2">
            <Toggle on={compare} onChange={setCompare} label="Compare with saved" /> Compare with the saved calibration (left = now)
          </label>
          <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-ink-3" title="White balance × colour temperature × peak level">
            effective gains
            {(["R", "G", "B"] as const).map((ch, i) => (
              <span key={ch} className="rounded bg-chassis-0 px-1.5 py-0.5">{ch} {gains[i].toFixed(2)}</span>
            ))}
          </div>
        </div>
      </div>

      {GROUPS.map(([title, keys]) => (
        <section key={title}>
          <div className="engrave mb-1">{title}</div>
          <div className="divide-y divide-line">
            {keys.map((k) => <FieldRow key={k} m={META[k]} value={c[k]} onChange={(v) => set(k, v)} />)}
          </div>
        </section>
      ))}

      <section>
        <div className="engrave mb-1">Rendering</div>
        <div className="divide-y divide-line">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
            <div className="min-w-[160px] flex-1">
              <div className="text-[13px] font-[560]">Dithering</div>
              <div className="text-[11.5px] leading-snug text-ink-3">Ordered dither hides banding in dark gradients. Static (no shimmer) and 1-bit safe: text and pure colours never change.</div>
            </div>
            <Toggle on={c.dither} label="Dithering" onChange={(v) => setC((x) => ({ ...x, dither: v, preset: "custom" }))} />
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
            <div className="min-w-[160px] flex-1">
              <div className="text-[13px] font-[560]">Studio preview colours</div>
              <div className="text-[11.5px] leading-snug text-ink-3">{MATCH_HINT[match]}. This browser only.</div>
            </div>
            <div className="seg">
              {MATCHES.map((m) => <button key={m} data-active={match === m} onClick={() => setMatch(m)}>{MATCH_LABEL[m]}</button>)}
            </div>
          </div>
        </div>
      </section>

      <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-line bg-chassis-1/95 py-3 backdrop-blur">
        <button className="key key-ghost" title="Every knob back to factory" onClick={() => setC({ ...IDENTITY, preset: "custom" })}><RotateCcw size={13} /> Factory</button>
        <button className="key key-ghost" disabled={!dirty} onClick={() => setC(saved)}><Undo2 size={13} /> Revert</button>
        <span className={clsx("ml-auto font-mono text-[10.5px]", dirty ? "text-warn" : "text-ink-4")}>{dirty ? "unsaved changes" : "saved"}</span>
        <button className="key key-ember" disabled={!dirty} onClick={save}><Check size={13} /> Save</button>
      </div>
    </div>
  );
}

function FieldRow({ m, value, onChange }: { m: FieldMeta; value: number; onChange: (v: number) => void }) {
  const def = IDENTITY[m.key];
  const changed = Math.abs(value - def) > 1e-6;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
      <div className="min-w-[160px] flex-1">
        <div className="text-[13px] font-[560]">{m.label}</div>
        <div className="text-[11px] leading-snug text-ink-3">{m.hint}</div>
      </div>
      <div className="flex items-center gap-1.5">
        <Slider value={value} min={m.min} max={m.max} step={m.step} unit={m.unit} width={150} onCommit={onChange} />
        <button className={clsx("key key-ghost key-icon !h-7 !w-7", !changed && "invisible")} aria-label={`Reset ${m.label}`} title={`Reset to ${def}`} onClick={() => onChange(def)}>
          <RotateCcw size={12} />
        </button>
      </div>
    </div>
  );
}

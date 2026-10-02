import clsx from "clsx";
import { RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { type Calib, IDENTITY, calibrator, isIdentity, toCalib } from "../../lib/calib";
import { toast } from "../../lib/store";
import type { EngineState } from "../../lib/types";
import { Icon } from "../Icon";
import { CalAdvanced } from "./CalAdvanced";
import { CalPresets } from "./CalPresets";
import { CalWizard } from "./CalWizard";
import { Swatches } from "./parts";

type Mode = "home" | "wizard" | "presets" | "advanced";

/** Skin, sky, foliage, ember, mid grey, dark grey, white — the same strip the presets show. */
const SWATCH = [[226, 172, 125], [70, 150, 235], [60, 170, 70], [255, 72, 24], [128, 128, 128], [40, 40, 48], [255, 255, 255]];
const hex = (r: number, g: number, b: number) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");

export function swatchesFor(c: Calib): string[] {
  const out = calibrator(c, SWATCH.length)(Uint8Array.from(SWATCH.flat()));
  return SWATCH.map((_, i) => hex(out[i * 3], out[i * 3 + 1], out[i * 3 + 2]));
}

/**
 * Settings → Display → Colour calibration: three ways in — a guided A/B match (most accurate), one-tap presets
 * (fastest) and every knob (advanced). All of them preview on the real panel with animated test videos.
 */
export function ColourCalibration({ st }: { st: EngineState }) {
  const saved = useMemo(() => toCalib(st.settings.calibration), [st.settings.calibration]);
  const [mode, setMode] = useState<Mode>("home");
  const [handoff, setHandoff] = useState<Calib | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    api.calibPresets().then((l) => setNames(Object.fromEntries(l.presets.map((p) => [p.id, p.name])))).catch(() => undefined);
  }, []);

  const home = () => { setMode("home"); setHandoff(null); };
  const presetName = saved.preset === "wizard" ? "Guided match" : saved.preset === "custom" ? "Custom" : names[saved.preset] ?? (isIdentity(saved) ? "Panel native" : "Custom");

  if (mode !== "home") {
    const titles: Record<Exclude<Mode, "home">, string> = { wizard: "Guided match", presets: "Presets", advanced: "Advanced" };
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <button className="key key-ghost !h-8" onClick={() => { home(); api.clearPattern(); }}><Icon name="chevron-left" size={13} /> Colour</button>
          <div className="seg ml-auto">
            {(["wizard", "presets", "advanced"] as const).map((m) => (
              <button key={m} data-active={mode === m} onClick={() => { setHandoff(null); setMode(m); }}>{titles[m]}</button>
            ))}
          </div>
        </div>
        {mode === "wizard" && <CalWizard saved={saved} onDone={home} onAdvanced={(c) => { setHandoff(c); setMode("advanced"); }} />}
        {mode === "presets" && <CalPresets saved={saved} onPicked={home} />}
        {mode === "advanced" && <CalAdvanced key={handoff ? "handoff" : "saved"} saved={saved} start={handoff} onDone={home} />}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-chassis-0 px-3 py-2.5">
        <div className="min-w-0">
          <div className="engrave">In use</div>
          <div className="font-display text-[15px] font-[640]">{presetName}</div>
        </div>
        <div className="ml-auto w-48 space-y-1" title="Design colours → as the panel is sent them">
          <Swatches colors={swatchesFor(IDENTITY)} />
          <Swatches colors={swatchesFor(saved)} />
          <div className="flex justify-between font-mono text-[9px] text-ink-4"><span>design ↑</span><span>panel ↓</span></div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <Tile icon="scan-eye" title="Guided match" sub="~2 min · most accurate" body="Test videos on the panel and here; pick the closer half until it converges." primary onClick={() => setMode("wizard")} />
        <Tile icon="palette" title="Presets" sub="1 tap · fastest" body="Claude presets, display-inspired styles and standards — or answer 3 questions." onClick={() => setMode("presets")} />
        <Tile icon="sliders-horizontal" title="Advanced" sub="every knob" body="Per-channel gamma and gains, contrast, temperature, peak, dithering, preview match." onClick={() => setMode("advanced")} />
      </div>
      <div className="flex justify-end">
        <button className="key key-ghost !h-8" title="Back to factory colours" disabled={isIdentity(saved)}
          onClick={async () => { await api.calibration({ ...IDENTITY, preset: "native" }); toast("Calibration reset", "ok"); }}>
          <RotateCcw size={13} /> Reset to panel native
        </button>
      </div>
    </div>
  );
}

function Tile({ icon, title, sub, body, onClick, primary }: { icon: string; title: string; sub: string; body: string; onClick: () => void; primary?: boolean }) {
  return (
    <button onClick={onClick} className={clsx("group rounded-[10px] border p-3 text-left transition",
      primary ? "border-ember/60 bg-ember-deep/30 hover:border-ember" : "border-line bg-chassis-0 hover:border-line-2")}>
      <div className="flex items-center gap-2">
        <Icon name={icon} size={16} className="text-ember" />
        <span className="text-[13.5px] font-[620] group-hover:text-ink-1">{title}</span>
      </div>
      <div className="engrave mt-1">{sub}</div>
      <div className="mt-1 text-[11.5px] leading-snug text-ink-3">{body}</div>
    </button>
  );
}

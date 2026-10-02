import clsx from "clsx";
import { AlertTriangle, Check, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { type Autotune, DEFAULT_MOTION, type MotionCfg, type MotionInfo, type MotionPreset, type Search, candidates, choose, startSearch } from "../../lib/calib";
import { toast } from "../../lib/store";
import type { EngineState } from "../../lib/types";
import { Icon } from "../Icon";
import { LedPanel } from "../LedPanel";
import { Row, Slider, Toggle } from "../controls";
import { ABKeys, Progress, SearchMeter, useClearOnUnmount, VideoChips } from "./parts";

type Transition = MotionCfg["transition"];
type View = "home" | "guided" | "bench";

/**
 * Settings → Display → Smooth motion: animated tests on the panel and on screen, A/B picks for the smoothest
 * settings, presets, a measured auto-tune, and the link's fixed physics shown as facts (rule 13).
 */
export function MotionLab({ st }: { st: EngineState }) {
  const [info, setInfo] = useState<MotionInfo | null>(null);
  const [view, setView] = useState<View>("home");
  const reload = useCallback(() => api.motion().then(setInfo).catch(() => undefined), []);
  useEffect(() => void reload(), [reload, st.settings.display.max_fps, st.settings.display.packet_gap_ms, st.settings.transition]);
  if (!info) return <div className="skeleton h-40 rounded-lg" />;

  if (view !== "home") {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <button className="key key-ghost !h-8" onClick={() => { setView("home"); api.clearPattern(); }}><Icon name="chevron-left" size={13} /> Motion</button>
          <div className="seg ml-auto">
            <button data-active={view === "guided"} onClick={() => setView("guided")}>Find my smoothest</button>
            <button data-active={view === "bench"} onClick={() => setView("bench")}>Test bench</button>
          </div>
        </div>
        {view === "guided" ? <Guided info={info} onDone={() => { setView("home"); reload(); }} /> : <Bench info={info} />}
      </div>
    );
  }
  return <Home st={st} info={info} reload={reload} onView={setView} />;
}

// ------------------------------------------------------------------------------------------------ home
function Home({ st, info, reload, onView }: { st: EngineState; info: MotionInfo; reload: () => void; onView: (v: View) => void }) {
  const d = st.settings.display;
  const cur = info.current;
  const [tuning, setTuning] = useState(false);
  const [tuned, setTuned] = useState<Autotune | null>(null);
  const active = info.presets.find((p) => matches(p, cur))?.id ?? (cur.preset === "auto" ? "auto" : null);
  const L = info.limits;

  const usePreset = async (p: MotionPreset) => {
    await api.motionPreset(p.id);
    toast(`${p.name} motion settings applied`, "ok");
    reload();
  };
  const autotune = async () => {
    setTuning(true);
    setTuned(null);
    try {
      setTuned(await api.motionAutotune(false));
    } finally {
      setTuning(false);
      api.clearPattern();
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 font-mono text-[11px] sm:grid-cols-5">
        {([
          ["Stream cap", `${cur.max_fps} fps`],
          ["Link now", `${st.device.link_fps.toFixed(1)} fps`],
          ["Spacing", `${cur.packet_gap_ms} ms`],
          ["Transition", cur.transition],
          ["Smoothing", cur.smoothing ? cur.smoothing.toFixed(2) : "off"],
        ] as const).map(([k, v]) => (
          <div key={k} className="rounded-[10px] border border-line bg-chassis-0 p-2.5">
            <div className="text-[9.5px] text-ink-4">{k}</div>
            <div className="mt-0.5 text-[13px] font-bold uppercase text-ink-1">{v}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <button onClick={() => onView("guided")} className="rounded-[10px] border border-ember/60 bg-ember-deep/30 p-3 text-left transition hover:border-ember">
          <div className="flex items-center gap-2"><Icon name="scan-eye" size={16} className="text-ember" /><span className="text-[13.5px] font-[620]">Find my smoothest</span></div>
          <div className="mt-1 text-[11.5px] leading-snug text-ink-3">A UFO, a live graph and app switches play on the panel; pick the smoother half. ~1 minute.</div>
        </button>
        <button onClick={() => onView("bench")} className="rounded-[10px] border border-line bg-chassis-0 p-3 text-left transition hover:border-line-2">
          <div className="flex items-center gap-2"><Icon name="flask-conical" size={16} className="text-ember" /><span className="text-[13.5px] font-[620]">Test bench</span></div>
          <div className="mt-1 text-[11.5px] leading-snug text-ink-3">Seven motion tests at any rate and speed, side by side, streamed or as a native loop.</div>
        </button>
      </div>

      <div>
        <div className="engrave mb-2">Presets</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {info.presets.map((p) => (
            <button key={p.id} onClick={() => usePreset(p)} className={clsx("rounded-[10px] border bg-chassis-0 p-3 text-left transition",
              active === p.id ? "border-ember" : "border-line hover:border-line-2")}>
              <div className="flex items-center gap-2 text-[13px] font-[600]">{p.name}{active === p.id && <span className="engrave !text-ember">in use</span>}</div>
              <div className="mt-0.5 text-[11.5px] leading-snug text-ink-3">{p.blurb}</div>
              <div className="mt-1.5 font-mono text-[10px] text-ink-4">{p.max_fps} fps · {p.packet_gap_ms} ms · {p.transition}{p.smoothing ? ` · smooth ${p.smoothing}` : ""}</div>
            </button>
          ))}
          <div className={clsx("rounded-[10px] border bg-chassis-0 p-3", active === "auto" ? "border-ember" : "border-line")}>
            <div className="flex items-center gap-2 text-[13px] font-[600]"><Icon name="sparkles" size={13} className="text-ember" /> Claude: auto-tune{active === "auto" && <span className="engrave !text-ember">in use</span>}</div>
            <div className="mt-0.5 text-[11.5px] leading-snug text-ink-3">Streams the heaviest test for 4 s, measures what your link really delivers, and picks settings within the verified limits.</div>
            {tuned ? (
              <div className="mt-2 space-y-1.5">
                <div className="font-mono text-[10.5px] text-ink-2">measured {tuned.measured_fps.toFixed(1)} fps · frame {tuned.frame_bytes} B → {tuned.max_fps} fps · {tuned.packet_gap_ms} ms · {tuned.transition}</div>
                <div className="flex gap-1.5">
                  <button className="key key-ember !h-8" onClick={async () => { await api.display({ max_fps: tuned.max_fps, packet_gap_ms: tuned.packet_gap_ms, smoothing: tuned.smoothing, motion_preset: "auto" }); await api.settings({ transition: tuned.transition }); toast("Auto-tuned for your link", "ok"); setTuned(null); reload(); }}><Check size={12} /> Apply</button>
                  <button className="key key-ghost !h-8" onClick={() => setTuned(null)}>Dismiss</button>
                </div>
              </div>
            ) : (
              <button className="key mt-2 !h-8" disabled={tuning} onClick={autotune}><Zap size={12} /> {tuning ? "Measuring the link…" : "Measure & suggest"}</button>
            )}
          </div>
        </div>
      </div>

      <details className="group/adv rounded-lg border border-line">
        <summary className="flex cursor-pointer select-none list-none items-center gap-2 rounded-lg px-3 py-2.5 text-[12.5px] text-ink-2 hover:bg-chassis-2/60">
          <span className="transition group-open/adv:rotate-90">›</span> Advanced: stream rate, smoothing, transitions, link facts
        </summary>
        <div className="border-t border-line px-3 pb-3 pt-1">
          <div className="divide-y divide-line">
            <Row label="Stream frame cap" hint={`Frames per second sent while streaming. The link delivers ~${L.measured_ui_fps} fps for simple frames and ~${L.measured_photo_fps} for photo-like ones; extra frames are dropped (latest wins).`}>
              <Slider value={d.max_fps} min={1} max={20} unit=" fps" onCommit={(v) => api.display({ max_fps: v, motion_preset: "custom" })} />
            </Row>
            <Row label="Temporal smoothing" hint="Blends each streamed frame with the last one: calms jittery live data (visualisers, graphs). 0 = off, crisp.">
              <Slider value={d.smoothing ?? 0} min={0} max={0.6} step={0.05} onCommit={(v) => api.display({ smoothing: v, motion_preset: "custom" })} />
            </Row>
            <Row label="App transitions" hint="How one app hands over to the next. Cut is the cleanest over Bluetooth; loops (clips) always cut.">
              <div className="seg">
                {(["cut", "push", "fade", "wipe"] as const).map((t) => (
                  <button key={t} data-active={st.settings.transition === t} onClick={() => api.settings({ transition: t })}>{t}</button>
                ))}
              </div>
            </Row>
            <Row label="Packet spacing" hint={`Pause between Bluetooth packets of one frame. Presets and tests never go below ${L.packet_gap_min_ms} ms; ${L.packet_gap_verified_ms} ms is the first value verified on hardware.`}>
              <Slider value={Math.max(L.packet_gap_min_ms, d.packet_gap_ms)} min={L.packet_gap_min_ms} max={80} unit=" ms" onCommit={(v) => api.display({ packet_gap_ms: v, motion_preset: "custom" })} />
            </Row>
          </div>
          {d.packet_gap_ms < L.packet_gap_min_ms && (
            <div className="mt-2 flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 p-2.5 text-[11.5px] text-ink-2">
              <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" />
              Packet spacing is set to {d.packet_gap_ms} ms, below the {L.packet_gap_min_ms} ms the presets use — unverified on hardware. If frames go missing, pick a preset.
            </div>
          )}
          <div className="engrave mb-1.5 mt-3">Fixed by the hardware (verified, not adjustable)</div>
          <div className="grid grid-cols-2 gap-1.5 font-mono text-[10.5px] text-ink-2 sm:grid-cols-3">
            {[
              [`${L.frames_in_flight} frame in flight`, "one un-acked frame at a time keeps the link reliable"],
              [`GIF ≤ ${L.gif_budget_kb} KB`, "bigger loops decode sluggishly on the panel"],
              [`loops ≤ ${L.clip_fps_max} fps`, "native playback, smooth and link-free"],
              [`≥ ${L.packet_gap_min_ms} ms spacing`, "unpaced packets are silently dropped"],
              [`~${L.measured_ui_fps} fps one-packet frames`, `frames over ${L.one_packet_bytes} B need two packets`],
              ["≤ ~1 px per frame", "small steps read as smooth motion"],
            ].map(([k, why]) => (
              <div key={k} className="rounded-lg bg-chassis-0 px-2.5 py-1.5" title={why}>
                <div className="text-ink-1">{k}</div>
                <div className="text-[9.5px] leading-snug text-ink-4">{why}</div>
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}

const matches = (p: MotionPreset, c: MotionInfo["current"]) =>
  p.max_fps === c.max_fps && p.packet_gap_ms === c.packet_gap_ms && p.transition === c.transition && Math.abs((c.smoothing ?? 0) - p.smoothing) < 1e-6;

// ------------------------------------------------------------------------------------------------ guided
type G = { stage: "fps" | "transition" | "smoothing" | "done"; fps: Search; tr: [Transition, Transition]; trLeft: Transition[]; sm: Search };

const GUIDED_STAGES = ["fps", "transition", "smoothing", "done"] as const;

function Guided({ info, onDone }: { info: MotionInfo; onDone: () => void }) {
  useClearOnUnmount();
  const [g, setG] = useState<G>(() => ({
    stage: "fps",
    fps: startSearch(4, 12, 3, true, 8),
    tr: ["cut", "fade"],
    trLeft: ["push", "wipe"],
    sm: { ...startSearch(0, 0.6, 2, false, 0.3), d: 0.3 },
  }));
  const [res, setRes] = useState<{ fps: number; transition: Transition; smoothing: number }>({ fps: info.current.max_fps, transition: info.current.transition, smoothing: info.current.smoothing ?? 0 });
  const [fa, fb] = candidates(g.fps);
  const [sa, sb] = candidates(g.sm);

  useEffect(() => {
    const base = { ...DEFAULT_MOTION, speed: 8 };
    if (g.stage === "fps") api.motionTest({ test: "ufo", a: { ...base, fps: fa }, b: { ...base, fps: fb }, layout: "stack" }).catch(() => undefined);
    else if (g.stage === "transition") api.motionTest({ test: "transition", a: { ...base, fps: 10, transition: g.tr[0] }, b: { ...base, fps: 10, transition: g.tr[1] }, layout: "alternate" }).catch(() => undefined);
    else if (g.stage === "smoothing") api.motionTest({ test: "live", a: { ...base, fps: 8, smoothing: sa }, b: { ...base, fps: 8, smoothing: sb }, layout: "stack" }).catch(() => undefined);
    else api.motionTest({ test: "ball", a: { ...base, fps: res.fps } }).catch(() => undefined);
  }, [g.stage, fa, fb, g.tr, sa, sb, res.fps]);

  const pick = (p: "a" | "b" | "same") => {
    if (g.stage === "fps") {
      if (p === "same" || fa === fb) return next("transition", { fps: Math.min(fa, fb) }); // equal: the lighter rate is enough
      const s = choose(g.fps, p);
      const [na, nb] = candidates(s);
      if (s.done || na === nb) return next("transition", { fps: p === "a" ? fa : fb });
      setG({ ...g, fps: s });
    } else if (g.stage === "transition") {
      const winner = p === "b" ? g.tr[1] : g.tr[0];
      if (!g.trLeft.length) return next("smoothing", { transition: winner });
      setG({ ...g, tr: [winner, g.trLeft[0]], trLeft: g.trLeft.slice(1) });
    } else if (g.stage === "smoothing") {
      if (p === "same") return next("done", { smoothing: 0 }); // equal: off is crisper
      const s = choose(g.sm, p);
      if (s.done) return next("done", { smoothing: Math.max(0, Math.round((p === "a" ? sa : sb) * 20) / 20) });
      setG({ ...g, sm: s });
    }
  };
  const next = (stage: G["stage"], patch: Partial<typeof res>) => {
    setRes((r) => ({ ...r, ...patch }));
    setG((x) => ({ ...x, stage }));
  };
  const apply = async () => {
    await api.display({ max_fps: res.fps, smoothing: res.smoothing, motion_preset: "guided" });
    await api.settings({ transition: res.transition });
    await api.clearPattern();
    toast("Motion tuned to your eyes and your link", "ok");
    onDone();
  };

  const at = GUIDED_STAGES.indexOf(g.stage);
  const Q: Record<G["stage"], { title: string; q: string; hint: string }> = {
    fps: { title: "Frame rate", q: "Follow the UFO with your eyes. Which one glides more smoothly?", hint: "A runs on the top half, B on the bottom, at different frame rates. Look for doubled edges or hops. If they look the same, the lighter rate wins." },
    transition: { title: "App switches", q: "Which switch between screens looks nicer on the panel?", hint: "The panel alternates: 4 s of A, then 4 s of B (the letter in the corner). A blocky or noisy switch is a no." },
    smoothing: { title: "Live data", q: "Which half's bars look calmer without feeling sluggish?", hint: "Jittery live data, like a visualiser. Smoothing steadies it but adds a little lag. Same? Off is crisper." },
    done: { title: "Done", q: "", hint: "" },
  };

  return (
    <div className="space-y-4">
      <Progress steps={GUIDED_STAGES.length} at={at} labels={["Frame rate", "App switches", "Live data", "Done"]} />
      <div className="flex flex-wrap items-start gap-4">
        <figure className="m-0">
          <div className="rounded-[10px] border border-line bg-black p-1.5"><LedPanel size={160} look="pixel" glow={false} lookSwitch={false} raw /></div>
          <figcaption className="engrave mt-1.5 text-center">Same test, on screen</figcaption>
        </figure>
        <div className="min-w-[220px] flex-1 space-y-2">
          {g.stage !== "done" ? (
            <>
              <div className="engrave !text-ember">Step {at + 1} of 3 · {Q[g.stage].title}</div>
              <div className="font-display text-[16px] font-[640] leading-snug">{Q[g.stage].q}</div>
              <p className="text-[12px] leading-relaxed text-ink-2">{Q[g.stage].hint}</p>
              {g.stage === "fps" && <SearchMeter s={g.fps} fmt={(v) => `${v} fps`} lowLabel="4 fps · lighter" highLabel="12 fps · heavier" />}
              {g.stage === "transition" && <div className="font-mono text-[11px] text-ink-3">A = {g.tr[0]} · B = {g.tr[1]}{g.trLeft.length ? ` · next: ${g.trLeft.join(", ")}` : " · final"}</div>}
              {g.stage === "smoothing" && <div className="font-mono text-[11px] text-ink-3">A = {sa.toFixed(2)} · B = {sb.toFixed(2)}</div>}
            </>
          ) : (
            <>
              <div className="font-display text-[17px] font-[640]">Your smoothest settings</div>
              <p className="text-[12px] text-ink-2">The bouncing ball now runs at your pick. Packet spacing stays at {Math.max(info.current.packet_gap_ms, info.limits.packet_gap_min_ms)} ms (fixed by the hardware tests).</p>
              <div className="grid grid-cols-3 gap-1.5 font-mono text-[11px]">
                <span className="rounded-lg bg-chassis-0 px-2.5 py-1.5">{res.fps} fps</span>
                <span className="rounded-lg bg-chassis-0 px-2.5 py-1.5">{res.transition}</span>
                <span className="rounded-lg bg-chassis-0 px-2.5 py-1.5">smooth {res.smoothing ? res.smoothing.toFixed(2) : "off"}</span>
              </div>
            </>
          )}
        </div>
      </div>
      {g.stage !== "done" ? (
        <ABKeys onPick={pick} sides={g.stage === "transition" ? ["first", "second"] : ["top", "bottom"]} sameLabel={g.stage === "transition" ? "No difference" : "Look the same"} />
      ) : (
        <div className="flex gap-2">
          <button className="key key-ghost" onClick={() => setG((x) => ({ ...x, stage: "fps", fps: startSearch(4, 12, 3, true, 8), tr: ["cut", "fade"], trLeft: ["push", "wipe"], sm: { ...startSearch(0, 0.6, 2, false, 0.3), d: 0.3 } }))}>Start over</button>
          <button className="key key-ember ml-auto" onClick={apply}><Check size={13} /> Apply</button>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ bench
const FPS = [4, 6, 8, 10, 12];
const SPEEDS = [4, 8, 12, 16];

function Bench({ info }: { info: MotionInfo }) {
  useClearOnUnmount();
  const [test, setTest] = useState("ufo");
  const [a, setA] = useState<MotionCfg>({ ...DEFAULT_MOTION });
  const [compare, setCompare] = useState(false);
  const [bFps, setBFps] = useState(12);
  const [layout, setLayout] = useState<"stack" | "alternate">("stack");
  const [native, setNative] = useState(false);

  useEffect(() => {
    setNative(false);
    api.motionTest({ test, a, b: compare ? { ...a, fps: bFps } : null, layout }).catch(() => undefined);
  }, [test, a, compare, bFps, layout]);

  const playNative = async () => {
    try {
      const r = await api.motionTest({ test, a, mode: "clip" });
      setNative(true);
      toast(`Playing as a native loop (${r.mode}) — compare it with the stream`, "ok");
    } catch {
      /* 429: the toast already says how long to wait */
    }
  };

  return (
    <div className="space-y-3">
      <VideoChips videos={info.tests} value={test} onChange={setTest} />
      <div className="flex flex-wrap items-start gap-4">
        <figure className="m-0">
          <div className="rounded-[10px] border border-line bg-black p-1.5"><LedPanel size={176} look="pixel" glow={false} lookSwitch={false} raw /></div>
          <figcaption className="engrave mt-1.5 text-center">{native ? "Panel: native loop · screen: stream" : "Same test, on screen"}</figcaption>
        </figure>
        <div className="min-w-[240px] flex-1 divide-y divide-line">
          <Row label="Frame rate" hint={compare ? "A (top / first)" : "How often the picture changes"}>
            <div className="seg">{FPS.map((f) => <button key={f} data-active={a.fps === f} onClick={() => setA({ ...a, fps: f })}>{f}</button>)}</div>
          </Row>
          <Row label="Speed" hint="Pixels per second">
            <div className="seg">{SPEEDS.map((v) => <button key={v} data-active={a.speed === v} onClick={() => setA({ ...a, speed: v })}>{v}</button>)}</div>
          </Row>
          <Row label="Soft edges" hint="Sub-pixel positions blend edge LEDs (shapes only — text stays 1-bit)">
            <Toggle on={a.soft} label="Soft edges" onChange={(v) => setA({ ...a, soft: v })} />
          </Row>
          {test === "live" && (
            <Row label="Smoothing"><Slider value={a.smoothing} min={0} max={0.6} step={0.05} width={140} onCommit={(v) => setA({ ...a, smoothing: v })} /></Row>
          )}
          {test === "transition" && (
            <Row label="Transition">
              <div className="seg">{(["cut", "push", "fade", "wipe"] as const).map((t) => <button key={t} data-active={a.transition === t} onClick={() => setA({ ...a, transition: t })}>{t}</button>)}</div>
            </Row>
          )}
          <Row label="Compare with" hint="B runs the same test at another rate">
            <Toggle on={compare} label="Compare" onChange={setCompare} />
            {compare && <div className="seg">{FPS.map((f) => <button key={f} data-active={bFps === f} onClick={() => setBFps(f)}>{f}</button>)}</div>}
          </Row>
          {compare && (
            <Row label="Layout">
              <div className="seg">
                <button data-active={layout === "stack"} onClick={() => setLayout("stack")}>A top · B bottom</button>
                <button data-active={layout === "alternate"} onClick={() => setLayout("alternate")}>A then B</button>
              </div>
            </Row>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <button className="key" onClick={playNative} title={`Bakes A as a GIF (≤ ${info.limits.clip_fps_max} fps, ≤ ${info.limits.gif_budget_kb} KB) and lets the panel play it by itself`}>
          <Icon name="repeat" size={13} /> Play as native loop
        </button>
        <span className="text-[11px] text-ink-4">Loops play inside the panel — the smoothest motion there is. One upload per 20 s.</span>
      </div>
    </div>
  );
}

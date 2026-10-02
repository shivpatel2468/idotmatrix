import clsx from "clsx";
import { Check, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { type Calib, type FieldKey, IDENTITY, type Search, candidates, choose, result, startSearch } from "../../lib/calib";
import { toast } from "../../lib/store";
import { Icon } from "../Icon";
import { ABKeys, PanelSketch, Progress, ScreenReference, SearchMeter, useClearOnUnmount, VideoChips, CAL_VIDEO_FALLBACK } from "./parts";

/**
 * The guided calibration: animated test videos play on the panel *and* on screen; each step asks
 * "which half looks closer to the screen?" and converges by halving (docs/CALIBRATION.md).
 */
type StepDef = {
  id: string;
  field: FieldKey;
  title: string;
  video: string;
  min: number;
  max: number;
  rounds: number;
  int?: boolean;
  q: string;
  hint: string;
  fmt?: (v: number) => string;
  low?: string;
  high?: string;
};

const STEPS: StepDef[] = [
  {
    id: "gamma", field: "gamma", title: "Mid-tones", video: "ramp", min: 1.0, max: 2.4, rounds: 4,
    q: "Which half's grey steps look most like the screen?",
    hint: "Compare the eight grey steps and the ramp sweeping up. The right answer has even jumps — no bunching at the bright end, no murky middle.",
    low: "brighter", high: "darker",
  },
  {
    id: "lift", field: "lift", title: "Black level", video: "pulse", min: 0, max: 16, rounds: 3, int: true,
    q: "Which half shows the dark patches most like the screen?",
    hint: "On the screen the dimmest patch is barely there. Pick the half where the faint patches are just visible and the pulsing bar fades all the way out.",
    fmt: (v) => v.toFixed(0), low: "deeper", high: "lifted",
  },
  {
    id: "blue", field: "blue", title: "White balance · blue", video: "white", min: 0.55, max: 1.05, rounds: 4,
    q: "Which half's white looks closer to the screen's white?",
    hint: "Most LED panels run blue-hot. Ignore brightness — look at the tint of the white and the greys. Pick the one that looks like paper, not ice or tea.",
    low: "warmer", high: "cooler",
  },
  {
    id: "green", field: "green", title: "White balance · green", video: "white", min: 0.65, max: 1.05, rounds: 3,
    q: "Which half's greys look less minty or less pink?",
    hint: "Now the green–magenta axis: one side may look slightly minty, the other slightly pink. Pick the more neutral grey.",
    low: "pinker", high: "mintier",
  },
  {
    id: "red", field: "red", title: "White balance · red", video: "skin", min: 0.7, max: 1.05, rounds: 3,
    q: "Which half's skin tones look more natural, like the screen?",
    hint: "Skin is where the eye notices red the most: too much looks sunburnt, too little looks grey or sickly.",
    low: "cooler skin", high: "redder skin",
  },
  {
    id: "saturation", field: "saturation", title: "Colour intensity", video: "bars", min: 0.7, max: 1.5, rounds: 3,
    q: "Which half's colour bars look most like the screen?",
    hint: "Too low looks washed out; too high makes neighbouring colours glow into each other. The grey ramp at the bottom must stay grey.",
    low: "softer", high: "bolder",
  },
];

const REVIEW_VIDEOS = ["card", "skin", "sky", "wheel", "bars"];

export function CalWizard({ saved, onDone, onAdvanced }: { saved: Calib; onDone: () => void; onAdvanced: (c: Calib) => void }) {
  useClearOnUnmount();
  const [phase, setPhase] = useState<"intro" | "steps" | "review">("intro");
  const [fresh, setFresh] = useState(false);
  const [i, setI] = useState(0);
  const [work, setWork] = useState<Calib>(saved);
  const [search, setSearch] = useState<Search | null>(null);
  const [history, setHistory] = useState<{ i: number; work: Calib }[]>([]);
  const [split, setSplit] = useState(16);
  const [video, setVideo] = useState("card");
  const step = STEPS[i];

  const begin = () => {
    const base = fresh ? { ...IDENTITY } : { ...saved };
    setWork(base);
    setHistory([]);
    setI(0);
    setSearch(startFor(0, base));
    setPhase("steps");
  };
  /** Refining starts the search around the current value (if it is in range); fresh starts mid-range. */
  const startFor = (k: number, base: Calib, isFresh = fresh) => {
    const s = STEPS[k];
    const cur = base[s.field];
    const q = (s.max - s.min) / 4;
    const centre = !isFresh && typeof cur === "number" && cur >= s.min && cur <= s.max ? Math.min(s.max - q, Math.max(s.min + q, cur)) : undefined;
    return startSearch(s.min, s.max, s.rounds, s.int, centre);
  };

  // show the A/B halves (or the before/after wipe) on the panel whenever the question changes
  const [ca, cb] = search ? candidates(search) : [0, 0];
  const candA = useMemo(() => (step ? { ...work, [step.field]: ca } : work), [work, step, ca]);
  const candB = useMemo(() => (step ? { ...work, [step.field]: cb } : work), [work, step, cb]);
  const normalised = useMemo(() => normaliseGains(work), [work]);
  useEffect(() => {
    if (phase === "steps" && step && search && !search.done) {
      api.calibTest({ video: step.video, a: candA, b: candB, layout: "ab", labels: ["A", "B"] }).catch(() => undefined);
    } else if (phase === "review") {
      api.calibTest({ video, a: saved, b: normalised, layout: "wipe", split, labels: ["OLD", "NEW"] }).catch(() => undefined);
    }
  }, [phase, step, search, candA, candB, video, split, saved, normalised]);

  const pick = (p: "a" | "b" | "same") => {
    if (!search || !step) return;
    const next = choose(search, p);
    const [na, nb] = candidates(next);
    if (next.done || (step.int && na === nb)) {
      const w = { ...work, [step.field]: result({ ...next, done: true }) };
      advance(w);
    } else setSearch(next);
  };
  const advance = (w: Calib) => {
    setHistory((h) => [...h, { i, work }]);
    setWork(w);
    if (i + 1 < STEPS.length) {
      setI(i + 1);
      setSearch(startFor(i + 1, w));
    } else {
      setSearch(null);
      setPhase("review");
    }
  };
  const back = () => {
    const last = history[history.length - 1];
    if (!last) return setPhase("intro");
    setHistory((h) => h.slice(0, -1));
    setWork(last.work);
    setI(last.i);
    setSearch(startFor(last.i, last.work));
    setPhase("steps");
  };
  const save = async () => {
    await api.calibration({ ...normalised, preset: "wizard" });
    await api.clearPattern();
    toast("Calibration saved — the panel now matches your screen", "ok");
    onDone();
  };

  if (phase === "intro") {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <div>
            <div className="font-display text-[18px] font-[620] leading-snug">Let's make the panel match your screen.</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
              Short test videos play on the panel and here at the same time. Each question shows two versions side by side
              on the panel — <b className="text-ink-1">A</b> on the left, <b className="text-ink-1">B</b> on the right — and you pick the one that looks
              closer to the screen. Every answer halves the guesswork, so six quick steps land on a precise match.
            </p>
          </div>
          <div className="flex items-center gap-2 font-mono text-[10.5px] text-ink-3 sm:flex-col sm:items-end">
            <span>~2 minutes</span><span>6 steps</span><span>~20 taps</span>
          </div>
        </div>
        <ul className="grid gap-1.5 text-[12px] text-ink-2 sm:grid-cols-3">
          {[
            ["sun", "Set the brightness you normally use"],
            ["eye", "Sit where you usually do and look straight at the panel"],
            ["lamp", "Avoid a lamp shining right onto the panel"],
          ].map(([icon, t]) => (
            <li key={t} className="flex items-start gap-2 rounded-lg bg-chassis-0 px-3 py-2"><Icon name={icon} size={14} className="mt-0.5 shrink-0 text-ember" />{t}</li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-3">
          <div className="seg">
            <button data-active={!fresh} onClick={() => setFresh(false)}>Refine my current colours</button>
            <button data-active={fresh} onClick={() => setFresh(true)}>Start fresh</button>
          </div>
          <button className="key key-ember ml-auto" onClick={begin}><Icon name="play" size={13} /> Start</button>
        </div>
        <p className="text-[11px] text-ink-4">Keys: <b>A</b> / ← picks the left half, <b>B</b> / → the right, <b>S</b> or space when they look the same.</p>
      </div>
    );
  }

  if (phase === "steps" && step && search) {
    return (
      <div className="space-y-4">
        <Progress steps={STEPS.length + 1} at={i} labels={[...STEPS.map((s) => s.title), "Before / after"]} />
        <div className="flex items-center justify-between">
          <div className="engrave !text-ember">Step {i + 1} of {STEPS.length} · {step.title}</div>
          <span className="font-mono text-[10.5px] text-ink-3">look at the real panel</span>
        </div>
        <div className="font-display text-[17px] font-[640] leading-snug">{step.q}</div>
        <div className="flex flex-wrap items-start gap-4">
          <ScreenReference size={176} split={16} />
          <PanelSketch a={candA} b={candB} size={112} caption="A | B as sent" />
          <p className="min-w-[180px] flex-1 text-[12px] leading-relaxed text-ink-2">{step.hint}</p>
        </div>
        <SearchMeter s={search} fmt={step.fmt} lowLabel={step.low} highLabel={step.high} />
        <ABKeys onPick={pick} />
        <div className="flex items-center gap-2 border-t border-line pt-3">
          <button className="key key-ghost" onClick={back}>Back</button>
          <button className="key key-ghost" onClick={() => setSearch(startFor(i, work))} title="Restart this step"><RotateCcw size={13} /> Redo step</button>
          <button className="key key-ghost ml-auto" onClick={() => advance(work)}>Skip (keep {fmtVal(work[step.field], step)})</button>
        </div>
      </div>
    );
  }

  // review: before / after wipe
  return (
    <div className="space-y-4">
      <Progress steps={STEPS.length + 1} at={STEPS.length} />
      <div className="font-display text-[18px] font-[640] leading-snug">Nice — here's the difference.</div>
      <p className="text-[12.5px] leading-relaxed text-ink-2">
        The panel shows your old colours left of the line and the new ones on the right. Drag the slider to wipe across, and try a few videos.
      </p>
      <div className="flex flex-wrap items-start gap-4">
        <ScreenReference size={176} split={split} />
        <PanelSketch a={saved} b={normalised} split={split} size={112} caption="Old | new as sent" />
        <div className="min-w-[200px] flex-1 space-y-3">
          <label className="block">
            <span className="engrave">Wipe · old ← → new</span>
            <input type="range" min={0} max={32} value={split} className="fader mt-1" style={{ ["--fill" as string]: `${(split / 32) * 100}%` }}
              onChange={(e) => setSplit(+e.target.value)} aria-label="Before / after split" />
          </label>
          <VideoChips videos={CAL_VIDEO_FALLBACK.filter((v) => REVIEW_VIDEOS.includes(v.id))} value={video} onChange={setVideo} />
          <ResultChips c={normalised} />
        </div>
      </div>
      <div className="flex flex-wrap gap-2 border-t border-line pt-3">
        <button className="key key-ghost" onClick={back}>Back</button>
        <button className="key key-ghost" onClick={() => setPhase("intro")}>Start over</button>
        <button className="key" onClick={() => onAdvanced(normalised)}><Icon name="sliders-horizontal" size={13} /> Fine-tune</button>
        <button className="key key-ember ml-auto" onClick={save}><Check size={13} /> Save calibration</button>
      </div>
    </div>
  );
}

function fmtVal(v: number | boolean | string, s: StepDef) {
  return typeof v === "number" ? (s.fmt ? s.fmt(v) : v.toFixed(2)) : String(v);
}

/** Keep the tint the user chose but drive the brightest channel fully (brightness is the brightness control's job). */
export function normaliseGains(c: Calib): Calib {
  const top = Math.max(c.red, c.green, c.blue);
  if (top <= 0 || top >= 0.999) return c;
  const r = (v: number) => Math.round((v / top) * 1000) / 1000;
  return { ...c, red: r(c.red), green: r(c.green), blue: r(c.blue) };
}

function ResultChips({ c }: { c: Calib }) {
  const white = `rgb(${255 * c.red},${255 * c.green},${255 * c.blue})`;
  return (
    <div className="grid grid-cols-2 gap-1.5 font-mono text-[10.5px] sm:grid-cols-4">
      <span className="flex items-center gap-1.5 rounded-lg bg-chassis-0 px-2.5 py-1.5"><span className="h-3 w-3 rounded-sm" style={{ background: white }} /> white</span>
      <span className="rounded-lg bg-chassis-0 px-2.5 py-1.5">γ {c.gamma.toFixed(2)}</span>
      <span className="rounded-lg bg-chassis-0 px-2.5 py-1.5">lift {c.lift}</span>
      <span className={clsx("rounded-lg bg-chassis-0 px-2.5 py-1.5")}>sat {c.saturation.toFixed(2)}</span>
    </div>
  );
}

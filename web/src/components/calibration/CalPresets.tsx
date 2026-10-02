import clsx from "clsx";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { type Calib, type CalibPreset, type PresetListing } from "../../lib/calib";
import { toast } from "../../lib/store";
import { Icon } from "../Icon";
import { Toggle } from "../controls";
import { PanelSketch, ScreenReference, Swatches, useClearOnUnmount, VideoChips, CAL_VIDEO_FALLBACK } from "./parts";

const GROUP_ORDER: CalibPreset["group"][] = ["claude", "inspired", "standard"];
const GROUP_ICON: Record<CalibPreset["group"], string> = { claude: "sparkles", inspired: "tv", standard: "ruler" };

/**
 * One-tap picture styles. "Try" plays a before/after wipe on the panel (nothing is saved, so clips aren't
 * re-baked on every click); "Use" saves it. Quick match asks three questions instead.
 */
export function CalPresets({ saved, onPicked }: { saved: Calib; onPicked: () => void }) {
  useClearOnUnmount();
  const [list, setList] = useState<PresetListing | null>(null);
  const [keep, setKeep] = useState(true);
  const [trying, setTrying] = useState<{ id: string; c: Calib } | null>(null);
  const [video, setVideo] = useState("card");
  const [quiz, setQuiz] = useState(false);

  useEffect(() => {
    api.calibPresets().then(setList).catch(() => setList(null));
  }, []);
  useEffect(() => {
    if (trying) api.calibTest({ video, a: saved, b: trying.c, layout: "wipe", split: 16, labels: ["NOW", "NEW"] }).catch(() => undefined);
  }, [trying, video, saved]);

  const tryIt = async (p: CalibPreset) => {
    if (p.id === "claude_quick") return setQuiz(true);
    const c = await api.calibPreset(p.id, keep, false);
    setTrying({ id: p.id, c });
  };
  const use = async (id: string, c?: Calib) => {
    if (c) await api.calibration(c);
    else await api.calibPreset(id, keep, true);
    await api.clearPattern();
    setTrying(null);
    toast("Preset applied", "ok");
    onPicked();
  };

  if (!list) return <div className="skeleton h-48 rounded-lg" />;
  const current = saved.preset;
  const name = (id: string) => list.presets.find((p) => p.id === id)?.name ?? id;

  return (
    <div className="space-y-4">
      {quiz && <QuickMatch saved={saved} onClose={() => setQuiz(false)} onUse={(c) => use("claude_quick", c)} />}
      {trying && !quiz && (
        <div className="rounded-xl border border-ember/40 bg-ember-deep/30 p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="engrave !text-ember">Trying on the panel</span>
            <span className="font-display text-[15px] font-[640]">{name(trying.id)}</span>
            <span className="text-[11.5px] text-ink-3">left = now, right = {name(trying.id)}</span>
          </div>
          <div className="flex flex-wrap items-start gap-3">
            <ScreenReference size={128} split={16} />
            <PanelSketch a={saved} b={trying.c} size={96} caption="Now | new as sent" />
            <div className="min-w-[180px] flex-1 space-y-2">
              <VideoChips videos={CAL_VIDEO_FALLBACK.filter((v) => ["card", "skin", "sky", "wheel", "bars", "ramp"].includes(v.id))} value={video} onChange={setVideo} />
              <div className="flex gap-2">
                <button className="key key-ember" onClick={() => use(trying.id, trying.c)}><Check size={13} /> Use this</button>
                <button className="key key-ghost" onClick={() => { setTrying(null); api.clearPattern(); }}>Stop trying</button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-chassis-0 px-3 py-2">
        <Toggle on={keep} onChange={setKeep} label="Keep my panel's white balance" />
        <div className="min-w-[200px] flex-1 text-[12px]">
          <div className="text-ink-1">Keep my panel's white balance</div>
          <div className="text-[11px] text-ink-3">A preset sets the picture style; your measured RGB gains stay. Turn off to use the preset's own gains.</div>
        </div>
      </div>

      {GROUP_ORDER.map((g) => (
        <section key={g}>
          <div className="mb-2 flex items-center gap-2">
            <Icon name={GROUP_ICON[g]} size={14} className="text-ember" />
            <h4 className="font-display text-[14px] font-[640]">{list.groups[g]}</h4>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {list.presets.filter((p) => p.group === g).map((p) => (
              <article key={p.id} className={clsx("group rounded-[10px] border bg-chassis-0 p-3 transition",
                current === p.id ? "border-ember" : trying?.id === p.id ? "border-ember/50" : "border-line hover:border-line-2")}>
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 text-[13px] font-[600]">
                      {p.name}
                      {current === p.id && <span className="engrave !text-ember">in use</span>}
                    </div>
                    <div className="mt-0.5 text-[11.5px] leading-snug text-ink-3">{p.blurb}</div>
                  </div>
                </div>
                <Swatches colors={p.swatches} className="mt-2" />
                <div className="mt-2 flex gap-1.5">
                  <button className="key !h-8" onClick={() => tryIt(p)}>
                    <Icon name={p.id === "claude_quick" ? "message-circle-question" : "eye"} size={12} /> {p.id === "claude_quick" ? "Answer 3 questions" : "Try"}
                  </button>
                  {p.id !== "claude_quick" && <button className="key key-ghost !h-8" onClick={() => use(p.id)}>Use</button>}
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
      <p className="text-[11px] leading-relaxed text-ink-4">{list.disclaimer}</p>
    </div>
  );
}

type Q = { key: "room" | "use" | "tint"; q: string; options: [string, string][] };
const QUIZ: Q[] = [
  { key: "room", q: "Where does the panel live?", options: [["bright", "Bright room / daylight"], ["dim", "Normal indoor light"], ["dark", "Dark room / evenings"]] },
  { key: "use", q: "What does it mostly show?", options: [["mixed", "A bit of everything"], ["text", "Clocks, text, dashboards"], ["photos", "Photos & art"], ["games", "Games & animations"]] },
  { key: "tint", q: "Look at a white screen on the panel: how does it look?", options: [["neutral", "White"], ["blue", "Bluish"], ["yellow", "Yellowish"], ["green", "Greenish"], ["pink", "Pinkish"]] },
];

/** "Quick match": three taps → a calibration (computed by the engine), previewed as a before/after wipe. */
function QuickMatch({ saved, onClose, onUse }: { saved: Calib; onClose: () => void; onUse: (c: Calib) => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Calib | null>(null);
  const at = QUIZ.findIndex((q) => !answers[q.key]);
  const q = at >= 0 ? QUIZ[at] : null;

  useEffect(() => {
    if (q?.key === "tint") api.calibTest({ video: "white", a: { ...saved, red: 1, green: 1, blue: 1, temperature: 6500, level: 1 } }).catch(() => undefined);
  }, [q?.key, saved]);
  useEffect(() => {
    if (at !== -1) return;
    api.calibQuick({ room: answers.room, use: answers.use, tint: answers.tint }).then((c) => {
      setResult(c);
      api.calibTest({ video: "card", a: saved, b: c, layout: "wipe", split: 16, labels: ["NOW", "NEW"] }).catch(() => undefined);
    }).catch(() => undefined);
  }, [at, answers, saved]);

  return (
    <div className="rounded-xl border border-ember/40 bg-ember-deep/30 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="sparkles" size={14} className="text-ember" />
        <span className="font-display text-[15px] font-[640]">Quick match</span>
        <span className="ml-auto font-mono text-[10.5px] text-ink-3">{Math.min(QUIZ.length, Object.keys(answers).length + (q ? 1 : 0))} / {QUIZ.length}</span>
      </div>
      {q ? (
        <div>
          <div className="mb-2 text-[13.5px] font-[560]">{q.q}</div>
          <div className="flex flex-wrap gap-1.5">
            {q.options.map(([v, label]) => (
              <button key={v} className="key" onClick={() => setAnswers({ ...answers, [q.key]: v })}>{label}</button>
            ))}
          </div>
          {q.key === "tint" && <p className="mt-2 text-[11.5px] text-ink-3">The panel is showing neutral greys with no white-balance correction right now.</p>}
        </div>
      ) : result ? (
        <div className="flex flex-wrap items-start gap-3">
          <ScreenReference size={128} split={16} />
          <PanelSketch a={saved} b={result} size={96} caption="Now | match as sent" />
          <div className="min-w-[180px] flex-1 space-y-2 text-[12px] text-ink-2">
            <p>Done. The panel shows your current colours on the left and the match on the right.</p>
            <div className="flex flex-wrap gap-2">
              <button className="key key-ember" onClick={() => onUse(result)}><Check size={13} /> Use it</button>
              <button className="key key-ghost" onClick={() => { setAnswers({}); setResult(null); }}>Answer again</button>
            </div>
          </div>
        </div>
      ) : (
        <div className="skeleton h-20 rounded-lg" />
      )}
      <button className="key key-ghost mt-3 !h-8" onClick={() => { onClose(); api.clearPattern(); }}>Close</button>
    </div>
  );
}

import clsx from "clsx";
import { Plus, Wand2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { EMPTY_LIST, toast, useStore } from "../lib/store";
import type { AppMeta, AutopilotRule } from "../lib/types";

/** Autopilot: "when this app is in front, show that on the panel". Rules are checked top to bottom. */
export function AutopilotEditor() {
  const ap = useStore((s) => s.state?.engine.autopilot);
  const apps = useStore((s) => s.meta?.apps ?? EMPTY_LIST) as AppMeta[];
  const current = useStore((s) => s.state?.engine.current?.status?.app) as string | undefined;
  const [rules, setRules] = useState<AutopilotRule[]>([]);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (ap && !dirty) setRules(ap.rules);
  }, [ap, dirty]);
  if (!ap) return null;

  const edit = (i: number, p: Partial<AutopilotRule>) => {
    setDirty(true);
    setRules(rules.map((r, k) => (k === i ? { ...r, ...p } : r)));
  };
  const save = async (enabled = ap.enabled, next = rules) => {
    await api.autopilot(enabled, next.filter((r) => r.match.trim()));
    setDirty(false);
    toast(enabled ? "Autopilot saved" : "Autopilot off", "ok");
  };

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <Wand2 size={13} className="text-ember" />
        <span className="engrave">Autopilot</span>
        <span className="text-[11px] text-ink-4">— the panel follows the app you're using</span>
        <button role="switch" aria-checked={ap.enabled} className="toggle ml-auto" onClick={() => save(!ap.enabled)} />
      </div>
      <div className={clsx("space-y-1.5", !ap.enabled && "opacity-50")}>
        {rules.map((r, i) => (
          <div key={i} className={clsx("flex items-center gap-2 rounded-lg p-1.5", ap.active === i && ap.enabled ? "bg-ember-deep/60 ring-1 ring-[#7a2a12]" : "bg-chassis-0")}>
            <span className="w-9 text-center font-mono text-[9px] text-ink-4">WHEN</span>
            <input className="field !h-7 !text-[12px]" value={r.match} placeholder="spotify · code · title:youtube"
              onChange={(e) => edit(i, { match: e.target.value })} />
            <span className="font-mono text-[9px] text-ink-4">SHOW</span>
            <select className="field !h-7 !w-40 !text-[12px]" value={r.app} onChange={(e) => edit(i, { app: e.target.value })}>
              {apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <button className="text-ink-4 hover:text-bad" title="Remove" onClick={() => { setDirty(true); setRules(rules.filter((_, k) => k !== i)); }}>
              <X size={13} />
            </button>
          </div>
        ))}
        <div className="flex gap-2 pt-1">
          <button className="key !h-8" onClick={() => { setDirty(true); setRules([...rules, { match: "", app: "activeapp", settings: {} }]); }}>
            <Plus size={12} /> Rule
          </button>
          {dirty && <button className="key key-ember !h-8" onClick={() => save()}>Save rules</button>}
          <span className="ml-auto self-center text-[10.5px] text-ink-4">
            Match part of the process name, or <code>title:</code> + window title{current ? ` · now: ${current}` : ""}
          </span>
        </div>
      </div>
    </section>
  );
}

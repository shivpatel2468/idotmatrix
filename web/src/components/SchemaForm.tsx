import clsx from "clsx";
import { Gamepad2, ImagePlus, Sparkles, Trash2, Workflow } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { EMPTY_MAP, useStore } from "../lib/store";
import type { AppSchema, JsonSchemaProp, MediaItem } from "../lib/types";

type Props = {
  schema: AppSchema;
  value: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
};

/**
 * Renders any app's pydantic settings model. Mapping (keep in sync with docs/APP_SDK.md):
 *   enum ≤ 4 options -> segmented · enum > 4 -> select · boolean -> toggle
 *   number/integer with min+max -> fader · format "color" -> swatches + picker
 *   format "media" -> media library picker · format "password" -> masked secret · long string -> textarea
 *   string -> input
 */
export function SchemaForm({ schema, value, onChange }: Props) {
  const props = Object.entries(schema.properties ?? {});
  if (!props.length) return <p className="text-[12.5px] text-ink-3">This app has no settings.</p>;
  // fields tagged with json_schema_extra.group render in collapsible sections, after the ungrouped ones
  const loose = props.filter(([, p]) => !p.group);
  const groups: [string, typeof props][] = [];
  for (const entry of props) {
    const g = entry[1].group;
    if (!g) continue;
    const found = groups.find(([name]) => name === g);
    if (found) found[1].push(entry);
    else groups.push([g, [entry]]);
  }
  // known groups in a fixed order (games: Game, Graphics, Game flow); any others keep their schema order
  groups.sort(([a], [b]) => (GROUP_ORDER[a] ?? 99) - (GROUP_ORDER[b] ?? 99));
  const field = ([key, p]: (typeof props)[number]) => (
    <Field key={key} name={key} p={p} v={value[key] ?? p.default} set={(v) => onChange({ [key]: v })} />
  );
  // essentials first: the first few ungrouped fields; everything else sits behind one "More options" disclosure
  const essentials = loose.slice(0, ESSENTIALS);
  const extra = loose.slice(ESSENTIALS);
  const hidden = extra.length + groups.reduce((n, [, e]) => n + e.length, 0);
  const group = ([name, entries]: [string, typeof props]) => {
    const Ico = GROUP_ICON[name];
    return (
    <details key={name} className="group/g rounded-xl border border-line bg-chassis-0/40">
      <summary className="flex cursor-pointer select-none list-none items-center gap-2 rounded-xl px-3 py-2.5 hover:bg-chassis-2/60">
        {Ico && <Ico size={13} className="shrink-0 text-ink-3" />}
        <span className="text-[12.5px] font-[560] text-ink-2">{name}</span>
        <span className="font-mono text-[9px] text-ink-4">{entries.length}</span>
        <span className="ml-auto text-ink-4 transition group-open/g:rotate-90">›</span>
      </summary>
      <div className="space-y-4 border-t border-line px-3 pb-3 pt-3">{entries.map(field)}</div>
    </details>
    );
  };
  return (
    <div className="space-y-4">
      {essentials.map(field)}
      {hidden > 0 && (
        <details className="group/more" open={!essentials.length}>
          <summary className="flex cursor-pointer select-none list-none items-center gap-2 rounded-[10px] border border-dashed border-line-2 px-3 py-2.5 text-[12.5px] text-ink-2 transition hover:border-ink-4 hover:text-ink-1">
            <span className="transition group-open/more:rotate-90">›</span>
            <span className="group-open/more:hidden">More options</span>
            <span className="hidden group-open/more:inline">Fewer options</span>
            <span className="ml-auto font-mono text-[10px] text-ink-4">{hidden}</span>
          </summary>
          <div className="space-y-4 pt-4">
            {extra.map(field)}
            {groups.map(group)}
          </div>
        </details>
      )}
    </div>
  );
}

const GROUP_ORDER: Record<string, number> = { Game: 0, Graphics: 1, "Game flow": 2 };
const GROUP_ICON: Record<string, typeof Gamepad2> = { Game: Gamepad2, Graphics: Sparkles, "Game flow": Workflow };

/** "Full (particles, shake, flashes)" → ["Full", "particles, shake, flashes"]: short key label + a hint line. */
function splitLabel(label: string): [string, string | null] {
  const m = /^(.*?)\s*\((.+)\)\s*$/.exec(label);
  return m && m[1] ? [m[1], m[2]] : [label, null];
}

/** How many settings the inspector shows before "More options". */
const ESSENTIALS = 5;

function Field({ name, p, v, set }: { name: string; p: JsonSchemaProp; v: unknown; set: (v: unknown) => void }) {
  const label = p.title ?? name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  const row = (control: React.ReactNode, inline = false) => (
    <div className={clsx("field-row", inline ? "field-row-inline flex items-center justify-between gap-3" : "field-row-stack")}>
      <div className={clsx("field-label mb-1.5 flex items-baseline justify-between gap-2", inline && "mb-0")}>
        <span className="text-[12.5px] font-[520] text-ink-1">{label}</span>
        {p.description && !inline && <span className="field-desc truncate text-[10.5px] text-ink-4" title={p.description}>{p.description}</span>}
      </div>
      <div className="field-control min-w-0">{control}</div>
    </div>
  );

  if (p.enum) {
    const labels = p.enumLabels ?? Object.fromEntries(p.enum.map((e) => [e, e]));
    if (p.enum.length <= 4) {
      const hint = splitLabel(labels[String(v)] ?? "")[1];
      return row(
        <>
          <div className="seg">
            {p.enum.map((opt) => (
              <button key={opt} data-active={v === opt} onClick={() => set(opt)} title={labels[opt]}>
                {splitLabel(labels[opt])[0]}
              </button>
            ))}
          </div>
          {hint && <p className="mt-1 text-[10.5px] text-ink-4">{hint[0].toUpperCase() + hint.slice(1)}</p>}
        </>,
      );
    }
    return row(
      <select className="field" value={String(v)} onChange={(e) => set(e.target.value)}>
        {p.enum.map((opt) => (
          <option key={opt} value={opt}>
            {labels[opt]}
          </option>
        ))}
      </select>,
    );
  }
  if (p.type === "boolean") {
    return row(<button role="switch" aria-checked={!!v} className="toggle" onClick={() => set(!v)} />, true);
  }
  if ((p.type === "integer" || p.type === "number") && p.minimum !== undefined && p.maximum !== undefined) {
    return row(<Fader p={p} v={Number(v)} set={set} />);
  }
  if (p.type === "integer" || p.type === "number") {
    return row(<input type="number" className="field" value={Number(v)} onChange={(e) => set(Number(e.target.value))} />);
  }
  if (p.format === "layers") {
    return row(
      <p className="rounded-lg border border-dashed border-line-2 px-3 py-2.5 text-[12px] text-ink-3">
        Edit layers directly on the panel preview — click to add, drag to move.
      </p>,
    );
  }
  if (p.format === "date-time" || p.format === "date") {
    const t = p.format === "date" ? "date" : "datetime-local";
    return row(
      <input type={t} className="field [color-scheme:dark]" value={String(v ?? "").slice(0, t === "date" ? 10 : 16)}
        onChange={(e) => e.target.value && set(e.target.value)} />,
    );
  }
  if (p.format === "password") return row(<SecretField v={String(v ?? "")} set={set} />);
  if (p.format === "color") return row(<ColorField v={String(v)} set={set} />);
  if (p.format === "media") return row(<MediaField v={String(v ?? "")} set={set} />);
  return row(<TextField p={p} v={String(v ?? "")} set={set} />);
}

function Fader({ p, v, set }: { p: JsonSchemaProp; v: number; set: (v: unknown) => void }) {
  const [local, setLocal] = useState(v);
  useEffect(() => setLocal(v), [v]);
  const step = p.type === "integer" ? 1 : (p.maximum! - p.minimum!) / 100;
  const fill = ((local - p.minimum!) / (p.maximum! - p.minimum!)) * 100;
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        className="fader"
        min={p.minimum}
        max={p.maximum}
        step={step}
        value={local}
        style={{ ["--fill" as string]: `${fill}%` }}
        onChange={(e) => {
          setLocal(+e.target.value);
          set(+e.target.value);
        }}
      />
      <span className="w-12 text-right font-mono text-[11px] tabular-nums text-ink-2">
        {p.type === "integer" ? local : local.toFixed(2)}
      </span>
    </div>
  );
}

function TextField({ p, v, set }: { p: JsonSchemaProp; v: string; set: (v: unknown) => void }) {
  const [local, setLocal] = useState(v);
  useEffect(() => setLocal(v), [v]);
  const long = (p.maxLength ?? 0) > 80;
  const commit = () => local !== v && set(local);
  return long ? (
    <textarea className="field" rows={3} value={local} maxLength={p.maxLength} onChange={(e) => setLocal(e.target.value)} onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && commit()} />
  ) : (
    <input className="field" value={local} maxLength={p.maxLength} onChange={(e) => setLocal(e.target.value)} onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()} />
  );
}

/** Tokens / API keys: the engine never sends the real value ("••••••" = set). Typing replaces it. */
function SecretField({ v, set }: { v: string; set: (v: unknown) => void }) {
  const isSet = v !== "";
  const [local, setLocal] = useState("");
  const commit = () => {
    if (local) set(local);
    setLocal("");
  };
  return (
    <div className="flex items-center gap-2">
      <input type="password" autoComplete="off" className="field" value={local}
        placeholder={isSet ? "Saved — type to replace" : "Not set"}
        onChange={(e) => setLocal(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
      {isSet && (
        <button className="key key-ghost !px-2" title="Remove the saved secret" onClick={() => set("")}>Clear</button>
      )}
    </div>
  );
}

function ColorField({ v, set }: { v: string; set: (v: unknown) => void }) {
  const palette = useStore((s) => s.meta?.palette ?? EMPTY_MAP);
  const tokens = Object.entries(palette).filter(([k]) => !["black", "ink", "ok", "warn", "bad", "info"].includes(k));
  return (
    <div className="flex items-center gap-2">
      <label className="relative h-8 w-11 shrink-0 overflow-hidden rounded-[8px] border border-line-2" style={{ background: v, boxShadow: `0 0 14px -4px ${v}` }}>
        <input type="color" value={v} onChange={(e) => set(e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
      <div className="flex flex-wrap gap-1">
        {tokens.map(([name, c]) => (
          <button
            key={name}
            title={name}
            onClick={() => set(c)}
            className={clsx("h-[18px] w-[18px] rounded-[5px] border transition hover:scale-110", v.toLowerCase() === c ? "border-white" : "border-black/40")}
            style={{ background: c }}
          />
        ))}
      </div>
    </div>
  );
}

function MediaField({ v, set }: { v: string; set: (v: unknown) => void }) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const load = () => api.media().then(setItems);
  useEffect(() => void load(), []);
  return (
    <div className="grid grid-cols-4 gap-1.5">
      <button onClick={() => input.current?.click()} className="grid aspect-square place-items-center rounded-[9px] border border-dashed border-line-2 text-ink-3 transition hover:border-ember hover:text-ember" title="Upload">
        <ImagePlus size={16} />
        <input ref={input} type="file" accept="image/*" hidden onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          const it = await api.upload(f, false);
          await load();
          set(it.id);
        }} />
      </button>
      {items.map((m) => (
        <div key={m.id} className="group relative">
          <button onClick={() => set(m.id)} title={`${m.name} · ${m.width}×${m.height}${m.frames > 1 ? ` · ${m.frames} frames` : ""}`}
            className={clsx("block aspect-square w-full overflow-hidden rounded-[9px] border bg-black", v === m.id ? "border-ember shadow-[0_0_14px_-3px_var(--color-ember)]" : "border-line")}>
            <img src={`/api/media/${m.id}/preview.png?scale=4`} alt={m.name} className="h-full w-full [image-rendering:pixelated]" />
          </button>
          <button onClick={async () => { await api.deleteMedia(m.id); load(); }} title="Delete"
            className="absolute right-1 top-1 hidden rounded bg-black/70 p-0.5 text-ink-2 hover:text-bad group-hover:block">
            <Trash2 size={11} />
          </button>
        </div>
      ))}
    </div>
  );
}

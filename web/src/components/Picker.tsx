import clsx from "clsx";
import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMedia } from "../lib/useMedia";
import { Icon, IconTile } from "./Icon";
import { Sheet } from "./Sheet";

export type PickerOption = {
  value: string;
  label: string;
  /** A second line under the label. */
  hint?: string;
  /** A lucide icon name (kebab-case), shown as a small tinted tile. */
  icon?: string;
  /** The tile's tint (an app category or accent, see IconTile). */
  tone?: string;
  /** A colour chip instead of an icon. */
  swatch?: string;
  disabled?: boolean;
};

/**
 * The studio's dropdown — replaces native <select>s. Touch screens get a bottom sheet with big rows (icon, name,
 * description, a check on the current one); mouse screens get an anchored list that works like a select from the
 * keyboard (↑ ↓ Home End, Enter, Esc, type a letter to jump). More than 10 options add a search box.
 */
export function Picker({ value, options, onChange, label, className, size = "md", disabled, placeholder = "Choose…", returnFocus = true }: {
  value: string;
  options: PickerOption[];
  onChange: (v: string) => void;
  /** Accessible name; also the sheet's title on phones. */
  label: string;
  className?: string;
  size?: "sm" | "md";
  disabled?: boolean;
  placeholder?: string;
  /** false: after a choice, focus leaves the key (Play mode hands the arrow keys back to the game). */
  returnFocus?: boolean;
}) {
  const touch = useMedia("(pointer: coarse), (max-width: 767.98px)");
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const btn = useRef<HTMLButtonElement>(null);
  const cur = options.find((o) => o.value === value);
  const searchable = options.length > 10;
  const list = useMemo(() => {
    const f = q.trim().toLowerCase();
    return f ? options.filter((o) => `${o.label} ${o.hint ?? ""} ${o.value}`.toLowerCase().includes(f)) : options;
  }, [options, q]);
  const close = () => {
    setOpen(false);
    setQ("");
  };
  const choose = (o: PickerOption) => {
    if (o.disabled) return;
    if (o.value !== value) onChange(o.value);
    close();
    if (touch) return;
    if (returnFocus) btn.current?.focus();
    else btn.current?.blur();
  };

  return (
    <>
      <button ref={btn} type="button" disabled={disabled} className={clsx("field picker-trigger", size === "sm" && "picker-sm", className)}
        aria-haspopup={touch ? "dialog" : "listbox"} aria-expanded={open} aria-label={`${label}: ${cur?.label ?? placeholder}`}
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={(e) => {
          if (touch || open) return;
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
          }
        }}>
        <OptionLead o={cur} small />
        <span className={clsx("min-w-0 flex-1 truncate text-left", !cur && "text-ink-4")}>{cur?.label ?? placeholder}</span>
        <ChevronDown size={size === "sm" ? 13 : 15} className={clsx("shrink-0 text-ink-3 transition-transform", open && "rotate-180")} />
      </button>
      {touch ? (
        <Sheet open={open} onClose={close} title={label}>
          {searchable && (
            <label className="relative mb-2 block">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
              <input className="field !h-11 !pl-9" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} aria-label={`Search ${label}`} />
            </label>
          )}
          <div className="picker-sheet" role="listbox" aria-label={label}>
            {list.map((o) => (
              <button key={o.value} type="button" role="option" aria-selected={o.value === value} disabled={o.disabled}
                className="picker-row" onClick={() => choose(o)}>
                <OptionLead o={o} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14.5px] font-[560] leading-snug text-ink-1">{o.label}</span>
                  {o.hint && <span className="block text-[12px] leading-snug text-ink-3">{o.hint}</span>}
                </span>
                {o.value === value && <Check size={18} className="shrink-0 text-ember" />}
              </button>
            ))}
            {!list.length && <p className="py-6 text-center text-[13px] text-ink-3">Nothing matches.</p>}
          </div>
        </Sheet>
      ) : (
        open && <Popover anchor={btn} options={list} value={value} label={label} searchable={searchable} q={q} setQ={setQ} onChoose={choose} onClose={close} />
      )}
    </>
  );
}

function OptionLead({ o, small = false }: { o?: PickerOption; small?: boolean }) {
  if (!o) return null;
  if (o.swatch) return <span className={clsx("shrink-0 rounded-[6px] border border-black/20", small ? "h-4 w-4" : "h-7 w-7")} style={{ background: o.swatch }} />;
  if (!o.icon) return null;
  return small
    ? <Icon name={o.icon} size={14} duo className="shrink-0 text-ink-2" />
    : <IconTile name={o.icon} tone={o.tone ?? "neutral"} size={32} glyph={16} />;
}

function Popover({ anchor, options, value, label, searchable, q, setQ, onChoose, onClose }: {
  anchor: React.RefObject<HTMLButtonElement | null>;
  options: PickerOption[];
  value: string;
  label: string;
  searchable: boolean;
  q: string;
  setQ: (q: string) => void;
  onChoose: (o: PickerOption) => void;
  onClose: () => void;
}) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number; width: number; max: number } | null>(null);
  const [active, setActive] = useState(() => Math.max(0, options.findIndex((o) => o.value === value)));

  useLayoutEffect(() => {
    const place = () => {
      const r = anchor.current?.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom - 12;
      const above = r.top - 12;
      const width = Math.max(r.width, 220);
      const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
      setPos(below >= 220 || below >= above
        ? { left, top: r.bottom + 6, width, max: Math.min(360, below) }
        : { left, bottom: window.innerHeight - r.top + 6, width, max: Math.min(360, above) });
    };
    const onScroll = (e: Event) => !box.current?.contains(e.target as Node) && place(); // the page moved, not our list
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [anchor]);

  useEffect(() => {
    const out = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node) && !anchor.current?.contains(e.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", out, true);
    return () => window.removeEventListener("pointerdown", out, true);
  }, [anchor, onClose]);

  useEffect(() => setActive((a) => Math.min(a, Math.max(0, options.length - 1))), [options.length]);
  useEffect(() => {
    box.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, pos]);
  useEffect(() => {
    if (!searchable) box.current?.focus();
  }, [searchable]);

  const step = (d: number) => {
    if (!options.length) return;
    let i = active;
    for (let k = 0; k < options.length; k++) {
      i = (i + d + options.length) % options.length;
      if (!options[i].disabled) break;
    }
    setActive(i);
  };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(options.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); if (options[active]) onChoose(options[active]); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); onClose(); anchor.current?.focus(); }
    else if (!searchable && e.key.length === 1 && /\S/.test(e.key)) {
      const k = e.key.toLowerCase();
      const n = options.length;
      for (let j = 1; j <= n; j++) {
        const i = (active + j) % n;
        if (options[i].label.toLowerCase().startsWith(k)) { setActive(i); break; }
      }
    }
  };

  if (!pos) return null;
  return createPortal(
    <div ref={box} className="picker-pop surface animate-rise" role="dialog" aria-label={label} tabIndex={-1} onKeyDown={key}
      style={{ left: pos.left, top: pos.top, bottom: pos.bottom, width: pos.width, maxHeight: pos.max }}>
      {searchable && (
        <label className="relative m-1.5 mb-1 block shrink-0">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-4" />
          <input autoFocus className="field !h-8 !pl-8 !text-[12.5px]" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)}
            aria-controls={id} aria-activedescendant={options[active] ? `${id}-${active}` : undefined} />
        </label>
      )}
      <div id={id} role="listbox" aria-label={label} className="min-h-0 overflow-y-auto p-1">
        {options.map((o, i) => (
          <button key={o.value} id={`${id}-${i}`} data-i={i} type="button" role="option" aria-selected={o.value === value} disabled={o.disabled}
            tabIndex={-1} data-active={i === active} className="picker-item" onMouseEnter={() => setActive(i)} onClick={() => onChoose(o)}>
            {o.swatch ? <span className="h-4 w-4 shrink-0 rounded-[5px] border border-black/20" style={{ background: o.swatch }} />
              : o.icon ? <IconTile name={o.icon} tone={o.tone ?? "neutral"} size={24} glyph={13} /> : null}
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] text-ink-1">{o.label}</span>
              {o.hint && <span className="block truncate text-[11px] text-ink-3">{o.hint}</span>}
            </span>
            {o.value === value && <Check size={14} className="shrink-0 text-ember" />}
          </button>
        ))}
        {!options.length && <p className="px-3 py-4 text-center text-[12px] text-ink-3">Nothing matches.</p>}
      </div>
    </div>,
    document.body,
  );
}

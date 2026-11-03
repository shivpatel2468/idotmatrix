import clsx from "clsx";
import { Download, RefreshCw, Sparkles, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { joinContinuations } from "../lib/notes";
import { toast, useStore } from "../lib/store";
import type { UpdatesInfo } from "../lib/types";
import { Row, Toggle } from "./controls";
import { openUpdates } from "./UpdatesSheet";

/**
 * In-app updates (src/deskdot/updates.py, docs/API.md § Updates): the Settings block and the top-bar pill; both open
 * the Updates sheet (UpdatesSheet.tsx), which holds the notes, the install and its live steps.
 * The engine checks GitHub Releases at most every 6 h; installing downloads the installer for this system, checks
 * its SHA-256 and hands off (Windows / macOS restart DeskDot; Android opens its installer). The browser app
 * (kind "web") reads its site's /app/version.json instead and offers a reload when a new build is out.
 */

const DISMISS_KEY = "deskdot.update.dismissed";

function dismissed(): string | null {
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

export function updatesAgo(t: number | null): string {
  if (!t) return "never";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
}

// ------------------------------------------------------------------ release notes (WHATS_NEW-style markdown)
/** `**bold**`, `` `code` `` and [links](https://…) inside a line; everything else is plain text. */
export function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-[620] text-ink-1">{p.slice(2, -2)}</strong>;
        if (p.startsWith("`") && p.endsWith("`")) return <code key={i} className="rounded bg-chassis-3 px-1 font-mono text-[11px]">{p.slice(1, -1)}</code>;
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(p);
        if (link) {
          return link[2].startsWith("https://")
            ? <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer" className="text-ember underline-offset-2 hover:underline">{link[1]}</a>
            : <Fragment key={i}>{link[1]}</Fragment>;
        }
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}

/** Headings (##/###), bullets with one nested level ("Before:" / "Now:"), paragraphs. No HTML is ever injected. */
export function ReleaseNotes({ text }: { text: string }) {
  const lines = joinContinuations(text.replace(/<!--[\s\S]*?-->/g, "").replace(/\r/g, "").split("\n"));
  const out: React.ReactNode[] = [];
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (!line.trim()) return;
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      out.push(<div key={i} className={clsx("font-[640] text-ink-1", h[1].length <= 2 ? "mt-3 text-[13.5px]" : "engrave mt-3 !text-[9.5px]")}><Inline text={h[2]} /></div>);
      return;
    }
    const b = /^(\s*)[-*]\s+(.*)$/.exec(line);
    if (b) {
      const nested = b[1].length >= 2;
      const label = /^(Before|Now):\s*(.*)$/.exec(b[2]);
      out.push(
        <div key={i} className={clsx("flex gap-2 leading-relaxed", nested ? "ml-4 text-[12px] text-ink-2" : "mt-1.5 text-[12.5px] text-ink-1")}>
          <span aria-hidden className="text-ink-4">{nested ? "–" : "•"}</span>
          <span className="min-w-0">
            {label ? <><span className={clsx("font-[600]", label[1] === "Now" ? "text-ok" : "text-ink-3")}>{label[1]}:</span> <Inline text={label[2]} /></> : <Inline text={b[2]} />}
          </span>
        </div>,
      );
      return;
    }
    out.push(<p key={i} className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2"><Inline text={line.trim()} /></p>);
  });
  return <div>{out}</div>;
}

// ------------------------------------------------------------------ Settings → Device → Updates
/** A short status line and the automatic-check switch; everything else lives in the Updates sheet. */
export function UpdatesBlock() {
  const brief = useStore((s) => s.state?.updates);
  const [info, setInfo] = useState<UpdatesInfo | null>(null);

  useEffect(() => {
    let live = true;
    api.updates().then((i) => live && setInfo(i)).catch(() => {});
    return () => { live = false; };
  }, [brief?.current, brief?.latest, brief?.status, brief?.error]);

  if (!info) return <div className="text-[12.5px] text-ink-3">Looking for the version…</div>;
  const status = brief?.status ?? info.status;
  const available = brief?.available ?? info.available;
  const busy = status === "downloading" || status === "verifying" || status === "installing";
  const web = info.kind === "web";
  const headline = busy
    ? "Updating…"
    : available
      ? web && info.latest === info.current ? "A new build of the browser app is ready" : `DeskDot ${info.latest} is available`
      : status === "error" ? "Couldn't check for updates" : info.latest ? "You have the latest version" : "DeskDot";
  return (
    <>
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-chassis-0 px-3 py-3">
        <span className="led" data-on={available ? "ember" : status === "error" ? "warn" : "ok"} />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-[560]">{headline}</div>
          <div className="text-[11.5px] text-ink-3">This is version {info.current} · checked {updatesAgo(info.checked_at)}</div>
        </div>
        <button className={clsx("key", available && "key-ember")} onClick={openUpdates}>
          {available ? <Download size={13} /> : <RefreshCw size={13} />} Open updates
        </button>
      </div>

      <div className="mt-2 divide-y divide-line">
        <Row label="Check for updates automatically" hint={web
          ? "About every 30 minutes this tab asks idotmatrix.com which version it serves. Nothing about you is sent."
          : "About every 6 hours DeskDot asks GitHub if there's a new version. Nothing about you is sent."}>
          <Toggle on={info.auto_check} label="Check for updates automatically" onChange={async (v) => setInfo(await api.setUpdates(v))} />
        </Row>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ the top-bar pill
/** "Update available": a small pill (and one toast per version) when a newer DeskDot is out. */
export function UpdatePill({ compact = false }: { compact?: boolean }) {
  const u = useStore((s) => s.state?.updates);
  const [hidden, setHidden] = useState<string | null>(() => dismissed());
  const toasted = useRef<string | null>(null);
  const latest = u?.available ? (u.kind === "web" && u.latest_build ? `${u.latest} (${u.latest_build})` : u.latest) : null;
  const web = u?.kind === "web";

  useEffect(() => {
    if (!latest || latest === hidden || toasted.current === latest) return;
    toasted.current = latest;
    toast(web ? "A new version of the browser app is ready — reload the page to get it" : `DeskDot ${latest} is available — Settings → Updates`, "info");
  }, [latest, hidden, web]);

  if (!latest || latest === hidden) return null;
  const busy = u?.status === "downloading" || u?.status === "verifying" || u?.status === "installing";
  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, latest); } catch { /* private mode */ }
    setHidden(latest);
  };
  return (
    <span className="glass-capsule lg-toolbar inline-flex shrink-0 items-center">
      <button onClick={openUpdates} aria-haspopup="dialog" title={`DeskDot ${latest} is available — see what's new and install`}
        className={clsx("flex items-center gap-1.5 rounded-full py-1.5 text-[12px] font-medium text-ember transition hover:bg-[var(--lg-control-hover)]", compact ? "px-2" : "pl-2.5 pr-1.5")}>
        <Sparkles size={13} />
        {compact ? <span className="sr-only">Update available</span> : <span>{busy ? "Updating…" : web ? "New version — reload" : "Update available"}</span>}
      </button>
      {!compact && !busy && (
        <button className="key key-ghost key-icon !h-6 !w-6" aria-label="Hide until the next version" title="Hide until the next version" onClick={dismiss}>
          <X size={12} />
        </button>
      )}
    </span>
  );
}

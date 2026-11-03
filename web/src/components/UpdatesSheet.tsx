import clsx from "clsx";
import { AlertTriangle, ArrowRight, Download, Globe, Laptop, RefreshCw, RotateCcw, Smartphone, Terminal } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "../lib/api";
import { openSettings, useStore } from "../lib/store";
import type { UpdateKind, UpdatesInfo } from "../lib/types";
import { type BusyStatus, flowSteps, isBusy, primaryAction } from "../lib/updateFlow";
import { StepIcon } from "./ConnectionSheet";
import { Sheet } from "./Sheet";
import { Inline, ReleaseNotes, updatesAgo } from "./Updates";

/*
 * The Updates sheet (docs/STUDIO_UI.md "Updates"): which version this is, which one is new, what's new in it, and
 * the one thing to do — built like the Connection sheet (same Sheet, cards and live steps). Opened from the top bar's
 * update pill and Settings → Updates. The engine does the work (src/deskdot/updates.py, docs/API.md § Updates):
 * download → check against checksums.txt → install → restart (Android: its own installer takes over); the browser
 * app reads its site's /app/version.json and reloads. The steps come from lib/updateFlow.ts.
 */

// ------------------------------------------------------------------ open / close (no global store change needed)
let open = false;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
export function openUpdates() {
  open = true;
  emit();
}
function closeUpdates() {
  open = false;
  emit();
}
const useOpen = () => useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), () => open);

// ------------------------------------------------------------------ helpers
const WHERE: Record<UpdateKind, [string, typeof Laptop]> = {
  windows: ["DeskDot for Windows", Laptop],
  macos: ["DeskDot for Mac", Laptop],
  android: ["The DeskDot Android app", Smartphone],
  source: ["Running from source", Terminal],
  web: ["The browser app", Globe],
};

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5 text-[12.5px]">
      <span className="w-28 shrink-0 text-ink-3">{k}</span>
      <span className="min-w-0 flex-1 text-ink-1">{v}</span>
    </div>
  );
}

type Run = { lastBusy: BusyStatus | null; result: string | null; target: string | null; reloading: boolean };
const FRESH: Run = { lastBusy: null, result: null, target: null, reloading: false };

// ------------------------------------------------------------------ the sheet
export function UpdatesSheet() {
  const isOpen = useOpen();
  const brief = useStore((s) => s.state?.updates);
  const linkOpen = useStore((s) => s.link === "open");
  const [info, setInfo] = useState<UpdatesInfo | null>(null);
  const [run, setRun] = useState<Run>(FRESH);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);

  // the engine reports one step at a time: remember the last busy one so a failure lands on it (always mounted,
  // so an install keeps its steps while the sheet is closed)
  const status = brief?.status ?? info?.status ?? "idle";
  useEffect(() => {
    if (isBusy(status)) setRun((r) => (r.lastBusy === status ? r : { ...r, lastBusy: status, target: r.target ?? brief?.latest ?? null }));
  }, [status, brief?.latest]);

  // the details (notes, assets, messages) whenever the sheet is open and the engine's short status changes
  useEffect(() => {
    if (!isOpen) return;
    let live = true;
    api.updates().then((i) => live && setInfo(i)).catch(() => {});
    return () => {
      live = false;
    };
  }, [isOpen, linkOpen, brief?.current, brief?.latest, brief?.latest_build, brief?.status, brief?.error]);

  // a finished run is forgotten when the sheet closes (not while it is still working or restarting)
  useEffect(() => {
    if (!isOpen && !isBusy(status) && run.result !== "restart" && !run.reloading && run !== FRESH) setRun(FRESH);
  }, [isOpen, status, run]);

  if (!isOpen) return null;

  const close = closeUpdates;
  const kind: UpdateKind = info?.kind ?? brief?.kind ?? "windows";
  const web = kind === "web";
  const current = brief?.current ?? info?.current ?? "";
  const latest = brief?.latest ?? info?.latest ?? null;
  const available = brief?.available ?? info?.available ?? false;
  const error = brief?.error ?? info?.error ?? null;
  const progress = brief?.progress ?? info?.progress ?? null;
  const [where, WhereIcon] = WHERE[kind];
  const steps = flowSteps({
    kind, status, progress, lastBusy: run.lastBusy, result: run.result, target: run.target, current, linkOpen, reloading: run.reloading,
  });
  const primary = primaryAction({ kind, available, canInstall: !!info?.can_install, status, lastBusy: run.lastBusy, result: run.result });
  const restarted = run.result === "restart" && linkOpen && !!run.target && current === run.target;
  const restarting = run.result === "restart" && !restarted;
  const working = starting || isBusy(status) || restarting || run.reloading;

  const tone = restarted ? "ok" : working ? "warn" : status === "error" ? "bad" : available ? "ember" : status === "checking" ? "warn" : "ok";
  const title = restarted
    ? `Updated to DeskDot ${current}`
    : restarting
      ? "Restarting DeskDot…"
      : working
        ? `Updating to ${run.target ?? latest ?? "the new version"}…`
        : status === "checking"
          ? "Checking for updates…"
          : available
            ? web && latest === current ? "A new build of the browser app is ready" : `DeskDot ${latest} is available`
            : status === "error"
              ? "Couldn't check for updates"
              : info?.checked_at || latest ? "Up to date" : "DeskDot";

  const check = async () => {
    setChecking(true);
    try {
      setInfo(await api.checkUpdates());
      setRun(FRESH);
    } catch {
      /* api.req already toasted */
    } finally {
      setChecking(false);
    }
  };
  const install = async () => {
    setRun({ ...FRESH, target: latest });
    setStarting(true);
    try {
      const r = await api.installUpdate();
      setInfo(r);
      setRun((x) => ({ ...x, result: r.result }));
    } catch {
      /* api.req already toasted; the engine's error shows on its step */
    } finally {
      setStarting(false);
    }
  };
  const reload = () => {
    setRun({ ...FRESH, reloading: true });
    requestAnimationFrame(() => requestAnimationFrame(() => window.location.reload())); // let the step paint first
  };

  const installLabel = kind === "android" ? "Download & install" : "Install & restart";
  const showNotes = available && !!info?.notes && !restarted;
  const message = info?.message && !restarted ? info.message : null;

  const footer = (
    <div className="flex flex-wrap gap-2">
      {primary === "install" && (
        <button className="key key-ember" disabled={working} onClick={install}>
          <Download size={13} /> {starting ? "Starting…" : installLabel}
        </button>
      )}
      {primary === "reload" && (
        <button className="key key-ember" disabled={working} onClick={reload}>
          <RefreshCw size={13} /> Reload
        </button>
      )}
      <button className="key" disabled={checking || working || status === "checking"} onClick={check}>
        <RefreshCw size={13} className={clsx((checking || status === "checking") && "animate-spin")} /> {checking || status === "checking" ? "Checking…" : "Check now"}
      </button>
    </div>
  );

  return (
    <Sheet open onClose={close} title="Updates" footer={footer}>
      <div className="space-y-3">
        <section className="qs-card">
          <div className="flex items-start gap-3">
            <span className="led mt-1.5 shrink-0" data-on={tone} />
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-[620] leading-snug">{title}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-3">
                <WhereIcon size={12} className="shrink-0" /> {where}
              </div>
            </div>
          </div>
          <div className="mt-3 border-t border-line pt-2">
            <Row
              k="Version"
              v={
                available && latest && !restarted ? (
                  <span className="inline-flex flex-wrap items-center gap-1.5 font-mono text-[12px]">
                    <span className="text-ink-2">{current}</span>
                    <ArrowRight size={12} className="text-ink-3" aria-label="to" />
                    <span className="font-[620] text-ember">{latest}</span>
                  </span>
                ) : (
                  <span className="font-mono text-[12px]">{current}</span>
                )
              }
            />
            {web && info?.build && (
              <Row k="Build" v={<span className="font-mono text-[11.5px]">{info.build}{available && info.latest_build ? ` → ${info.latest_build}` : ""}</span>} />
            )}
            <Row k="Last checked" v={updatesAgo(info?.checked_at ?? null)} />
          </div>
        </section>

        {(steps || (status === "error" && error)) && (
          <section className={`rounded-xl border p-3 text-[12.5px] ${status === "error" ? "border-bad/30 bg-bad/10" : "border-line bg-chassis-0"}`} aria-live="polite">
            {steps && (
              <ol className="space-y-1">
                {steps.map((s) => (
                  <li key={s.id} className={`flex items-center gap-2 ${s.state === "todo" ? "text-ink-3" : "text-ink-1"}`}>
                    <span className="flex w-4 justify-center"><StepIcon state={s.state} /></span>
                    {s.label}
                    {s.detail && <span className="ml-auto font-mono text-[11px] tabular-nums text-ink-3">{s.detail}</span>}
                  </li>
                ))}
              </ol>
            )}
            {steps?.[0]?.detail && (
              <div className="ml-6 mt-1.5 h-1 overflow-hidden rounded-full bg-chassis-3" role="progressbar" aria-label="Download progress"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((progress ?? 0) * 100)}>
                <div className="h-full origin-left rounded-full bg-ember transition-transform" style={{ transform: `scaleX(${progress ?? 0})` }} />
              </div>
            )}
            {status === "error" && error && (
              <div className={clsx("flex gap-2.5", steps && "mt-2")}>
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-bad" />
                <p className="min-w-0 text-ink-1">{error}</p>
              </div>
            )}
            {(primary === "retry-install" || primary === "retry-check") && (
              <button className="key mt-2.5" disabled={checking || starting} onClick={primary === "retry-install" ? install : check}>
                <RotateCcw size={13} /> Retry
              </button>
            )}
          </section>
        )}

        {message && (
          <p className={clsx("px-1 text-[12.5px]", run.result === "permission" ? "text-warn" : "text-ok")}>{message}</p>
        )}

        {available && !working && !steps && (
          info?.can_install ? (
            <p className="px-1 text-[12px] leading-snug text-ink-3">
              {kind === "android"
                ? "Downloads the new version and checks it; then Android asks you to confirm. Your settings stay."
                : "Downloads the new version, checks it against the release's checksums, installs it and opens DeskDot again. Your settings stay."}
            </p>
          ) : web ? (
            <p className="px-1 text-[12px] leading-snug text-ink-3">
              The browser app updates with the website: reloading this tab loads the new version. Your settings and uploads
              stay in this browser.
            </p>
          ) : kind === "source" ? (
            <p className="px-1 text-[12px] leading-relaxed text-ink-2"><Inline text={info?.source_hint ?? ""} /></p>
          ) : info ? (
            <p className="px-1 text-[12px] text-ink-2">
              There's no installer for your system in this release yet.{" "}
              <a className="text-ember hover:underline" href={info.url} target="_blank" rel="noopener noreferrer">See the release on GitHub</a>
            </p>
          ) : null
        )}

        {showNotes && (
          <section className="qs-card">
            <div className="text-[12px] font-[620] uppercase tracking-wide text-ink-3">What's new in {latest}</div>
            <ReleaseNotes text={info!.notes} />
          </section>
        )}

        <button className="key key-ghost !px-0 text-ink-3" onClick={() => { close(); openSettings("updates"); }}>
          Update settings
        </button>
      </div>
    </Sheet>
  );
}

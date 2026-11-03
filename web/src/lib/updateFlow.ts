import type { UpdateKind, UpdateStatus } from "./types";

/*
 * The Updates sheet's live steps (components/UpdatesSheet.tsx), as a pure function so node can test it
 * (tests/js/update_flow.test.mjs). The engine reports one status at a time (src/deskdot/updates.py:
 * downloading → verifying → installing, or error); the studio remembers the last busy one it saw so a failure lands
 * on the step it happened in. Percentages come only from the engine's `progress`; without one the step just spins.
 */

export type StepState = "todo" | "active" | "done" | "failed";
export type StepId = "download" | "verify" | "install" | "restart" | "version" | "reload";
export type FlowStep = { id: StepId; label: string; state: StepState; detail?: string };
export type BusyStatus = "downloading" | "verifying" | "installing";

export type FlowInput = {
  kind: UpdateKind;
  status: UpdateStatus;
  progress: number | null;
  /** the last busy status this tab saw since Install was pressed (or since the engine started one) */
  lastBusy: BusyStatus | null;
  /** POST /api/updates/install's `result` (restart · opened · started · permission · signature), once it replied */
  result: string | null;
  /** the version being installed, and the version the engine runs now (it changes after the restart) */
  target: string | null;
  current: string;
  /** the studio's link to the engine is up (it drops while DeskDot restarts) */
  linkOpen: boolean;
  /** the browser app: Reload was pressed */
  reloading?: boolean;
};

export const isBusy = (s: UpdateStatus | undefined): s is BusyStatus =>
  s === "downloading" || s === "verifying" || s === "installing";

const ORDER: BusyStatus[] = ["downloading", "verifying", "installing"];

/** The steps to show, or null when no install is under way or just finished (nothing to show). */
export function flowSteps(i: FlowInput): FlowStep[] | null {
  if (i.kind === "web") {
    if (!i.reloading) return null;
    return [
      { id: "version", label: "New build found in version.json", state: "done" },
      { id: "reload", label: "Reload this tab", state: "active" },
    ];
  }
  if (i.kind === "source") return null;

  const busy = isBusy(i.status) ? i.status : null;
  const at = busy ?? i.lastBusy;
  if (!at && !i.result) return null;

  const installLabel =
    i.kind === "android" ? "Open Android's installer" : i.result === "opened" ? "Open the installer" : "Install";
  const steps: FlowStep[] = [
    { id: "download", label: "Download the new version", state: "todo" },
    { id: "verify", label: "Check it against checksums.txt", state: "todo" },
    { id: "install", label: installLabel, state: "todo" },
  ];
  const desktop = i.kind === "windows" || i.kind === "macos";
  if (desktop && i.result !== "opened") steps.push({ id: "restart", label: "Restart DeskDot", state: "todo" });

  const pos = at ? ORDER.indexOf(at) : steps.length; // the step the engine is on (or failed in)
  const mark = (upto: number, last: StepState) =>
    steps.forEach((s, n) => {
      s.state = n < upto ? "done" : n === upto ? last : "todo";
    });

  if (i.result === "restart" && i.status !== "error") {
    // the installer has it: the engine stays "installing" until it exits, so the restart is the live step
    const back = i.linkOpen && !!i.target && i.current === i.target;
    mark(back ? steps.length : 3, back ? "done" : "active");
  } else if (busy) {
    mark(pos, "active");
    if (busy === "downloading" && i.progress != null && i.progress > 0 && i.progress < 1)
      steps[0].detail = `${Math.round(i.progress * 100)}%`;
  } else if (i.status === "error") {
    mark(i.result === "signature" ? 2 : pos, "failed");
  } else if (i.result === "permission") {
    mark(2, "failed"); // Android needs "install unknown apps" first; the sheet says how
  } else if (i.result) {
    mark(steps.length, "done"); // started / opened: the system's installer has it now
  } else {
    return null; // idle, nothing pressed in this tab
  }
  return steps;
}

/** What the one primary button does right now. */
export type Primary = "install" | "reload" | "retry-install" | "retry-check" | null;

export function primaryAction(o: {
  kind: UpdateKind;
  available: boolean;
  canInstall: boolean;
  status: UpdateStatus;
  lastBusy: BusyStatus | null;
  result: string | null;
}): Primary {
  if (isBusy(o.status) || o.status === "checking" || o.result === "restart") return null;
  // an install that failed (here, in another tab or before a reload) is retried by installing again; a failed check
  // with nothing installable is retried by checking again
  if (o.status === "error") return o.lastBusy || o.result || (o.available && o.canInstall) ? "retry-install" : "retry-check";
  if (!o.available) return null;
  if (o.kind === "web") return "reload";
  return o.canInstall ? "install" : null;
}

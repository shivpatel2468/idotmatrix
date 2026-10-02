// The launcher's tiny HTTP client: same origin as the engine (served at /launcher), no studio store.
import type { EngineState, Meta, Preset } from "../lib/types";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "content-type": "application/json" };
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg ?? detail);
    } catch {
      /* not json */
    }
    throw new Error(detail);
  }
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  meta: () => req<Meta>("GET", "/api/meta"),
  state: () => req<EngineState>("GET", "/api/state"),
  presets: () => req<Preset[]>("GET", "/api/presets"),
  activate: (app: string, settings?: Record<string, unknown>) =>
    req("POST", `/api/apps/${encodeURIComponent(app)}/activate`, { settings: settings ?? null }),
  patchSettings: (app: string, patch: Record<string, unknown>) =>
    req("PATCH", `/api/apps/${encodeURIComponent(app)}/settings`, patch),
  action: (app: string, action: string, payload: Record<string, unknown> = {}) =>
    req("POST", `/api/apps/${encodeURIComponent(app)}/actions/${encodeURIComponent(action)}`, payload),
  playPreset: (id: string, shuffle = false) => req("POST", `/api/presets/${encodeURIComponent(id)}/play`, { shuffle }),
  playlist: (op: "play" | "stop" | "next" | "prev") => req("POST", `/api/playlist/${op}`),
  settings: (patch: Record<string, unknown>) => req("PATCH", "/api/settings", patch),
  notify: (message: string, title = "") =>
    req("POST", "/api/notify", { title, message, color: "#ff7419", icon: "bell", duration: 8, style: "banner" }),
  dismiss: () => req("DELETE", "/api/notify"),
  text: (text: string) => req("POST", "/api/text", { text, color: "#ffcc33", revert_after: 30 }),
  reconnect: () => req("POST", "/api/device/reconnect"),
};

/** `window.pywebview.api` when running inside `deskdot launcher` (src/deskdot/launcher.py LauncherApi). */
export type ShellApi = {
  hide: () => Promise<boolean>;
  open_url: (url: string) => Promise<boolean>;
  quit: () => Promise<boolean>;
  info: () => Promise<{ hotkey: string; url: string; autostart: boolean; platform: string }>;
  set_autostart: (on: boolean) => Promise<boolean>;
};

export function shellApi(): ShellApi | null {
  return (window as unknown as { pywebview?: { api?: ShellApi } }).pywebview?.api ?? null;
}

export const inShell = () => document.documentElement.dataset.shell !== "browser";

/** Open a studio path (`/#app/clock`, `/#settings/display`) in the default browser. */
export function openStudio(path = "/") {
  const sh = shellApi();
  if (sh) void sh.open_url(path);
  else window.open(path, "_blank", "noopener");
}

export function hideShell() {
  void shellApi()?.hide();
}

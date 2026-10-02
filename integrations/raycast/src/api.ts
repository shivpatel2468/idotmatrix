// DeskDot engine HTTP client (docs/API.md). Only the engine talks to the panel; we talk to the engine.
import { getPreferenceValues, open } from "@raycast/api";

export type AppMeta = {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  schema: { properties?: Record<string, { title?: string }> };
  actions: { id: string; label: string; icon: string }[];
  max_players?: number;
  supported?: boolean;
};
export type Meta = { version: string; apps: AppMeta[] };
export type Preset = {
  id: string;
  name: string;
  icon: string;
  builtin: boolean;
  items: { app: string; duration: number }[];
};
export type EngineState = {
  device: { status: string; name: string | null; kind: string };
  engine: {
    mode: "manual" | "playlist";
    current: { app: string } | null;
    playlist: { enabled: boolean; items: unknown[] };
    active_preset?: string | null;
  };
  settings: { brightness: number; power: boolean };
  apps: Record<string, Record<string, unknown>>;
};

export const CATEGORY_LABEL: Record<string, string> = {
  time: "Time",
  data: "Live data",
  media: "Media",
  creative: "Create",
  ambient: "Ambient",
  productivity: "Focus & agents",
  pets: "Pets & characters",
  games: "Games",
  device: "Panel",
};
export const CATEGORY_ORDER = [
  "time",
  "data",
  "media",
  "pets",
  "games",
  "creative",
  "productivity",
  "ambient",
  "device",
];

export function baseUrl(): string {
  const { engineUrl } = getPreferenceValues<{ engineUrl?: string }>();
  return (engineUrl || "http://127.0.0.1:8765").replace(/\/+$/, "");
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(baseUrl() + path, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
      headers: body === undefined ? undefined : { "content-type": "application/json" },
    });
  } catch {
    throw new Error(`DeskDot isn't running at ${baseUrl()} (start it with: uv run deskdot serve)`);
  }
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = (await r.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* not json */
    }
    throw new Error(detail);
  }
  return (r.headers.get("content-type") ?? "").includes("json") ? ((await r.json()) as T) : (undefined as T);
}

export const api = {
  meta: () => req<Meta>("GET", "/api/meta"),
  state: () => req<EngineState>("GET", "/api/state"),
  presets: () => req<Preset[]>("GET", "/api/presets"),
  activate: (app: string) => req("POST", `/api/apps/${encodeURIComponent(app)}/activate`, {}),
  patchSettings: (app: string, patch: Record<string, unknown>) =>
    req("PATCH", `/api/apps/${encodeURIComponent(app)}/settings`, patch),
  action: (app: string, action: string) =>
    req("POST", `/api/apps/${encodeURIComponent(app)}/actions/${encodeURIComponent(action)}`, {}),
  playPreset: (id: string, shuffle = false) => req("POST", `/api/presets/${encodeURIComponent(id)}/play`, { shuffle }),
  playlist: (op: "play" | "stop" | "next" | "prev") => req("POST", `/api/playlist/${op}`),
  settings: (patch: Record<string, unknown>) => req("PATCH", "/api/settings", patch),
  notify: (n: { title: string; message: string; color: string; icon: string; duration: number; style: string }) =>
    req("POST", "/api/notify", n),
  text: (text: string, color: string, seconds: number) =>
    req("POST", "/api/text", { text, color, revert_after: seconds }),
};

export const previewUrl = (app: string) => `${baseUrl()}/api/apps/${encodeURIComponent(app)}/preview.gif`;
export const frameUrl = () => `${baseUrl()}/api/frame.png?scale=8&t=${Date.now()}`;

/** Studio deep links: `#app/<id>` selects an app, `#settings/<section>` opens settings (web/src/lib/deeplink.ts). */
export const openStudio = (hash = "") => open(`${baseUrl()}/${hash}`);

export const canFlyPilot = (a: AppMeta | undefined) => !!a?.schema?.properties?.pilot;

/** The fruit-fly brain plays `app` (a game), or the game on the panel, or its own Fly Brain app. */
export async function flyPlay(meta: Meta | undefined, current: string | undefined, app?: string): Promise<string> {
  const target = app ?? current;
  const m = meta?.apps.find((a) => a.id === target);
  if (target && canFlyPilot(m)) {
    await api.patchSettings(target, { pilot: "fly" });
    if (app) await api.activate(target);
    await api.action(target, "fly").catch(() => undefined);
    return `The fly is playing ${m?.name ?? target}`;
  }
  await api.activate("flybrain");
  return "The fly is on the panel";
}

import type { LobbyInfo, LobbyResponse, Preset, AutopilotRule, MediaItem, Meta, Notice, PlaylistItem, Handoff, Indicator, Integrations } from "./types";
import { toast, useStore } from "./store";
import type { Autotune, CalTest, Calib, MotionInfo, MotionTest, PresetListing, VideoInfo } from "./calib";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "content-type": "application/json" };
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg ?? JSON.stringify(j.detail));
    } catch {
      /* not json */
    }
    toast(detail || `Request failed (${r.status})`, "error");
    throw new Error(detail);
  }
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  meta: () => req<Meta>("GET", "/api/meta"),
  activate: (app: string, settings?: Record<string, unknown>) => {
    // the stage shows a loading overlay (with a tip) until this app's first frame arrives
    useStore.setState({ opening: { app, since: performance.now() } });
    return req("POST", `/api/apps/${app}/activate`, { settings: settings ?? null });
  },
  patchSettings: (app: string, patch: Record<string, unknown>) =>
    req<Record<string, unknown>>("PATCH", `/api/apps/${app}/settings`, patch),
  action: (app: string, action: string, payload: Record<string, unknown> = {}) =>
    req("POST", `/api/apps/${app}/actions/${action}`, payload),
  pixels: (body: { rows?: string[]; palette?: Record<string, string>; rgb?: string; pixels?: [number, number, string][]; clear?: boolean }) =>
    req("POST", "/api/pixels", body),
  playlist: (op: "play" | "stop" | "next" | "prev") => req("POST", `/api/playlist/${op}`),
  putPlaylist: (enabled: boolean, items: Omit<PlaylistItem, "id">[] | PlaylistItem[]) =>
    req("PUT", "/api/playlist", { enabled, items }),
  notify: (n: Partial<Notice>) => req("POST", "/api/notify", n),
  dismiss: () => req("DELETE", "/api/notify"),
  settings: (patch: Record<string, unknown>) => req("PATCH", "/api/settings", patch),
  reconnect: () => req("POST", "/api/device/reconnect"),
  scan: () => req<{ address: string; name: string; rssi: number }[]>("GET", "/api/device/scan"),
  media: () => req<MediaItem[]>("GET", "/api/media"),
  upload: (file: File, show = true) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<MediaItem>("POST", `/api/media?show=${show}`, fd);
  },
  deleteMedia: (id: string) => req("DELETE", `/api/media/${id}`),
  nowplaying: (op: "toggle" | "next" | "prev") => req("POST", `/api/nowplaying/${op}`),
  autopilot: (enabled: boolean, rules: AutopilotRule[]) => req("PUT", "/api/autopilot", { enabled, rules }),
  display: (patch: Record<string, unknown>) => req<Record<string, unknown>>("PATCH", "/api/display", patch),
  calibration: (c: Partial<Calib> | Record<string, number>) => req<Calib>("PUT", "/api/calibration", c),
  // calibration wizard, picture presets and the motion lab (docs/CALIBRATION.md)
  calibPresets: () => req<PresetListing>("GET", "/api/calibration/presets"),
  calibPreset: (id: string, keep_balance = true, apply = true) =>
    req<Calib>("POST", `/api/calibration/preset/${encodeURIComponent(id)}`, { keep_balance, apply }),
  calibQuick: (body: { room: string; use: string; tint: string; apply?: boolean }) => req<Calib>("POST", "/api/calibration/quick", body),
  calibVideos: () => req<{ videos: VideoInfo[]; motion: VideoInfo[]; fps: number }>("GET", "/api/calibration/videos"),
  calibTest: (t: CalTest) => req<{ ok: boolean; pattern: string; fps: number }>("POST", "/api/calibration/test", t),
  motion: () => req<MotionInfo>("GET", "/api/motion"),
  motionTest: (t: MotionTest) => req<{ ok: boolean; pattern: string; fps?: number; mode: string }>("POST", "/api/motion/test", t),
  motionPreset: (id: string) => req<Record<string, unknown>>("POST", `/api/motion/preset/${encodeURIComponent(id)}`),
  motionAutotune: (apply = false, seconds = 4) => req<Autotune>("POST", "/api/motion/autotune", { apply, seconds }),
  pattern: (name: string) => req("POST", `/api/calibration/pattern/${name}`),
  clearPattern: () => req("DELETE", "/api/calibration/pattern"),
  applyTransferCalib: (data: { max_fps: number; packet_gap_ms: number; transition: "cut" | "push" | "fade" | "wipe" }) =>
    req("POST", "/api/calibration/transfer/apply", data),
  link: (enabled: boolean) => req("POST", "/api/device/link", { enabled }),
  handoff: () => req<Handoff>("GET", "/api/handoff"),
  setHandoff: (patch: Partial<Handoff>) => req<Handoff>("PUT", "/api/handoff", patch),
  handoffNow: (mode?: Handoff["mode"]) => req<{ result: string; released: boolean }>("POST", "/api/handoff/now", { mode: mode ?? null }),
  takeBack: () => req("POST", "/api/handoff/take-back"),
  // presets: one-tap playlists
  presets: () => req<Preset[]>("GET", "/api/presets"),
  playPreset: (id: string, shuffle = false) => req<{ ok: boolean; items: number }>("POST", `/api/presets/${encodeURIComponent(id)}/play`, { shuffle }),
  savePreset: (name: string) => req<Preset>("POST", "/api/presets", { name }),
  deletePreset: (id: string) => req("DELETE", `/api/presets/${encodeURIComponent(id)}`),
  // platform: integrations, indicators, custom push apps
  integration: <K extends keyof Integrations>(section: K, patch: Partial<Integrations[K]>) =>
    req<Integrations[K]>("PATCH", `/api/integrations/${section}`, patch),
  hassTest: () => req<{ ok: boolean; message: string }>("POST", "/api/integrations/homeassistant/test"),
  onairSimulate: (seconds: number) => req("POST", "/api/onair/simulate", { seconds }),
  eyebreakNow: () => req("POST", "/api/eyebreak/now"),
  setIndicator: (slot: number, ind: Partial<Indicator>) => req("POST", `/api/indicators/${slot}`, ind),
  clearIndicator: (slot: number) => req("DELETE", `/api/indicators/${slot}`),
  removeCustom: (name: string) => req("DELETE", `/api/custom/${encodeURIComponent(name)}`),
  // local-Wi-Fi multiplayer lobby
  lobby: () => req<LobbyResponse>("GET", "/api/play/lobby"),
  openLobby: (app: string) => req<LobbyInfo & { ok: boolean }>("POST", "/api/play/lobby", { app }),
  startLobby: () => req("POST", "/api/play/lobby/start"),
  closeLobby: () => req("DELETE", "/api/play/lobby"),
  // Gemini AI Studio
  aiConfig: () => req<{ configured: boolean; source: string; masked_key: string; model: string }>("GET", "/api/ai/config"),
  aiSaveConfig: (data: { api_key?: string; model?: string }) =>
    req<{ configured: boolean; source: string; masked_key: string; model: string }>("POST", "/api/ai/config", data),
  aiCreate: (data: {
    prompt: string;
    api_key?: string;
    model?: string;
    fps?: number;
    num_frames?: number;
    action?: "preview" | "canvas" | "clip" | "stream";
    revert_after?: number;
  }) =>
    req<{
      ok: boolean;
      title: string;
      media_id: string;
      fps: number;
      frame_count: number;
      frames: { rows: string[]; duration_ms: number }[];
      palette: Record<string, string>;
      gif_url: string;
      action: string;
    }>("POST", "/api/ai/create", data),
};


/** Refresh the preset list in the store (after load, save or delete). */
export async function loadPresets() {
  try {
    useStore.setState({ presets: await api.presets() });
  } catch {
    if (!useStore.getState().presets) useStore.setState({ presets: [] });
  }
}

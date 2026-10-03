// What the command bar can find, and how it ranks it. Pure functions: easy to reason about, no React.
import type { AppMeta, EngineState, Meta, Preset } from "../lib/types";

export type Kind = "now" | "action" | "app" | "game" | "fly" | "preset" | "setting" | "say";

export type Item = {
  id: string; // stable: used for "recent"
  kind: Kind;
  title: string;
  subtitle: string;
  /** extra text the fuzzy search looks at (description, category, setting titles…) */
  keywords: string;
  /** the app it's about (preview gif, category icon) */
  app?: string;
  category?: string;
  /** studio deep link for Ctrl/⌘+Enter */
  studio?: string;
  /** the verb shown on the Enter hint */
  verb: string;
  /** shown only when the query is not empty (long tails: settings, per-game fly items) */
  searchOnly?: boolean;
  /** typed-text actions listed after the real matches */
  fallback?: boolean;
  /** the action itself; returns the toast text */
  run: () => Promise<string>;
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
  casino: "Casino",
  device: "Panel",
};
export const CATEGORY_ORDER = ["time", "data", "media", "pets", "games", "casino", "creative", "productivity", "ambient", "device"];

/** Studio settings sections and blocks (web/src/lib/store.ts SettingsTab) with words people search for. */
export const SETTINGS: { tab: string; title: string; words: string }[] = [
  { tab: "display", title: "Display", words: "brightness transition flip night mode hz fps" },
  { tab: "panel", title: "Panel", words: "power flip orientation" },
  { tab: "calibrate", title: "Colour calibration", words: "color gamma white balance wizard" },
  { tab: "transfer", title: "Transfer speed", words: "bluetooth packet gap fps hz smooth" },
  { tab: "alerts", title: "Alerts", words: "notifications on air eye break indicators" },
  { tab: "notifications", title: "OS notifications", words: "toast windows mac alerts banner" },
  { tab: "integrations", title: "Integrations", words: "on air ntfy home assistant eye break webcam microphone" },
  { tab: "playlist", title: "Playlist", words: "rotation queue presets durations" },
  { tab: "autopilot", title: "Autopilot", words: "foreground app rules automatic" },
  { tab: "device", title: "Device & Bluetooth", words: "connect reconnect scan mac address ble link" },
  { tab: "handoff", title: "Hand-off", words: "sleep shutdown clock release panel on its own" },
  { tab: "audio", title: "Audio source", words: "music visualiser microphone system sound" },
  { tab: "weather", title: "Weather & location", words: "city units metric imperial" },
];

export const canFlyPilot = (a: AppMeta | undefined) => !!a?.schema?.properties?.pilot;

export type Ctx = {
  meta: Meta | null;
  state: EngineState | null;
  presets: Preset[];
  api: typeof import("./client").api;
  inShell: boolean;
};

function appKeywords(a: AppMeta): string {
  const props = a.schema?.properties ?? {};
  const settings = Object.values(props)
    .map((p) => `${p.title ?? ""} ${p.enum ? Object.values(p.enumLabels ?? {}).join(" ") : ""}`)
    .join(" ");
  return `${a.id} ${a.description} ${CATEGORY_LABEL[a.category] ?? a.category} ${a.category} ${settings} ${a.actions
    .map((x) => x.label)
    .join(" ")}`;
}

/** Make the fly play: the given game (or the one on the panel), else its own Fly Brain app. */
export async function flyPlay(ctx: Ctx, app?: string): Promise<string> {
  const apps = ctx.meta?.apps ?? [];
  const target = app ?? ctx.state?.engine.current?.app;
  const meta = apps.find((a) => a.id === target);
  if (target && canFlyPilot(meta)) {
    await ctx.api.patchSettings(target, { pilot: "fly" });
    if (app) await ctx.api.activate(target);
    await ctx.api.action(target, "fly").catch(() => undefined); // older engines take over after the idle wait
    return `The fly is playing ${meta?.name ?? target}`;
  }
  await ctx.api.activate("flybrain");
  return "The fly is on the panel";
}

export function buildItems(ctx: Ctx): Item[] {
  const { meta, state, presets, api } = ctx;
  const apps = (meta?.apps ?? []).filter((a) => a.supported !== false);
  const name = (id: string | undefined) => apps.find((a) => a.id === id)?.name ?? id ?? "nothing";
  const cur = state?.engine.current?.app;
  const settings = state?.settings as { brightness?: number; power?: boolean } | undefined;
  const power = settings?.power !== false;
  const playlistOn = state?.engine.mode === "playlist" && state.engine.playlist.enabled;
  const curPilot = cur ? (state?.apps as Record<string, Record<string, unknown>> | undefined)?.[cur]?.pilot : undefined;
  const items: Item[] = [];

  items.push({
    id: "now",
    kind: "now",
    title: `Now showing: ${name(cur)}`,
    subtitle: playlistOn ? "Playlist is playing" : "Live view of the panel",
    keywords: "now playing current panel live frame what is on",
    app: cur,
    studio: cur ? `/#app/${cur}` : "/",
    verb: "Open studio",
    run: async () => "",
  });
  items.push({
    id: "brightness",
    kind: "action",
    title: "Brightness",
    subtitle: `${settings?.brightness ?? 60}%  ·  ← → to adjust, or type “b 40”`,
    keywords: "brightness dim light level",
    studio: "/#settings/display",
    verb: "Adjust",
    run: async () => "",
  });
  items.push({
    id: "next",
    kind: "action",
    title: "Next",
    subtitle: "Skip to the next playlist item",
    keywords: "next skip forward playlist",
    verb: "Next",
    run: async () => (await api.playlist("next"), "Next"),
  });
  items.push({
    id: "prev",
    kind: "action",
    title: "Previous",
    subtitle: "Back to the previous playlist item",
    keywords: "previous back prev playlist",
    verb: "Previous",
    run: async () => (await api.playlist("prev"), "Previous"),
  });
  items.push({
    id: "power",
    kind: "action",
    title: power ? "Turn the panel off" : "Turn the panel on",
    subtitle: power ? "Display power off (the Bluetooth link stays up)" : "Display power on",
    keywords: "power on off screen sleep wake display",
    verb: power ? "Turn off" : "Turn on",
    run: async () => (await api.settings({ power: !power }), power ? "Panel off" : "Panel on"),
  });
  items.push({
    id: "playlist",
    kind: "action",
    title: playlistOn ? "Stop the playlist" : "Play the playlist",
    subtitle: playlistOn ? "Stay on the current app" : "Rotate through your playlist",
    keywords: "playlist play stop pause rotation resume",
    studio: "/#settings/playlist",
    verb: playlistOn ? "Stop" : "Play",
    run: async () => (await api.playlist(playlistOn ? "stop" : "play"), playlistOn ? "Playlist stopped" : "Playlist playing"),
  });
  items.push({
    id: "fly",
    kind: "fly",
    title: "Let the fly play",
    subtitle: cur && canFlyPilot(apps.find((a) => a.id === cur))
      ? `A fruit-fly brain takes over ${name(cur)}`
      : "A fruit-fly brain on the panel (Fly Brain)",
    keywords: "fly fruit fly brain ai play itself drosophila pilot",
    app: "flybrain",
    studio: "/",
    verb: "Let it play",
    run: () => flyPlay(ctx),
  });
  if (cur && curPilot === "fly") {
    items.push({
      id: "fly-handback",
      kind: "fly",
      title: `Give ${name(cur)} back to the AI`,
      subtitle: "The fly leaves the game",
      keywords: "fly hand back stop ai pilot",
      verb: "Hand back",
      run: async () => (await api.patchSettings(cur, { pilot: "ai" }), "The built-in AI plays again"),
    });
  }
  if (state?.engine.overlay) {
    items.push({
      id: "dismiss",
      kind: "action",
      title: "Dismiss notification",
      subtitle: state.engine.overlay.title || state.engine.overlay.message,
      keywords: "dismiss clear notification close banner",
      verb: "Dismiss",
      run: async () => (await api.dismiss(), "Dismissed"),
    });
  }
  items.push({
    id: "studio",
    kind: "action",
    title: "Open DeskDot Studio",
    subtitle: "The full editor in your browser",
    keywords: "studio open browser editor web",
    studio: "/",
    verb: "Open",
    run: async () => "",
  });
  items.push({
    id: "reconnect",
    kind: "action",
    title: "Reconnect the panel",
    subtitle: state ? `Bluetooth: ${state.device.status}` : "Bluetooth",
    keywords: "reconnect bluetooth ble connect link device",
    searchOnly: true,
    verb: "Reconnect",
    run: async () => (await api.reconnect(), "Reconnecting…"),
  });

  for (const p of presets) {
    items.push({
      id: `preset:${p.id}`,
      kind: "preset",
      title: p.name,
      subtitle: `Preset · ${p.items.length} apps${p.builtin ? "" : " · yours"}`,
      keywords: `preset playlist mix ${p.items.map((i) => name(i.app)).join(" ")}`,
      studio: "/#settings/playlist",
      verb: "Play preset",
      run: async () => (await api.playPreset(p.id), `Playing “${p.name}”`),
    });
  }

  for (const a of apps) {
    const game = a.category === "games";
    items.push({
      id: `app:${a.id}`,
      kind: game ? "game" : "app",
      title: a.name,
      subtitle: a.description,
      keywords: appKeywords(a),
      app: a.id,
      category: a.category,
      studio: `/#app/${a.id}`,
      verb: game ? "Play on panel" : "Show on panel",
      run: async () => (await api.activate(a.id), `${a.name} is on the panel`),
    });
    if (canFlyPilot(a)) {
      items.push({
        id: `fly:${a.id}`,
        kind: "fly",
        title: `Play ${a.name} with the fly`,
        subtitle: "The fruit-fly brain plays it, seeing only the pixels",
        keywords: `fly brain ${a.name} game pilot`,
        app: a.id,
        category: a.category,
        studio: `/#app/${a.id}`,
        verb: "Let the fly play",
        searchOnly: true,
        run: () => flyPlay(ctx, a.id),
      });
    }
  }

  for (const s of SETTINGS) {
    items.push({
      id: `setting:${s.tab}`,
      kind: "setting",
      title: `${s.title} settings`,
      subtitle: "Opens in the studio",
      keywords: `settings preferences ${s.words}`,
      studio: `/#settings/${s.tab}`,
      verb: "Open settings",
      searchOnly: true,
      run: async () => "",
    });
  }
  return items;
}

/** Items that depend on what was typed: "b 40", "> hello", and the fallback "send this to the panel". */
export function queryItems(query: string, ctx: Ctx): Item[] {
  const q = query.trim();
  if (!q) return [];
  const out: Item[] = [];
  const b = /^(?:b|br|bri|bright|brightness)\s*(\d{1,3})\s*%?$/i.exec(q);
  if (b) {
    const v = Math.max(5, Math.min(100, Number(b[1])));
    out.push({
      id: "brightness-set",
      kind: "action",
      title: `Set brightness to ${v}%`,
      subtitle: "Panel brightness",
      keywords: q,
      verb: "Set",
      run: async () => (await ctx.api.settings({ brightness: v }), `Brightness ${v}%`),
    });
  }
  const say = /^(?:>|say\s|notify\s|send\s)\s*(.+)$/i.exec(q);
  const text = say ? say[1].trim() : q;
  if (text) {
    out.push({
      id: "say-notify",
      kind: "say",
      title: `Send “${text}” to the panel`,
      subtitle: "Notification banner",
      keywords: q,
      verb: "Send",
      run: async () => (await ctx.api.notify(text), "Sent"),
    });
    out.push({
      id: "say-text",
      kind: "say",
      title: `Show “${text}” for 30 s`,
      subtitle: "Scrolling text, then back to what was on",
      keywords: q,
      verb: "Show",
      run: async () => (await ctx.api.text(text), "On the panel for 30 s"),
    });
  }
  // typed text without "> " goes after the real matches; "b 40" and "> hello" lead
  return out.map((i) => (i.kind === "say" && !say ? { ...i, fallback: true } : i));
}

// ------------------------------------------------------------------ fuzzy ranking
const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");

/** Score one query token against a title; 0 = no match. */
function titleScore(token: string, title: string): number {
  if (title === token) return 120;
  if (title.startsWith(token)) return 90;
  const words = title.split(/[\s\-_/·:()“”"]+/);
  if (words.some((w) => w.startsWith(token))) return 70;
  if (title.includes(token)) return 50;
  // subsequence (initials, typos of omission): "nwp" → "now playing"
  let i = 0;
  let gaps = 0;
  let last = -1;
  for (let k = 0; k < title.length && i < token.length; k++) {
    if (title[k] === token[i]) {
      if (last >= 0 && k - last > 1) gaps++;
      last = k;
      i++;
    }
  }
  return i === token.length && token.length >= 2 ? Math.max(8, 30 - gaps * 4) : 0;
}

export function scoreItem(query: string, item: Item): number {
  const q = norm(query.trim());
  if (!q) return 1;
  const title = norm(item.title);
  const kw = norm(`${item.subtitle} ${item.keywords}`);
  const whole = titleScore(q, title);
  let total = whole ? whole + 40 : 0;
  if (!whole) {
    for (const t of q.split(/\s+/)) {
      const s = titleScore(t, title);
      if (s) total += s;
      else if (kw.includes(t)) total += t.length >= 3 ? 18 : 6;
      else return 0;
    }
  }
  if (item.kind === "fly" && item.searchOnly && !/fly/.test(q)) total -= 25; // per-game fly items: only when asked
  if (item.kind === "setting") total -= 4;
  return Math.max(total, 1);
}

/** Title indices to highlight for the query (substring first, then subsequence). */
export function highlight(query: string, title: string): Set<number> {
  const q = norm(query.trim());
  const t = norm(title);
  const out = new Set<number>();
  if (!q) return out;
  const at = t.indexOf(q);
  if (at >= 0) {
    for (let k = 0; k < q.length; k++) out.add(at + k);
    return out;
  }
  for (const tok of q.split(/\s+/)) {
    const i = t.indexOf(tok);
    if (i >= 0) for (let k = 0; k < tok.length; k++) out.add(i + k);
  }
  return out;
}

export function rank(items: Item[], extra: Item[], query: string, recent: string[]): Item[] {
  const q = query.trim();
  if (!q) {
    const byId = new Map(items.map((i) => [i.id, i]));
    const rec = recent.map((id) => byId.get(id)).filter((i): i is Item => !!i);
    const recSet = new Set(rec.map((i) => i.id));
    return [...rec, ...items.filter((i) => !i.searchOnly && !recSet.has(i.id))];
  }
  const scored = items
    .map((it) => {
      let s = scoreItem(q, it);
      const r = recent.indexOf(it.id);
      if (s > 0 && r >= 0) s += 24 - r * 2;
      return { it, s };
    })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .map((x) => x.it);
  const exact = extra.filter((e) => !e.fallback);
  const fallback = extra.filter((e) => e.fallback);
  return [...exact, ...scored, ...fallback];
}

export function groupLabel(item: Item): string {
  switch (item.kind) {
    case "now":
    case "action":
    case "fly":
      return "Controls";
    case "preset":
      return "Presets";
    case "setting":
      return "Settings";
    case "say":
      return "Send to panel";
    default:
      return CATEGORY_LABEL[item.category ?? ""] ?? "Apps";
  }
}

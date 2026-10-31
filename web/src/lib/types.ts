// Mirrors the engine's JSON (src/deskdot/server.py + engine/runtime.py snapshot()).

export type JsonSchemaProp = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  enumLabels?: Record<string, string>;
  format?: string;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  pattern?: string;
  group?: string;
  /** Hosts this setting works on (engine `platforms.only_on`); absent = everywhere. */
  platforms?: Platform[];
  /** Enum options that only work on some hosts: option -> platforms. */
  enumPlatforms?: Record<string, Platform[]>;
};

/** The engine's host OS (GET /api/meta `platform`). A Raspberry Pi is "linux". */
export type Platform = "windows" | "macos" | "linux" | "android" | "web";

export type AppSchema = {
  properties?: Record<string, JsonSchemaProp>;
  title?: string;
  /** The whole app only works on these hosts (App.platforms); absent = everywhere. */
  platforms?: Platform[];
  /** Why the app can't run in a browser tab (App.web_reason); shown by the web app only. */
  webReason?: string;
};

export type AppMeta = {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: "time" | "data" | "media" | "creative" | "ambient" | "productivity" | "pets" | "games" | "casino" | "device";
  schema: AppSchema;
  actions: { id: string; label: string; icon: string }[];
  /** Games: seats (1 = single player) and recommended controllers, best first. Older engines omit both. */
  max_players?: number;
  controls?: ("dpad" | "joystick" | "swipe" | "tap" | "gamepad")[];
  /** Games: ways to play with their player ranges (first = default). Older engines omit it. */
  modes?: GameMode[];
  /** Hosts the app works on (null = everywhere) and whether this engine's host is one. Older engines omit both. */
  platforms?: Platform[] | null;
  supported?: boolean;
};

/** A game mode from `/api/meta`. `teams`: versus modes show the side-select screen before the match. */
export type GameMode = { id: string; name: string; min_players: number; max_players: number; teams: "solo" | "coop" | "ffa" | "versus" };
/** Where a game is in its flow (`engine.current.status.flow`). */
export type GameFlow = "attract" | "home" | "teams" | "intro" | "play" | "outro";
/** `status.roster`: seat -> side (0 = team A, 1 = team B, null = middle / not picked), person or AI, ready. */
export type RosterEntry = { team: 0 | 1 | null; human: boolean; ready: boolean };
export type GameOutcome = { seat?: number | null; team?: 0 | 1 | null; text?: string | null };

export type Meta = {
  version: string;
  apps: AppMeta[];
  palette: Record<string, string>;
  icons: string[];
  leagues: Record<string, string>;
  plugins: string[];
  /** The engine's host OS, a display label ("Linux (Raspberry Pi)") and host-feature support. Older engines omit them. */
  platform?: Platform;
  platform_label?: string;
  features?: Record<string, boolean>;
};

export type DeviceInfo = {
  kind: "ble" | "sim" | "android" | "web";
  status: "disconnected" | "scanning" | "connecting" | "connected" | "error";
  address: string | null;
  name: string | null;
  mtu: number | null;
  mode: "unknown" | "diy" | "gif" | "native";
  last_error: string | null;
  connected_since: number | null;
  frames_sent: number;
  frames_dropped: number;
  bytes_sent: number;
  last_write_ms: number;
  link_fps: number;
  last_ack: string | null;
  power: boolean;
  link_enabled: boolean;
  // connection health (device/base.py, device/diagnose.py); older engines omit them
  attempts?: number;
  retry_at?: number | null;
  last_seen?: number | null;
  rssi?: number | null;
  reason?:
    | "bluetooth_off" | "not_found" | "busy" | "no_answer" | "permission" | "needs_user" | "link_lost" | "released"
    | "moved" | "elsewhere" | "recovering" | "error" | null;
  hint?: string | null;
  recoveries?: number;
};

/** Panel hand-over between DeskDots (src/deskdot/handover.py, ADR 0015); absent on older engines and in the browser */
export type HandoverPeer = {
  id: string;
  name: string;
  kind: string; // "ble" (a computer) | "android" | "web" (the browser tab on this computer)
  holding: boolean;
  panel: string | null;
  online: boolean;
  paired: boolean;
  ago: number | null;
};
export type HandoverStep = { id: "ask" | "released" | "waiting" | "connected"; label: string; state: "todo" | "active" | "done" | "failed" };
export type HandoverBrief = {
  enabled: boolean;
  me: { id: string; name: string; kind: string };
  holder: { id: string; name: string; kind: string; me: boolean; since?: number | null } | null;
  probable: { id: string; name: string; ago: number } | null;
  peers: HandoverPeer[];
  lease: { owner: string; name: string; in: number } | null;
  progress: { steps: HandoverStep[]; error: string | null; can_force: boolean; done: boolean; target: string | null } | null;
  moved_to: { id: string; name: string; at: number } | null;
  pair_requests: { id: string; name: string; kind: string; code: string }[];
  pairing: { id: string; name: string; code: string; status: "pending" | "allowed" | "denied" | "expired" }[];
};

export type PlaylistItem = {
  id: string;
  app: string;
  duration: number;
  settings: Record<string, unknown>;
  enabled: boolean;
};

export type Notice = {
  title: string;
  message: string;
  color: string;
  icon: string | null;
  duration: number;
  style: "banner" | "full" | "celebrate";
};

export type EngineState = {
  device: DeviceInfo;
  engine: {
    mode: "manual" | "playlist";
    active_preset?: string | null; // preset id while a preset plays
    current: {
      key: string;
      app: string;
      item: string | null;
      kind: "stream" | "clip" | "native";
      error: string | null;
      baking: boolean;
      status: Record<string, unknown>;
    } | null;
    focus: string | null;
    playlist: {
      enabled: boolean;
      items: PlaylistItem[];
      index: number;
      current_item: string | null;
      remaining: number | null;
    };
    overlay: Notice | null;
    pattern: string | null;
    /** the calibration / motion test card on the panel, if any */
    test?: { name: string; kind: "calibration" | "motion" | "still"; fps: number; native: boolean } | null;
    released?: boolean; // handed off: the panel is running on its own
    autopilot: { enabled: boolean; rules: AutopilotRule[]; active: number | null };
    queued_notices: number;
    render_ms: number;
    takeover?: "onair" | "eyebreak" | null;
    onair?: OnAirState;
    eyebreak?: { active: boolean; next_in_s: number | null; supported: boolean };
    indicators?: Record<string, IndicatorState>;
    custom?: CustomAppInfo[];
  };
  settings: {
    brightness: number;
    power: boolean;
    flip: boolean;
    transition: "cut" | "push" | "fade" | "wipe";
    units: "metric" | "imperial";
    location: { city?: string; lat?: number; lon?: number };
    audio_source: "system" | "mic";
    os_notifications: { enabled: boolean; style: string; duration: number; only: string; exclude: string };
    display: {
      max_fps: number;
      packet_gap_ms: number;
      idle_dim: number;
      smoothing?: number; // temporal smoothing of streamed frames (0 = off)
      motion_preset?: string | null;
      night: { enabled: boolean; start: string; end: string; brightness: number };
    };
    night_active: boolean;
    calibration: Record<string, number | boolean | string>; // lib/calib.ts `toCalib()` reads it
    integrations?: Integrations;
    page_theme?: string; // the page theme id (lib/pageTheme.ts); absent on engines older than 3.7
  };
  apps: Record<string, Record<string, unknown>>;
  providers: Record<string, { updated: number | null; error: string | null; active: boolean }>;
  /** in-app updates (src/deskdot/updates.py); absent on engines older than 3.8 */
  updates?: UpdatesBrief;
  /** panel hand-over between DeskDots (ADR 0015); absent on engines older than 3.9 and in the browser app */
  handover?: HandoverBrief;
};

export type UpdateKind = "windows" | "macos" | "android" | "source" | "web";
export type UpdateStatus = "idle" | "checking" | "downloading" | "verifying" | "installing" | "error";
export type UpdatesBrief = {
  current: string;
  latest: string | null;
  available: boolean;
  kind?: UpdateKind;
  latest_build?: string | null; // the browser app: the build its site serves now (version.json)
  status: UpdateStatus;
  progress: number | null; // 0..1 while downloading
  error: string | null;
};
/** GET /api/updates (docs/API.md § Updates) */
export type UpdatesInfo = UpdatesBrief & {
  notes: string; // the release's notes (WHATS_NEW-style markdown)
  name: string | null;
  published_at: string | null;
  url: string;
  assets: { name: string; size: number | null; url: string }[];
  checked_at: number | null; // unix seconds
  auto_check: boolean;
  kind: UpdateKind;
  can_install: boolean;
  source_hint: string | null;
  message: string | null;
  build?: string | null; // the browser app: the build this tab runs
};

export type Handoff = {
  on_exit: boolean;
  on_sleep: boolean;
  mode: "clock" | "app" | "last";
  app: string;
  seconds: number;
  clock_style: number;
  hour24: boolean;
  color: string;
  released?: boolean;
};

export type AutopilotRule = { match: string; app: string; settings: Record<string, unknown> };

export type MediaItem = {
  id: string;
  name: string;
  ext: string;
  width: number;
  height: number;
  frames: number;
  created: number;
  bytes: number;
};

// ------------------------------------------------------------- platform
export type OnAirState = {
  active: boolean;
  glyph: "mic" | "cam" | "both";
  apps: Record<string, string[]>;
  simulated: boolean;
};

export type Indicator = { color: string; blink: number; fade: number; lifetime_s: number; size: 2 | 3 };
export type IndicatorState = Indicator & { remaining_s: number | null };

export type CustomAppInfo = { name: string; text: string; icon: string | null; duration: number; expires_in: number | null };

export type OnAirConfig = {
  enabled: boolean; style: "full" | "badge" | "glow"; look: "sign" | "outline";
  webcam: boolean; microphone: boolean; exclude: string;
};
export type EyeBreakConfig = { enabled: boolean; interval_min: number; style: "breathe" | "ring" };
export type NtfyConfig = {
  enabled: boolean; server: string; topics: string; token: string; token_set: boolean;
  style: "auto" | "banner" | "full"; duration: number; route_prefix: string; lifetime: number;
};
export type HassConfig = { url: string; token: string; token_set: boolean };

export type Integrations = {
  onair: OnAirConfig;
  eyebreak: EyeBreakConfig;
  ntfy: NtfyConfig;
  homeassistant: HassConfig;
};

// ------------------------------------------------------------- presets
export type Preset = {
  id: string;
  name: string;
  icon: string;
  builtin: boolean;
  items: { app: string; duration: number }[];
};

// ------------------------------------------------------------- local-Wi-Fi multiplayer
export type LobbySeat = { seat: number; name: string; color: string | null };
export type LobbyInfo = {
  code: string; app: string; url: string | null; max_players: number; lan_ready: boolean; seats: LobbySeat[];
  warning?: string;
};
/** The TV view link (docs/TV_VIEW.md): `GET/POST /api/tv`. */
/** The studio's display choices for every TV of the link (POST /api/tv/settings); null = each TV keeps its own. */
export type TvLook = "pixel" | "led" | "glow";
export type TvQuality = "auto" | "hq" | "lite";
export type TvDisplay = { look: TvLook | null; quality: TvQuality | null; rev: number | null };
export type TvInfo = { code: string; url: string | null; lan_ready: boolean; viewers: number; display?: TvDisplay };
export type LobbyResponse = { lobby: LobbyInfo | null; lan_ready: boolean; games: { id: string; name: string; max_players: number }[] };
/** `engine.current.status` extras for games with max_players > 1. */
export type SeatStatus = { seat: number; human: boolean; name: string };

// Host-OS support for apps and settings (engine: src/deskdot/platforms.py, docs/COMPATIBILITY.md).
import type { Platform } from "./types";

const ALL: Platform[] = ["windows", "macos", "linux", "android", "web"];
export const PLATFORM_LABEL: Record<Platform, string> = { windows: "Windows", macos: "macOS", linux: "Linux", android: "Android", web: "Browser" };

/** True when `platforms` is absent (works everywhere), the host is unknown (older engine), or the host is listed. */
export function supportedOn(platforms: readonly string[] | null | undefined, host: string | undefined): boolean {
  return !platforms || !platforms.length || !host || platforms.includes(host);
}

/** ["windows", "macos"] -> "Windows/macOS only"; everything but one -> "Not on Android". */
export function platformsLabel(platforms: readonly string[]): string {
  const missing = ALL.filter((p) => !platforms.includes(p));
  if (missing.length === 1 && platforms.length === ALL.length - 1) return `Not on ${PLATFORM_LABEL[missing[0]]}`;
  return `${platforms.map((p) => PLATFORM_LABEL[p as Platform] ?? p).join("/")} only`;
}

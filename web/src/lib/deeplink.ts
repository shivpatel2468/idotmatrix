/**
 * Deep links into the studio, used by the launchers (docs/LAUNCHERS.md):
 *   /#settings/<section-or-block>   open the settings sheet there (e.g. #settings/display, #settings/calibrate)
 *   /#app/<id>                      select an app and show its settings in the inspector
 * The hash is cleared after it's handled, so reloads don't reopen the sheet.
 */
import { inspect, openSettings, type SettingsTab } from "./store";

const TABS: readonly SettingsTab[] = [
  "display", "alerts", "playlist", "device", "transfer", "calibrate", "notifications", "autopilot",
  "integrations", "audio", "weather", "panel", "handoff",
];

function handle() {
  const m = /^#(settings|app)\/([\w-]+)$/.exec(window.location.hash);
  if (!m) return;
  if (m[1] === "settings" && (TABS as readonly string[]).includes(m[2])) openSettings(m[2] as SettingsTab);
  else if (m[1] === "app") inspect(m[2]);
  else return;
  history.replaceState(null, "", window.location.pathname + window.location.search);
}

export function installDeepLinks() {
  // after the first render, so the inspector / sheet are mounted
  setTimeout(handle, 0);
  window.addEventListener("hashchange", handle);
}

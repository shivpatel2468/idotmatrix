/**
 * What Android's Back button does in the phone studio, innermost first (lib/android.ts runs it):
 * close what's open on top (a sheet, a dialog, a menu) → else go back to the Panel tab from Apps, Presets or
 * Settings → else leave (the app goes to the home screen and keeps running). No imports: tested with plain node.
 */
export type BackStep = "close" | "panel" | "leave";

export function backStep(somethingOpen: boolean, tab: string): BackStep {
  if (somethingOpen) return "close";
  if (tab !== "panel") return "panel";
  return "leave";
}

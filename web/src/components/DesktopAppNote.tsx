import { Download } from "lucide-react";
import { DESKTOP_APP_URL } from "../lib/platform";
import { useStore } from "../lib/store";

/** "Get the desktop app" — the link the browser app shows next to anything a tab can't do (docs/WEB_APP.md). */
export function DesktopAppLink({ className }: { className?: string }) {
  return (
    <a href={DESKTOP_APP_URL} target="_blank" rel="noopener" className={className ?? "inline-flex items-center gap-1 whitespace-nowrap font-[560] text-ember underline-offset-2 hover:underline"}>
      <Download size={12} aria-hidden /> Get the desktop app
    </a>
  );
}

/**
 * The browser app only (meta.platform "web"): one line saying why this needs the computer itself, and the link to
 * the desktop app. Renders nothing in the desktop / Android studio.
 */
export function DesktopAppNote({ why }: { why: string }) {
  const web = useStore((s) => s.meta?.platform === "web");
  if (!web) return null;
  return (
    <p role="note" className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2 text-[11.5px] leading-snug text-ink-3">
      <span><span className="font-[600] text-warn">Not in the browser:</span> {why}</span>
      <DesktopAppLink />
    </p>
  );
}

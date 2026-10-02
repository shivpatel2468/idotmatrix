// Small browser-compatibility shims for the studio (docs/COMPATIBILITY.md → "Studio browsers").

/**
 * Copy text to the clipboard. `navigator.clipboard` only exists in secure contexts (https or localhost), so a
 * studio opened over the LAN as http://<pi>.local:8765 falls back to a hidden textarea + execCommand("copy").
 * Resolves false when neither works (the caller tells the user to select the text instead).
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* permission denied: try the legacy path */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length); // iOS Safari ignores select() alone
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

type WebkitDoc = Document & { webkitFullscreenElement?: Element | null; webkitExitFullscreen?: () => void };
type WebkitEl = HTMLElement & { webkitRequestFullscreen?: () => void };

/** The element in fullscreen, including Safari < 16.4's prefixed API. */
export function fullscreenElement(): Element | null {
  const d = document as WebkitDoc;
  return d.fullscreenElement ?? d.webkitFullscreenElement ?? null;
}

/**
 * Enter fullscreen where the browser allows it. iPhone Safari has no element fullscreen at all (only video), so
 * this resolves false and the caller's fixed overlay simply covers the page.
 */
export async function requestFullscreen(el: HTMLElement | null): Promise<boolean> {
  if (!el) return false;
  try {
    if (el.requestFullscreen) {
      await el.requestFullscreen();
      return true;
    }
    const w = el as WebkitEl;
    if (w.webkitRequestFullscreen) {
      w.webkitRequestFullscreen();
      return true;
    }
  } catch {
    /* not allowed (iframe, no user gesture) */
  }
  return false;
}

export function exitFullscreen(): void {
  const d = document as WebkitDoc;
  if (d.fullscreenElement) d.exitFullscreen().catch(() => {});
  else if (d.webkitFullscreenElement) d.webkitExitFullscreen?.();
}

/** Listen for fullscreen changes (standard + webkit-prefixed); returns the unsubscribe function. */
export function onFullscreenChange(fn: () => void): () => void {
  document.addEventListener("fullscreenchange", fn);
  document.addEventListener("webkitfullscreenchange", fn);
  return () => {
    document.removeEventListener("fullscreenchange", fn);
    document.removeEventListener("webkitfullscreenchange", fn);
  };
}

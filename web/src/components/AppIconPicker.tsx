import { Check, Info } from "lucide-react";
import { useState } from "react";
import { appIconIds, currentAppIcon, inAndroidApp, screenInfo, setAppIcon } from "../lib/android";
import { APP_ICONS } from "../lib/appIcons";
import { toast } from "../lib/store";

/** The launcher artwork (the adaptive icon's visible middle, 18..90 of 108) — the same drawing as the APK's. */
export function AppIconArt({ svg, size = 60 }: { svg: string; size?: number }) {
  return <svg viewBox="18 18 72 72" width={size} height={size} aria-hidden dangerouslySetInnerHTML={{ __html: svg }} />;
}

/**
 * Settings → Display & colour → App icon. Only inside the Android app (it needs `DeskDotAndroid`): a grid of the
 * launcher icons, the current one ticked. Choosing one flips the app's <activity-alias> (MainActivity.switchIcon).
 */
export function AppIconPicker() {
  const known = appIconIds();
  const options = known ? APP_ICONS.filter((i) => known.includes(i.id)) : APP_ICONS;
  const [cur, setCur] = useState(() => currentAppIcon() ?? "classic");
  const screen = screenInfo();
  if (!inAndroidApp()) return null;
  const pick = (id: string, name: string) => {
    if (id === cur) return;
    if (!setAppIcon(id)) return void toast("This version of the app can't switch to that icon — update the app", "error");
    setCur(id);
    toast(`Icon changed to ${name} — your home screen updates in a few seconds`, "ok");
  };
  return (
    <div className="space-y-3">
      <div className="appicon-grid" role="radiogroup" aria-label="App icon">
        {options.map((i) => (
          <button key={i.id} className="appicon" role="radio" aria-checked={cur === i.id} title={i.hint} onClick={() => pick(i.id, i.name)}>
            <AppIconArt svg={i.svg} />
            <span className="text-center text-[11.5px] font-[580] leading-tight text-ink-1">{i.name}</span>
            {cur === i.id && <span className="appicon-check"><Check size={12} strokeWidth={3} /></span>}
          </button>
        ))}
      </div>
      <p className="flex gap-2 text-[11.5px] leading-snug text-ink-3">
        <Info size={14} className="mt-px shrink-0" />
        <span>
          The launcher takes a few seconds to show the new icon. Some launchers (MIUI among them) remove the old
          home-screen shortcut — add DeskDot to the home screen again from the app drawer. DeskDot keeps running and
          the panel stays connected.
        </span>
      </p>
      {screen && (
        <p className="font-mono text-[10.5px] text-ink-4">
          Screen: {screen.hz} Hz now · up to {screen.max} Hz{screen.modes.length > 1 ? ` (${screen.modes.join(" / ")})` : ""}
        </p>
      )}
    </div>
  );
}

import { Power } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { toast, useStore } from "../lib/store";

/**
 * Panel power behind an eject-seat style guard: lift the striped cover, then press the red button.
 * The cover drops back after a few seconds. Turning the panel ON is harmless, so it's one click.
 */
export function SafetySwitch() {
  const power = useStore((s) => s.state?.settings.power ?? true);
  const [open, setOpen] = useState(false);
  const [left, setLeft] = useState(0);
  const timer = useRef(0);

  useEffect(() => {
    if (!open) return;
    setLeft(4);
    const start = performance.now();
    timer.current = window.setInterval(() => {
      const remaining = 4 - (performance.now() - start) / 1000;
      if (remaining <= 0) {
        setOpen(false);
        clearInterval(timer.current);
      } else setLeft(remaining);
    }, 100);
    return () => clearInterval(timer.current);
  }, [open]);

  if (!power) {
    return (
      <button className="safety-on key" title="Turn the panel on" onClick={() => api.settings({ power: true })}>
        <Power size={14} /> <span className="hidden md:inline">Panel off · turn on</span>
      </button>
    );
  }

  const kill = () => {
    setOpen(false);
    api.settings({ power: false });
    toast("Panel switched off", "info");
  };

  return (
    <div className="safety" data-open={open} title={open ? "Press the red button to switch the panel off" : "Lift the guard to switch the panel off"}>
      <button className="safety-btn" aria-label="Switch panel off" tabIndex={open ? 0 : -1} onClick={kill}>
        <Power size={13} strokeWidth={2.4} />
      </button>
      <button
        className="safety-cover"
        aria-label={open ? "Close guard" : "Lift guard to reveal power button"}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="safety-hinge" />
      </button>
      {open && (
        <svg className="safety-ring" viewBox="0 0 36 36" aria-hidden>
          <circle cx="18" cy="18" r="16" pathLength="100" strokeDasharray={`${(left / 4) * 100} 100`} />
        </svg>
      )}
    </div>
  );
}

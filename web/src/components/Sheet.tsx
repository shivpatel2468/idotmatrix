import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * A phone bottom sheet: slides up from the thumb zone, a grab handle you can drag down to close, the home-indicator
 * inset respected, at most 88 % of the visible height (dvh) and its own scroll that never chains to the page.
 */
export function Sheet({ open, onClose, title, children, footer }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const [drag, setDrag] = useState(0);
  const start = useRef<number | null>(null);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    setDrag(0);
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;

  // drag down from the handle / title row (or the body when it's scrolled to the top)
  const down = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button, input, select, textarea, a, [role=slider]")) return;
    if (body.current?.contains(e.target as Node) && body.current.scrollTop > 0) return;
    start.current = e.clientY;
  };
  const move = (e: React.PointerEvent) => {
    if (start.current == null) return;
    setDrag(Math.max(0, e.clientY - start.current));
  };
  const up = () => {
    if (start.current == null) return;
    start.current = null;
    if (drag > 90) onClose();
    else setDrag(0);
  };

  return createPortal(
    <div className="sheet-root" role="presentation">
      <div className="sheet-scrim" onClick={onClose} style={{ opacity: Math.max(0, 1 - drag / 320) }} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}
        style={drag ? { transform: `translateY(${drag}px)`, transition: "none" } : undefined}
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
        <div className="sheet-handle" aria-hidden />
        <div className="flex items-center gap-2 px-5 pb-2">
          <h2 className="font-display text-[17px] font-[640] tracking-[-0.015em]">{title}</h2>
          <button className="key key-ghost key-icon -mr-2 ml-auto" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div ref={body} className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

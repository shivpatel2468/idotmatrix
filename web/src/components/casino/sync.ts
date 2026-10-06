/**
 * The shared casino clock (docs/TV_VIEW.md §3, "The shared clock") — the same model as the TV
 * (src/deskdot/tv/tv-casino.js `serverClock`) and the phone page (src/deskdot/casino.html "shared sync clock"):
 *
 * - the engine publishes the round's timers as wall-clock anchors in `status.clock` (`ends_at`, `lock_at`,
 *   `reveal_at`, `next_at`, `turn_at` … in the engine's `time.time()` seconds), constant within a phase;
 * - each device keeps one synced clock: its monotonic `performance.now()` plus an offset to the engine's clock,
 *   **slewed** (at most 30 % of real time, never backwards; a jump over 1 s snaps), and counts every countdown and
 *   flip down to those anchors — so the panel, the TV, every phone and the studio flip at the same moment.
 *
 * The studio runs on the engine's own machine (the desktop engine, or the web app's in-tab engine), so its offset
 * starts at the browser's wall clock; `sample()` refines it from a server timestamp when one is available.
 */

const local = () => performance.now() / 1000;

let est: number | null = null; // engine time − local monotonic time, from samples
let off: number | null = null; // the slewed offset in use
let lastL = 0;
let lastT: number | null = null;

/** Feed a server timestamp: `serverTime` (s) seen between local times `sent` and `recv` (s, performance.now). */
export function sample(serverTime: number, sent: number, recv: number): void {
  const rtt = recv - sent;
  if (!Number.isFinite(serverTime) || rtt < 0 || rtt > 1.5) return;
  const o = serverTime - (sent + recv) / 2;
  est = est == null ? o : est + (o - est) * (rtt < 0.15 ? 0.3 : 0.1);
}

/** The engine's clock now (s): smooth and monotonic. */
export function serverNow(): number {
  const l = local();
  const target = est ?? Date.now() / 1000 - l;
  if (off == null || Math.abs(target - off) > 1) off = target;
  else {
    const dt = Math.min(0.5, Math.max(0, l - lastL));
    off += Math.max(-0.3 * dt, Math.min(0.3 * dt, target - off));
  }
  lastL = l;
  let t = l + off;
  if (lastT != null && t < lastT) t = lastT;
  lastT = t;
  return t;
}

/** Seconds until a `status.clock` anchor (≥ 0), or null without one. */
export function untilAnchor(at: number | null | undefined): number | null {
  return at == null ? null : Math.max(0, at - serverNow());
}

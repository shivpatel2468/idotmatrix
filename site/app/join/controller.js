"use strict";
/* ============================== basics ============================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const app = $("#app");
const code = location.pathname.split("/").filter(Boolean).pop() || "";
const SECURE = window.isSecureContext === true;
const SEATS = { 1: "#00c8ff", 2: "#ff3c5a", 3: "#50ff78", 4: "#ffc800" };
const TEAMS = { 0: "#00c8ff", 1: "#ff3c5a" };
const DIRS = ["up", "down", "left", "right"];
const now = () => performance.now();
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function cap(el, e) { try { el.setPointerCapture(e.pointerId); } catch (_) { /* synthetic / already gone */ } }
function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || "null"); localStorage.setItem(k, JSON.stringify(v)); } catch (_) { return null; } return v; }

/* ============================== session state ============================== */
// cid: this phone's identity, so a reconnect (Wi-Fi blip, reload) gets the same seat back while it's free
let cid = store("deskdot.cid");
if (typeof cid !== "string" || !/^[A-Za-z0-9_-]{8,40}$/.test(cid)) {
  const a = new Uint8Array(12); (crypto.getRandomValues ? crypto.getRandomValues(a) : a.forEach((_, i) => { a[i] = Math.random() * 256; }));
  cid = "p" + [...a].map((b) => "abcdefghijklmnopqrstuvwxyz0123456789"[b % 36]).join("");
  store("deskdot.cid", cid);
}
const S = {
  screen: "join", seat: 0, game: "", maxPlayers: 2, palette: [], avatars: {}, avatarIds: [], modes: [],
  me: { name: "", color: "#ff4818", avatar: "", team: null, ready: false }, roster: [], status: {}, pendingColor: "",
  fromPlay: false, hello: false,
};
const FUN = ["Pixel", "Blip", "Nova", "Zap", "Byte", "Comet", "Echo", "Fizz", "Jinx", "Kiwi", "Lumen", "Mochi", "Neon", "Orbit", "Pip", "Rex", "Sprout", "Turbo", "Vex", "Waffle", "Yeti", "Ziggy", "Bolt", "Dash"];
const cleanName = (s) => String(s || "").replace(/[^A-Za-z0-9 !?.'_+&#*-]/g, "").replace(/\s+/g, " ").replace(/^\s+/, "").slice(0, 10);

/* ============================== screens ============================== */
const ORDER = ["join", "seat", "char", "ready", "play"];
function go(name) {
  if (S.screen === name) return;
  const back = ORDER.indexOf(name) < ORDER.indexOf(S.screen);
  releaseAll();
  for (const s of $$(".scr")) {
    const on = s.id === "s-" + name;
    s.classList.toggle("back", !on && back === false && ORDER.indexOf(s.id.slice(2)) < ORDER.indexOf(name));
    s.classList.toggle("on", on);
    s.inert = !on;
  }
  S.screen = name;
  try { sessionStorage.setItem("deskdot.scr:" + code, name); } catch (_) {}
  $("#netc").hidden = name === "play";
  if (name === "play") { layout(); paintAll(); }
  if (name === "char") renderChar();
  if (name === "ready") renderReady();
}

/* ============================== avatars (canvas, LED look) ============================== */
const FIXED = { w: "#ebebeb", k: "#000000", y: "#ffc800", r: "#ff283c" };
function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v) => Math.round(v * k).toString(16).padStart(2, "0");
  return "#" + f(n >> 16) + f((n >> 8) & 255) + f(n & 255);
}
function drawAvatar(cv, id, color, led = true) {
  const px = (S.avatars[id] || S.avatars[S.avatarIds[0]] || {}).px;
  const css = Number(cv.dataset.s) || 64, dpr = Math.min(2, window.devicePixelRatio || 1), W = Math.round(css * dpr);
  if (cv.width !== W) { cv.width = W; cv.height = W; }
  if (!cv.style.width) { cv.style.width = css + "px"; cv.style.height = css + "px"; }
  const g = cv.getContext("2d");
  g.clearRect(0, 0, W, W);
  if (!px) return;
  const n = px.length, cell = W / n, r = cell * 0.42;
  const col = { c: color, d: shade(color, 0.5), ...FIXED };
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const ch = px[y][x];
    const fill = ch === "." || ch === " " ? null : col[ch];
    const cx = x * cell + cell / 2, cy = y * cell + cell / 2;
    if (!led) { if (fill) { g.fillStyle = fill; g.fillRect(x * cell, y * cell, cell + 0.5, cell + 0.5); } continue; }
    g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2);
    if (fill && fill !== "#000000") { g.shadowColor = fill; g.shadowBlur = cell * 0.5; g.fillStyle = fill; }
    else { g.shadowBlur = 0; g.fillStyle = "rgba(255,255,255,.06)"; }
    g.fill();
  }
  g.shadowBlur = 0;
}

/* ============================== modes & settings ============================== */
const ICON = {
  dpad: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 2.5h6v6.5h6.5v6H15v6.5H9V15H2.5V9H9z"/></svg>',
  joystick: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="14.5" cy="9.5" r="3.6" fill="currentColor"/></svg>',
  swipe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h15M13 6l6 6-6 6"/><circle cx="4" cy="12" r="1.4" fill="currentColor"/></svg>',
  tap: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2.5" y="4" width="8.5" height="16" rx="2.5"/><rect x="13" y="4" width="8.5" height="16" rx="2.5" fill="currentColor"/></svg>',
  keyboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2.5"/><path d="M6 10h1M10 10h1M14 10h1M18 10h0M7 14h10" stroke-linecap="round"/></svg>',
  gamepad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 7h10a5 5 0 0 1 4.8 6.4l-1 3.4a2.5 2.5 0 0 1-4.3 1L15 16H9l-1.5 1.8a2.5 2.5 0 0 1-4.3-1l-1-3.4A5 5 0 0 1 7 7z"/><path d="M8 10v4M6 12h4" stroke-linecap="round"/><circle cx="16" cy="11" r="1" fill="currentColor"/><circle cx="18" cy="13" r="1" fill="currentColor"/></svg>',
  tilt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="3" width="10" height="18" rx="2.5" transform="rotate(22 12 12)"/><path d="M3 20a9 9 0 0 1 0-6" stroke-linecap="round"/></svg>',
  rps: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="7" width="6" height="10" rx="2.5"/><path d="M10 6h4v5h8v2h-8v1h7v2h-7v1h6v2h-10z" opacity=".9"/></svg>',
};
const LOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>';
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>';
const MODES = {
  dpad: { name: "D-pad + A/B", desc: "Classic cross pad. Slide your thumb between directions without lifting.", hint: "Slide between directions without lifting" },
  joystick: { name: "Analog stick", desc: "A thumbstick that appears where your thumb lands. Snaps to 4 directions; push further to move faster.", hint: "Push further to move faster" },
  swipe: { name: "Swipe", desc: "Swipe to turn and keep sliding to chain turns. Tap for A; hold or two-finger tap for B.", hint: "" },
  tap: { name: "Tap zones", desc: "Hold the left or right half of the screen. Great one-thumb racing.", hint: "" },
  keyboard: { name: "Keyboard", desc: "A Bluetooth keyboard paired with this phone: arrows or WASD, Space = A, Shift = B.", hint: "" },
  gamepad: { name: "Game controller", desc: "Xbox, PlayStation, Switch Pro or 8BitDo paired with this phone.", hint: "" },
  rps: { name: "Hand picker", desc: "Three big buttons: rock, paper, scissors. Tap one to lock in your hand.", hint: "" },
  tilt: { name: "Tilt to steer", desc: "Tilt the phone left and right like a steering wheel.", hint: "Tilt like a steering wheel" },
};
const MODE_IDS = Object.keys(MODES);
// Gamepad API and DeviceOrientation are secure-context only; this page is plain http on the LAN.
const AVAIL = {
  gamepad: !SECURE ? "insecure" : typeof navigator.getGamepads === "function" ? "" : "unsupported",
  tilt: !SECURE ? "insecure" : "DeviceOrientationEvent" in window ? "" : "unsupported",
};
const WHY = {
  gamepad: {
    insecure: "Your browser only allows controllers on secure pages — use the on-screen joystick, or connect the controller to the laptop instead: the studio supports gamepads.",
    unsupported: "This browser can't read game controllers — use the on-screen joystick, or connect the controller to the laptop instead: the studio supports gamepads.",
  },
  tilt: {
    insecure: "Your browser only shares the tilt sensor with secure pages, and this game link is a plain local address — use the joystick or tap zones instead.",
    unsupported: "This browser can't read the tilt sensor — use the joystick or tap zones instead.",
  },
};
const why = (m) => (AVAIL[m] ? WHY[m][AVAIL[m]] : "");
const usable = (m) => !!MODES[m] && !AVAIL[m] && (m !== "rps" || controls.includes("rps")); // the hand picker only suits RPS

const OPTS = [
  { k: "stick", t: "Stick position", seg: [["float", "Where I touch"], ["fixed", "Fixed"]], modes: ["joystick"] },
  { k: "ways", t: "Directions", d: "4-way snaps to the nearest direction; 8-way sends both keys on diagonals", seg: [[4, "4-way"], [8, "8-way"]], modes: ["joystick", "gamepad"] },
  { k: "dead", t: "Dead zone", d: "How far to push before it moves", seg: [[0.08, "Tiny"], [0.15, "Small"], [0.25, "Medium"], [0.35, "Large"]], modes: ["joystick", "gamepad"] },
  { k: "swipe", t: "Swipe sensitivity", seg: [["low", "Low"], ["medium", "Medium"], ["high", "High"]], modes: ["swipe"] },
  { k: "strip", t: "A/B buttons", d: "A strip along the bottom", sw: 1, modes: ["tap"] },
  { k: "tilt", t: "Tilt sensitivity", seg: [["low", "Low"], ["medium", "Medium"], ["high", "High"]], modes: ["tilt"] },
  { k: "size", t: "Button size", seg: [["S", "S"], ["M", "M"], ["L", "L"]] },
  { k: "lefty", t: "Left-handed", d: "Mirror the layout", sw: 1 },
  { k: "repeat", t: "Repeat speed", d: "While you hold a direction", seg: [["off", "Off"], ["slow", "Slow"], ["normal", "Normal"], ["fast", "Fast"]] },
  { k: "haptics", t: "Vibration", sw: 1, na: typeof navigator.vibrate !== "function" ? "This phone's browser can't vibrate" : "" },
  { k: "awake", t: "Keep screen on", sw: 1, na: "wakeLock" in navigator ? "" : SECURE ? "Not supported by this browser" : "This browser only allows it on secure pages" },
];
const OPT = Object.fromEntries(OPTS.map((o) => [o.k, o]));
const DEF = { mode: "", size: "M", lefty: false, haptics: true, repeat: "normal", dead: 0.15, ways: 4, stick: "float", swipe: "medium", strip: true, tilt: "medium", awake: true };
const COMFORT = ["size", "lefty", "haptics", "repeat", "awake"]; // carried over to games you haven't set up yet
let cfg = { ...DEF, mode: "dpad" };
let controls = ["dpad"];

function validOpt(k, v) {
  if (k === "mode") return usable(v);
  const o = OPT[k];
  if (!o) return false;
  return o.sw ? typeof v === "boolean" : o.seg.some(([val]) => String(val) === String(v));
}
function loadCfg() {
  const g = store("deskdot.pad") || {}, s = store("deskdot.pad:" + S.game) || {};
  const next = { ...DEF };
  for (const k of COMFORT) if (validOpt(k, g[k])) next[k] = g[k];
  for (const k of Object.keys(DEF)) if (validOpt(k, s[k])) next[k] = typeof DEF[k] === "number" ? Number(s[k]) : s[k];
  if (!usable(next.mode)) next.mode = controls.find(usable) || "dpad";
  cfg = next;
}
function saveCfg() {
  if (!S.game) return;
  store("deskdot.pad:" + S.game, cfg);
  store("deskdot.pad", Object.fromEntries(COMFORT.map((k) => [k, cfg[k]])));
}

/* ============================== input core ============================== */
// Every press goes out the instant it happens (no debounce, no queue); holds repeat on their own timers.
// Visual feedback is painted in the same handler, before the network round trip.
let ws = null;
const live = () => S.screen === "play" && ws && ws.readyState === 1;
function send(k) { if (live()) ws.send('{"k":"' + k + '"}'); }
function buzz(ms) { if (cfg.haptics && typeof navigator.vibrate === "function") { try { navigator.vibrate(ms); } catch (_) {} } }
function press(k) { send(k); buzz(14); }

const REP = { off: [1e9, 1e9], slow: [320, 140], normal: [220, 90], fast: [150, 55] }; // [first repeat, then every] ms
const discrete = (first) => REP[cfg.repeat][first ? 0 : 1];
function analog(getT) { // t = 0 just past the dead zone … 1 fully pushed: the repeat rate follows deflection
  return (first) => {
    if (cfg.repeat === "off") return 1e9;
    const [d, i] = REP[cfg.repeat], t = clamp(getT(), 0, 1), iv = i * 3.2 - (i * 3.2 - i * 0.7) * t;
    return first ? Math.max(iv, d * 0.8) : iv;
  };
}
const holds = new Map(); // source -> {sig, keys, i, rate, first, last, due, timer}
function arm(src, h, ms) {
  h.due = now() + ms;
  if (ms >= 1e8) return; // repeat off
  h.timer = setTimeout(() => {
    if (holds.get(src) !== h) return;
    send(h.keys[h.i++ % h.keys.length]); h.last = now(); h.first = false;
    arm(src, h, h.rate(false));
  }, ms);
}
function hold(src, keys, rate) {
  const sig = keys.join(), h = holds.get(src);
  if (h && h.sig === sig) { // same direction: adopt the new rate; pull the next repeat in if it got faster
    h.rate = rate;
    const ms = rate(h.first), t = now();
    if (h.due - t > ms * 1.2 + 8) { clearTimeout(h.timer); arm(src, h, Math.max(0, h.last + ms - t)); }
    return;
  }
  const prev = h ? h.keys : [];
  if (h) clearTimeout(h.timer);
  const fresh = keys.filter((k) => !prev.includes(k));
  for (const k of fresh) send(k); // send first, then everything else
  const nh = { sig, keys, i: fresh.length ? (keys.indexOf(fresh[fresh.length - 1]) + 1) % keys.length : 0, rate, first: true, last: now(), due: 0, timer: 0 };
  holds.set(src, nh);
  arm(src, nh, rate(true));
  if (fresh.length) buzz(9);
}
function unhold(src) { const h = holds.get(src); if (h) { clearTimeout(h.timer); holds.delete(src); } }
const resets = [];
function releaseAll() { for (const h of holds.values()) clearTimeout(h.timer); holds.clear(); for (const r of resets) r(); }

function dir4(dx, dy, cur) { // hysteresis: keep the current axis until the other clearly dominates (no diagonal flicker)
  const ax = Math.abs(dx), ay = Math.abs(dy);
  let horiz = ax > ay;
  if (cur === "left" || cur === "right") horiz = ax * 1.3 >= ay;
  else if (cur === "up" || cur === "down") horiz = ax > ay * 1.3;
  return horiz ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
}
const OCT = [["right"], ["down", "right"], ["down"], ["down", "left"], ["left"], ["up", "left"], ["up"], ["up", "right"]];
function oct(dx, dy) { return ((Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) % 8) + 8) % 8; }
const ANG = { right: 0, down: 90, left: 180, up: 270 };

/* ---------- A/B clusters (slide between buttons, multi-touch) ---------- */
function bindButtons(group) {
  const btns = $$("[data-k]", group), ptr = new Map();
  const hit = (e) => {
    let best = null, bd = 1e9;
    for (const b of btns) {
      const r = b.getBoundingClientRect();
      if (e.clientX >= r.left - 8 && e.clientX <= r.right + 8 && e.clientY >= r.top - 8 && e.clientY <= r.bottom + 8) return b;
      const d = Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2));
      if (d < bd && d < Math.max(r.width, r.height) * 0.9) { bd = d; best = b; }
    }
    return best;
  };
  const paint = () => { const on = new Set(ptr.values()); for (const b of btns) b.classList.toggle("on", on.has(b)); };
  group.addEventListener("pointerdown", (e) => {
    e.preventDefault(); cap(group, e);
    const b = hit(e); ptr.set(e.pointerId, b);
    paint(); // light up first (same frame), then send
    if (b) press(b.dataset.k);
  });
  group.addEventListener("pointermove", (e) => {
    if (!ptr.has(e.pointerId)) return;
    const b = hit(e);
    if (b === ptr.get(e.pointerId)) return;
    ptr.set(e.pointerId, b); paint();
    if (b) press(b.dataset.k); // rolled onto the other button
  });
  const end = (e) => { if (ptr.delete(e.pointerId)) paint(); };
  for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) group.addEventListener(t, end);
  for (const b of btns) b.addEventListener("click", (e) => { if (e.detail === 0) { press(b.dataset.k); flash(b); } }); // keyboard / screen reader
  resets.push(() => { ptr.clear(); paint(); });
}
function flash(el) { el.classList.add("on"); setTimeout(() => el.classList.remove("on"), 120); }

for (const slot of $$(".slot-ab")) slot.appendChild($("#tpl-ab").content.cloneNode(true));
for (const slot of $$(".slot-info")) slot.appendChild($("#tpl-info").content.cloneNode(true));
for (const g of $$(".ab")) bindButtons(g);
bindButtons($("#strip"));

/* ---------- D-pad: one surface, 4-way with hysteresis, slide between arms ---------- */
(() => {
  const zone = $("#dpad"), cross = $(".cross", zone), arms = Object.fromEntries(DIRS.map((d) => [d, $(".arm." + d, zone)]));
  const ptr = new Map();
  const paint = () => {
    const on = new Set(ptr.values());
    for (const d of DIRS) arms[d].classList.toggle("on", on.has(d));
    const last = [...ptr.values()].filter(Boolean).pop();
    if (last) cross.dataset.d = last; else delete cross.dataset.d;
  };
  const upd = (e) => {
    const r = cross.getBoundingClientRect(), dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
    const cur = ptr.get(e.pointerId);
    if (Math.hypot(dx, dy) < r.width * 0.1) { // resting on the hub: nothing pressed
      if (cur) { unhold("dp" + e.pointerId); ptr.set(e.pointerId, null); paint(); }
      return;
    }
    const d = dir4(dx, dy, cur);
    if (d !== cur) { ptr.set(e.pointerId, d); paint(); hold("dp" + e.pointerId, [d], discrete); }
  };
  zone.addEventListener("pointerdown", (e) => { e.preventDefault(); cap(zone, e); ptr.set(e.pointerId, null); upd(e); });
  zone.addEventListener("pointermove", (e) => { if (ptr.has(e.pointerId)) upd(e); });
  const end = (e) => { if (!ptr.has(e.pointerId)) return; ptr.delete(e.pointerId); unhold("dp" + e.pointerId); paint(); };
  for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) zone.addEventListener(t, end);
  for (const d of DIRS) arms[d].addEventListener("click", (e) => { if (e.detail === 0) { press(d); flash(arms[d]); } });
  resets.push(() => { ptr.clear(); paint(); });
})();

/* ---------- analog stick: dead zone, 4-way snap (or 8-way), rate follows deflection ---------- */
const stick = (() => {
  const zone = $("#stick"), base = $("#sbase"), knob = $("#sknob"), wedge = $("#sdir");
  let id = null, cx = 0, cy = 0, t = 0, cur = null;
  const rate = analog(() => t);
  const place = () => { base.style.transform = `translate(${cx}px,${cy}px)`; };
  const home = () => { const r = zone.getBoundingClientRect(); cx = r.width / 2; cy = r.height * (app.classList.contains("land") ? 0.5 : 0.56); place(); };
  function move(e) {
    const r = zone.getBoundingClientRect(), R = base.offsetWidth * 0.4;
    let dx = e.clientX - r.left - cx, dy = e.clientY - r.top - cy, d = Math.hypot(dx, dy);
    if (d > R && cfg.stick === "float") { const k = (d - R) / d; cx += dx * k; cy += dy * k; dx -= dx * k; dy -= dy * k; d = R; place(); } // the stick follows the thumb
    const m = Math.min(d, R) / R;
    let keys = null;
    if (m >= cfg.dead) {
      t = (m - cfg.dead) / (1 - cfg.dead);
      keys = cfg.ways === 8 ? OCT[oct(dx, dy)] : [dir4(dx, dy, cur && cur.length === 1 ? cur[0] : null)];
      hold("js", keys, rate); // input first …
    } else if (cur) { t = 0; unhold("js"); }
    // … then visuals: the knob snaps onto the chosen axis in 4-way so you see what is being sent
    let kd = Math.min(d, R), ux = d ? dx / d : 0, uy = d ? dy / d : 0;
    if (keys && cfg.ways === 4) { const a = ANG[keys[0]] * Math.PI / 180, sx = Math.cos(a), sy = Math.sin(a); ux = ux * 0.35 + sx * 0.65; uy = uy * 0.35 + sy * 0.65; const l = Math.hypot(ux, uy) || 1; ux /= l; uy /= l; }
    knob.style.transform = `translate(${ux * kd}px,${uy * kd}px)`;
    if ((keys && keys.join()) !== (cur && cur.join())) {
      cur = keys;
      zone.classList.toggle("go", !!keys);
      if (keys) {
        const w = cfg.ways === 8 ? 45 : 90, a = cfg.ways === 8 ? oct(dx, dy) * 45 : ANG[keys[0]];
        wedge.style.setProperty("--a", a + "deg"); wedge.style.setProperty("--w", w + "deg");
      }
    }
  }
  zone.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (id !== null) return;
    id = e.pointerId; cap(zone, e);
    if (cfg.stick === "float") {
      const r = zone.getBoundingClientRect(), h = base.offsetWidth / 2;
      cx = clamp(e.clientX - r.left, Math.min(h * 0.7, r.width / 2), Math.max(r.width - h * 0.7, r.width / 2));
      cy = clamp(e.clientY - r.top, Math.min(h * 0.7, r.height / 2), Math.max(r.height - h * 0.7, r.height / 2));
      place();
    } else home();
    zone.classList.add("active"); move(e);
  });
  zone.addEventListener("pointermove", (e) => { if (e.pointerId === id) move(e); });
  const end = (e) => { if (e && e.pointerId !== id) return; id = null; t = 0; cur = null; unhold("js"); knob.style.transform = ""; zone.classList.remove("active", "go"); if (cfg.stick === "fixed") home(); };
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) zone.addEventListener(ev, end);
  resets.push(() => end());
  return { apply() { zone.classList.toggle("fixed", cfg.stick === "fixed"); if (cfg.stick === "fixed" && id === null) home(); } };
})();

/* ---------- swipe ---------- */
(() => {
  const el = $("#swipe"), glyph = $("#swglyph"), P = new Map();
  const TH = { low: 44, medium: 28, high: 16 };
  const local = (x, y) => { const r = el.getBoundingClientRect(); return [x - r.left, y - r.top]; };
  function show(dir) {
    const rot = { up: 0, right: 90, down: 180, left: 270 }[dir];
    if (glyph.animate) glyph.animate([{ opacity: 0.95, transform: `translate(-50%,-50%) rotate(${rot}deg) scale(1.12)` }, { opacity: 0.14, transform: `translate(-50%,-50%) rotate(${rot}deg) scale(1)` }], { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)", fill: "forwards" });
  }
  function ring(x, y, label) {
    const [lx, ly] = local(x, y), d = document.createElement("div");
    d.className = "fx"; d.textContent = label; d.style.transform = `translate(${lx}px,${ly}px)`;
    el.appendChild(d);
    const a = d.animate ? d.animate([{ opacity: 1, transform: `translate(${lx}px,${ly}px) scale(.6)` }, { opacity: 0, transform: `translate(${lx}px,${ly}px) scale(1.5)` }], { duration: 420, easing: "ease-out" }) : null;
    if (a) a.onfinish = () => d.remove(); else setTimeout(() => d.remove(), 400);
  }
  function trail(s, x, y) { const [lx, ly] = local(x, y); s.dot.style.transform = `translate(${lx}px,${ly}px)`; }
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault(); cap(el, e);
    const t = now(), dot = document.createElement("div");
    dot.className = "trail"; el.appendChild(dot);
    const s = { x0: e.clientX, y0: e.clientY, ax: e.clientX, ay: e.clientY, t0: t, dir: null, run: 0, used: false, lp: 0, dot };
    // a second finger landing while another rests (no swipe yet) = two-finger tap = B
    for (const o of P.values()) if (!o.dir && !o.used && t - o.t0 < 500) { o.used = s.used = true; clearTimeout(o.lp); press("b"); ring(e.clientX, e.clientY, "B"); break; }
    if (!s.used) s.lp = setTimeout(() => { if (!s.dir && !s.used) { s.used = true; send("b"); buzz(25); ring(s.x0, s.y0, "B"); } }, 480);
    P.set(e.pointerId, s); trail(s, e.clientX, e.clientY);
  });
  el.addEventListener("pointermove", (e) => {
    const s = P.get(e.pointerId);
    if (!s) return;
    const th = TH[cfg.swipe];
    if (Math.hypot(e.clientX - s.x0, e.clientY - s.y0) > th * 0.5) clearTimeout(s.lp);
    const dx = e.clientX - s.ax, dy = e.clientY - s.ay, d = Math.hypot(dx, dy);
    if (d >= th) {
      const dir = dir4(dx, dy, null);
      if (dir !== s.dir) { send(dir); buzz(8); s.dir = dir; s.run = 0; show(dir); } // chain: turn without lifting
      else if ((s.run += d) >= th * 2.5) { send(dir); s.run = 0; show(dir); } // keep sliding the same way: step again
      s.ax = e.clientX; s.ay = e.clientY;
    }
    trail(s, e.clientX, e.clientY);
  });
  const end = (e, cancel) => {
    const s = P.get(e.pointerId);
    if (!s) return;
    P.delete(e.pointerId); clearTimeout(s.lp); s.dot.remove();
    if (cancel || s.dir || s.used) return;
    const th = TH[cfg.swipe], dx = e.clientX - s.x0, dy = e.clientY - s.y0;
    if (Math.hypot(dx, dy) < th) { press("a"); ring(e.clientX, e.clientY, "A"); } // a tap (necessarily judged on release)
    else { const dir = dir4(dx, dy, null); send(dir); buzz(8); show(dir); } // a flick too fast for move events
  };
  el.addEventListener("pointerup", (e) => end(e, false));
  el.addEventListener("pointercancel", (e) => end(e, true));
  resets.push(() => { for (const s of P.values()) { clearTimeout(s.lp); s.dot.remove(); } P.clear(); });
})();

/* ---------- tap zones ---------- */
(() => {
  const el = $("#tz"), halves = Object.fromEntries($$(".tzh", el).map((h) => [h.dataset.side, h])), P = new Map();
  const side = (e) => { const r = el.getBoundingClientRect(); return e.clientX < r.left + r.width / 2 ? "left" : "right"; };
  const paint = () => { const on = new Set(P.values()); for (const s in halves) halves[s].classList.toggle("on", on.has(s)); };
  el.addEventListener("pointerdown", (e) => { e.preventDefault(); cap(el, e); const s = side(e); P.set(e.pointerId, s); paint(); hold("tz" + e.pointerId, [s], discrete); });
  el.addEventListener("pointermove", (e) => {
    if (!P.has(e.pointerId)) return;
    const s = side(e);
    if (s !== P.get(e.pointerId)) { P.set(e.pointerId, s); paint(); hold("tz" + e.pointerId, [s], discrete); }
  });
  const end = (e) => { if (!P.delete(e.pointerId)) return; unhold("tz" + e.pointerId); paint(); };
  for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) el.addEventListener(t, end);
  resets.push(() => { P.clear(); paint(); });
})();

/* ---------- physical keyboard (works in every layout, only on the controller screen) ---------- */
const KB = { ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down", ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right",
  Space: "a", Enter: "a", NumpadEnter: "a", KeyZ: "a", KeyJ: "a", ShiftLeft: "b", ShiftRight: "b", KeyX: "b", KeyK: "b" };
let kbSeen = false;
function kbLight(c, on) { for (const el of $$(".cap")) if (el.dataset.kc.split(" ").includes(c)) el.classList.toggle("on", on); }
addEventListener("keydown", (e) => {
  if (!$("#sheet").hidden) { if (e.key === "Escape") closeSheet(); return; }
  if (S.screen !== "play" || (e.target && e.target.tagName === "INPUT")) return;
  if (cfg.mode === "rps" && !e.repeat && RPS_DIGIT[e.key]) { e.preventDefault(); rpsPick(RPS_DIGIT[e.key]); return; }
  const c = KB[e.code] ? e.code : KB[e.key] ? e.key : "";
  if (!c) return;
  e.preventDefault();
  if (e.repeat) return; // we run our own repeat
  const k = KB[c];
  kbLight(c, true);
  if (DIRS.includes(k)) hold("kb" + c, [k], discrete); else press(k);
  $("#kblast").textContent = `${e.key === " " ? "Space" : e.key} → ${k.toUpperCase()}`;
  if (!kbSeen) { kbSeen = true; if (cfg.mode !== "keyboard") toast("Keyboard connected — its keys work in every layout"); }
});
addEventListener("keyup", (e) => { const c = KB[e.code] ? e.code : KB[e.key] ? e.key : ""; if (c) { unhold("kb" + c); kbLight(c, false); } });

/* ---------- physical gamepad (standard mapping, rAF polling) ---------- */
const GP = { raf: 0, count: 0, prev: new Map(), mag: {}, rates: {}, dir: {}, sig: "" };
const GBTN = [[0, "a"], [1, "b"], [2, "b"], [3, "a"], [4, "b"], [5, "a"], [8, "b"], [9, "a"]];
const padWanted = () => !AVAIL.gamepad && (cfg.mode === "gamepad" || GP.count > 0);
function padStart() { if (!GP.raf && padWanted()) GP.raf = requestAnimationFrame(padPoll); }
function padPoll() {
  GP.raf = 0;
  if (!padWanted()) return;
  let pads = [];
  try { pads = navigator.getGamepads() || []; } catch (_) {}
  let vis = null;
  for (const p of pads) {
    if (!p || !p.connected) continue;
    const b = (i) => !!(p.buttons[i] && p.buttons[i].pressed), src = "gp" + p.index;
    const dp = [b(12) && "up", b(13) && "down", b(14) && "left", b(15) && "right"].filter(Boolean).slice(0, 2);
    let keys = dp, rate = discrete;
    if (!dp.length) {
      const x = p.axes[0] || 0, y = p.axes[1] || 0, d = Math.min(1, Math.hypot(x, y));
      if (d > cfg.dead) {
        GP.mag[p.index] = (d - cfg.dead) / (1 - cfg.dead);
        rate = GP.rates[p.index] || (GP.rates[p.index] = analog(() => GP.mag[p.index] || 0));
        keys = cfg.ways === 8 ? OCT[oct(x, y)] : [dir4(x, y, GP.dir[p.index])];
      }
    }
    if (keys.length) { hold(src, keys, rate); GP.dir[p.index] = keys.length === 1 ? keys[0] : null; } else { unhold(src); GP.dir[p.index] = null; }
    const prev = GP.prev.get(p.index) || {}, cur = {};
    for (const [i, k] of GBTN) { cur[i] = b(i); if (cur[i] && !prev[i]) press(k); }
    GP.prev.set(p.index, cur);
    if (!vis) vis = { p, keys, a: cur[0] || cur[3] || cur[5] || cur[9], bb: cur[1] || cur[2] || cur[4] || cur[8], stick: !dp.length && keys.length > 0 };
  }
  if (vis && cfg.mode === "gamepad") { // paint only on change, after input
    const sig = [vis.p.id, vis.keys.join(), vis.a, vis.bb, vis.stick].join("|");
    if (sig !== GP.sig) {
      GP.sig = sig;
      for (const el of $$(".gpd .g")) { const g = el.dataset.g; el.classList.toggle("on", vis.keys.includes(g) || (g === "a" && vis.a) || (g === "b" && vis.bb) || (g === "stick" && vis.stick)); }
      $("#gpname").textContent = "Connected: " + (vis.p.id.replace(/\s*\(.*$/, "") || "controller");
      $("#gphelp").hidden = true;
    }
  }
  GP.raf = requestAnimationFrame(padPoll);
}
if (!AVAIL.gamepad) {
  addEventListener("gamepadconnected", (e) => {
    GP.count++;
    if (cfg.mode !== "gamepad") { setMode("gamepad"); toast("Controller connected — switched to Game controller"); } else padStart();
    $("#gpname").textContent = "Connected: " + (e.gamepad.id.replace(/\s*\(.*$/, "") || "controller");
  });
  addEventListener("gamepaddisconnected", (e) => {
    GP.count = Math.max(0, GP.count - 1); unhold("gp" + e.gamepad.index); GP.prev.delete(e.gamepad.index);
    toast("Controller disconnected"); if (!GP.count) { $("#gpname").textContent = "No controller yet"; $("#gphelp").hidden = false; }
  });
}

/* ---------- tilt ---------- */
const TL = { on: false, zero: null, a: 0, t: 0, got: false, raf: 0, dir: null };
const tiltRate = analog(() => TL.t);
function tmsg(s) { $("#tmsg").textContent = s; }
async function tiltStart() {
  if (AVAIL.tilt) { tmsg(why("tilt")); return; }
  try {
    if (typeof DeviceOrientationEvent.requestPermission === "function") { // iOS asks the player once
      const r = await DeviceOrientationEvent.requestPermission();
      if (r !== "granted") { tmsg("Motion access was declined. Allow Motion & Orientation for this site in Safari settings, or pick another controller."); return; }
    }
  } catch (err) { tmsg("Couldn't start the tilt sensor: " + (err && err.message ? err.message : err)); return; }
  if (!TL.on) { addEventListener("deviceorientation", onTilt); TL.on = true; }
  TL.zero = null; TL.got = false;
  $("#tstart").textContent = "Re-centre"; $("#tstart").classList.remove("hot");
  tmsg("Centre set. Tilt left or right to steer.");
  setTimeout(() => { if (!TL.got) tmsg("No readings from a tilt sensor — this device may not have one."); }, 1500);
}
function steerAngle(e) {
  const ang = screen.orientation && typeof screen.orientation.angle === "number" ? screen.orientation.angle : Number(window.orientation) || 0;
  const b = e.beta || 0, g = e.gamma || 0;
  switch (((ang % 360) + 360) % 360) { case 90: return b; case 270: return -b; case 180: return -g; default: return g; }
}
function onTilt(e) {
  if (e.gamma == null && e.beta == null) return;
  TL.got = true;
  if (cfg.mode !== "tilt" || S.screen !== "play") return;
  const raw = steerAngle(e);
  if (TL.zero === null) TL.zero = raw;
  let a = raw - TL.zero;
  if (a > 180) a -= 360; if (a < -180) a += 360;
  const max = { low: 34, medium: 24, high: 15 }[cfg.tilt], v = clamp(a / max, -1, 1), m = Math.abs(v), dz = 0.22;
  if (m < dz) { TL.t = 0; if (TL.dir) { unhold("tilt"); TL.dir = null; } }
  else { TL.t = (m - dz) / (1 - dz); TL.dir = v < 0 ? "left" : "right"; hold("tilt", [TL.dir], tiltRate); }
  TL.a = v;
  if (!TL.raf) TL.raf = requestAnimationFrame(() => { // paint at most once per frame, never in the input path
    TL.raf = 0;
    $("#wheel").style.transform = `rotate(${TL.a * 60}deg)`; $("#wheel").classList.toggle("go", !!TL.dir);
    $("#tknob").style.left = `${50 + TL.a * 46}%`;
  });
}
$("#tstart").addEventListener("click", tiltStart);
resets.push(() => { if (TL.dir) { TL.dir = null; TL.t = 0; } });

/* ============================== colour, layout ============================== */
function setColor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return;
  const n = parseInt(m[1], 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255, s = app.style;
  s.setProperty("--c", "#" + m[1]);
  for (const [k, a] of [["10", 0.1], ["20", 0.2], ["35", 0.35], ["55", 0.55]]) s.setProperty("--ca" + k, `rgba(${r},${g},${b},${a})`);
}
function layout() {
  const w = innerWidth, h = innerHeight, land = w > h * 1.05;
  app.classList.toggle("land", land);
  const sc = { S: 0.84, M: 1, L: 1.2 }[cfg.size] || 1;
  const head = land ? 72 : 128;
  const fit = land ? Math.min((h - head - 20) / 3.6, (w - 60) / 8.6) : Math.min((w - 26) / (cfg.size === "L" ? 6 : 6.4), (h - head - 190) / 3.8);
  const u = Math.round(clamp(Math.min(fit, 66 * sc), 42, 110));
  app.style.setProperty("--u", u + "px");
  stick.apply();
}
addEventListener("resize", layout);
addEventListener("orientationchange", () => setTimeout(layout, 60));

let wl = null;
async function wakeOn() {
  if (!cfg.awake || wl || !("wakeLock" in navigator) || document.visibilityState !== "visible") return;
  try { wl = await navigator.wakeLock.request("screen"); wl.addEventListener("release", () => { wl = null; }); } catch (_) {}
}
function wakeOff() { if (wl) { wl.release().catch(() => {}); wl = null; } }
document.addEventListener("pointerdown", wakeOn, { capture: true, passive: true });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") { wakeOn(); if (!ended && (!ws || ws.readyState > 1)) { clearTimeout(retryT); connect(); } }
  else releaseAll();
});
addEventListener("blur", releaseAll);
// iOS Safari / Android Chrome restore pages from the back-forward cache with their socket closed: reconnect
addEventListener("pageshow", (e) => { if (e.persisted && !ended && (!ws || ws.readyState > 1)) { clearTimeout(retryT); connect(); } });

let toastT = 0;
function toast(s) { const t = $("#toast"); t.textContent = s; t.hidden = false; t.style.animation = "none"; void t.offsetWidth; t.style.animation = ""; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 2600); }

function renderLay() { // the layouts that suit this game, one tap away; everything else is behind the gear
  const ids = [...controls.filter(usable)];
  if (!ids.includes(cfg.mode)) ids.push(cfg.mode);
  const show = ids.slice(0, innerWidth < 380 ? 3 : 4);
  if (!show.includes(cfg.mode)) show[show.length - 1] = cfg.mode;
  $("#lay").innerHTML = show.map((m) => `<button role="radio" aria-checked="${m === cfg.mode}" aria-label="${MODES[m].name}" title="${MODES[m].name}" data-mode="${m}">${ICON[m]}</button>`).join("");
}
$("#lay").addEventListener("click", (e) => { const b = e.target.closest("[data-mode]"); if (b) { setMode(b.dataset.mode); buzz(10); toast(MODES[b.dataset.mode].name); } });

function applyCfg() {
  for (const sec of $$(".mode")) sec.hidden = sec.dataset.m !== cfg.mode;
  app.dataset.mode = cfg.mode;
  app.classList.toggle("lefty", cfg.lefty);
  $("#strip").hidden = !cfg.strip;
  for (const el of $$(".mhint")) el.textContent = MODES[cfg.mode].hint;
  renderLay();
  layout();
  if (cfg.awake) wakeOn(); else wakeOff();
  padStart();
}
function setMode(m) { if (!usable(m) || m === cfg.mode) return; releaseAll(); cfg.mode = m; saveCfg(); applyCfg(); }

/* ============================== settings sheet ============================== */
function renderSheet() {
  const order = [...controls.filter((m) => MODES[m]), ...MODE_IDS.filter((m) => !controls.includes(m))].sort((x, y) => usable(y) - usable(x)); // unavailable last
  const modes = order.map((m) => {
    const M = MODES[m], dis = !usable(m), sel = cfg.mode === m;
    const badge = controls[0] === m ? '<span class="tag rec">Recommended</span>' : controls.includes(m) ? '<span class="tag">Suits this game</span>' : "";
    return `<button class="mcard${sel ? " sel" : ""}" role="radio" aria-checked="${sel}"${dis ? ' aria-disabled="true"' : ""} data-mode="${m}">
      <span class="mi" aria-hidden="true">${ICON[m]}</span>
      <span class="mt"><span class="mn">${M.name}${badge}</span><span class="md">${M.desc}</span>${dis ? `<span class="why">${LOCK}<span>${why(m)}</span></span>` : ""}</span>
      <span class="mc" aria-hidden="true">${sel ? CHECK : ""}</span></button>`;
  }).join("");
  const opt = (o) => {
    const v = cfg[o.k], na = o.na || "";
    if (o.sw) return `<button class="row" role="switch" aria-checked="${!!v && !na}" data-opt="${o.k}"${na ? ' aria-disabled="true"' : ""}>
      <span class="rt"><span class="rn">${o.t}</span>${na || o.d ? `<span class="rd">${na || o.d}</span>` : ""}</span><span class="tg" aria-hidden="true"><i></i></span></button>`;
    return `<div class="row"><span class="rt"><span class="rn" id="l-${o.k}">${o.t}</span>${o.d ? `<span class="rd">${o.d}</span>` : ""}</span>
      <div class="seg" role="radiogroup" aria-labelledby="l-${o.k}">${o.seg.map(([val, lab]) => `<button role="radio" aria-checked="${String(v) === String(val)}" data-opt="${o.k}" data-val="${val}">${lab}</button>`).join("")}</div></div>`;
  };
  const spec = OPTS.filter((o) => o.modes && o.modes.includes(cfg.mode)).map(opt).join("");
  const recentre = cfg.mode === "tilt" && TL.on ? `<div class="row"><span class="rt"><span class="rn">Centre</span><span class="rd">Use how you're holding the phone now</span></span><button class="act" data-act="recentre">Re-centre</button></div>` : "";
  $("#shbody").innerHTML = `<div class="eng shsec">Controller</div><div class="modes" role="radiogroup" aria-label="Controller type">${modes}</div>
    ${spec || recentre ? `<div class="eng shsec">${MODES[cfg.mode].name}</div>${spec}${recentre}` : ""}
    <div class="eng shsec">Comfort</div>${OPTS.filter((o) => !o.modes).map(opt).join("")}
    <div class="eng shsec">Player</div><div class="row"><span class="rt"><span class="rn">Character</span><span class="rd">Name, colour, look and side</span></span><button class="act" data-act="char">Edit</button></div>`;
}
$("#shbody").addEventListener("click", (e) => {
  const mb = e.target.closest(".mcard");
  if (mb) { if (mb.getAttribute("aria-disabled") !== "true") { setMode(mb.dataset.mode); renderSheet(); } return; }
  if (e.target.closest('[data-act="recentre"]')) { TL.zero = null; toast("Centre set"); return; }
  if (e.target.closest('[data-act="char"]')) { closeSheet(); editChar(); return; }
  const ob = e.target.closest("[data-opt]");
  if (!ob || ob.getAttribute("aria-disabled") === "true") return;
  const k = ob.dataset.opt;
  if (OPT[k].sw) cfg[k] = !cfg[k]; else cfg[k] = typeof DEF[k] === "number" ? Number(ob.dataset.val) : ob.dataset.val;
  if (k === "haptics" && cfg.haptics) buzz(20);
  saveCfg(); applyCfg(); renderSheet();
});
function openSheet() { releaseAll(); renderSheet(); $("#scrim").hidden = false; $("#sheet").hidden = false; $("#done").focus(); }
function closeSheet() { $("#scrim").hidden = true; $("#sheet").hidden = true; }
$("#gear").addEventListener("click", openSheet);
$("#done").addEventListener("click", closeSheet);
$("#scrim").addEventListener("click", closeSheet);

/* ============================== character select ============================== */
let profT = 0, profQ = {};
function sendProfile(p, now_ = false) { // name typing is throttled (it's not gameplay); picks go out at once
  Object.assign(profQ, p);
  const flush = () => { profT = 0; if (ws && ws.readyState === 1 && Object.keys(profQ).length) ws.send(JSON.stringify({ type: "profile", ...profQ })); profQ = {}; };
  clearTimeout(profT);
  if (now_) flush(); else profT = setTimeout(flush, 180);
  remember();
}
function remember() { store("deskdot.profile", { name: S.me.name, color: S.me.color, avatar: S.me.avatar, team: S.me.team }); }
function taken() { // colours other seats show on the panel: the host, other phones, and empty seats' AI defaults
  const t = new Set();
  const seated = new Set(S.roster.map((p) => p.seat));
  for (const p of S.roster) if (p.seat !== S.seat) t.add(p.color);
  for (let n = 1; n <= S.maxPlayers; n++) if (n !== S.seat && !seated.has(n) && SEATS[n]) t.add(SEATS[n]);
  return t;
}
const hasTeams = () => S.modes.some((m) => m.teams === "versus");
function paintMe() { // everything that shows my look
  setColor(S.me.color);
  for (const cv of $$("#pv, #pv2, .meb .av, .info .av")) drawAvatar(cv, S.me.avatar, S.me.color);
  $("#p-name").textContent = S.me.name || "P" + S.seat;
}
function renderChar() {
  const nm = $("#name");
  if (document.activeElement !== nm) nm.value = S.me.name;
  $("#name-c").textContent = `${nm.value.length}/10`;
  $("#char-k").textContent = `Player ${S.seat} · ${S.game}`;
  const avs = $("#avs");
  if (avs.childElementCount !== S.avatarIds.length) {
    avs.innerHTML = "";
    for (const id of S.avatarIds) {
      const b = document.createElement("button");
      b.className = "tile"; b.setAttribute("role", "radio"); b.dataset.av = id; b.setAttribute("aria-label", S.avatars[id].name);
      const cv = document.createElement("canvas"); cv.className = "av"; cv.dataset.s = "40";
      const l = document.createElement("span"); l.textContent = S.avatars[id].name;
      b.append(cv, l); avs.appendChild(b);
    }
  }
  for (const b of $$(".tile", avs)) { b.setAttribute("aria-checked", String(b.dataset.av === S.me.avatar)); drawAvatar($("canvas", b), b.dataset.av, S.me.color); }
  const cols = $("#cols"), tk = taken();
  if (cols.childElementCount !== S.palette.length) {
    cols.innerHTML = "";
    for (const p of S.palette) {
      const b = document.createElement("button");
      b.className = "chip-c"; b.setAttribute("role", "radio"); b.dataset.col = p.color; b.style.setProperty("--sc", p.color); b.setAttribute("aria-label", p.name);
      cols.appendChild(b);
    }
  }
  for (const b of $$(".chip-c", cols)) {
    const c = b.dataset.col, mine = c === S.me.color, off = tk.has(c) && !mine;
    b.setAttribute("aria-checked", String(mine)); b.setAttribute("aria-disabled", String(off));
    b.title = off ? "Taken by another player" : "";
  }
  $("#team-p").hidden = !hasTeams();
  for (const b of $$("#teams button")) b.setAttribute("aria-checked", String(b.dataset.team === (S.me.team === null ? "auto" : String(S.me.team))));
  $("#ready").textContent = S.fromPlay ? "Back to the game" : "Ready";
  renderLobby($("#lob1"));
  paintMe();
  liveBanner();
}
function renderReady() {
  $("#rdy-t").textContent = "Ready!";
  const st = S.status;
  $("#rdy-p").textContent = st.lobby ? "Waiting for the host to start…" : st.flow && st.flow !== "attract" ? "The game is on — open your controller." : "Waiting for the host — press Controller to play now.";
  renderLobby($("#lob2"));
  paintMe();
}
function renderLobby(box) {
  box.innerHTML = "";
  const seated = new Map(S.roster.map((p) => [p.seat, p]));
  for (let n = 1; n <= Math.max(S.maxPlayers, ...S.roster.map((p) => p.seat)); n++) {
    const p = seated.get(n), row = document.createElement("div");
    row.className = "pl" + (n === S.seat ? " me" : "") + (p ? "" : " empty");
    const color = p ? p.color : SEATS[n] || "#888";
    row.style.setProperty("--pc", p ? color : "transparent");
    const cv = document.createElement("canvas"); cv.className = "av"; cv.dataset.s = "36";
    const nm = document.createElement("div"); nm.className = "nm";
    const b = document.createElement("b"), sm = document.createElement("small");
    const st = document.createElement("span"); st.className = "st";
    if (!p) { b.textContent = "Open seat"; sm.textContent = `P${n} · AI plays`; st.textContent = "—"; }
    else if (p.host) { b.textContent = "Host"; sm.textContent = "P1 · keyboard"; st.className = "st host"; st.textContent = "Host"; }
    else {
      b.textContent = p.name + (n === S.seat ? " (you)" : "");
      const team = p.team === 0 ? " · Team A" : p.team === 1 ? " · Team B" : "";
      sm.textContent = `P${n}${team}`;
      st.className = "st" + (p.ready ? " ok" : ""); st.textContent = p.ready ? "Ready" : "Picking";
    }
    nm.append(b, sm); row.append(cv, nm, st); box.appendChild(row);
    if (p && !p.host && p.avatar) drawAvatar(cv, p.avatar, color);
    else if (p && p.host) { cv.style.background = "#050507"; const g = cv.getContext("2d"); cv.width = cv.height = 72; g.fillStyle = color; g.beginPath(); g.arc(36, 36, 14, 0, 7); g.fill(); }
  }
}
function liveBanner() { const st = S.status; $("#char-live").hidden = !(S.screen === "char" && !S.fromPlay && st.flow && st.flow !== "attract" && !st.lobby); }
$("#char-live").addEventListener("click", () => { S.me.ready = true; sendProfile({ ready: true }, true); go("play"); });

$("#name").addEventListener("input", (e) => {
  const v = cleanName(e.target.value);
  if (v !== e.target.value) e.target.value = v;
  $("#name-c").textContent = `${v.length}/10`;
  S.me.name = v.trim() || "P" + S.seat;
  paintMe();
  sendProfile({ name: S.me.name });
});
$("#name").addEventListener("change", () => sendProfile({ name: S.me.name }, true));
$("#name").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
$("#avs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-av]"); if (!b) return;
  S.me.avatar = b.dataset.av; buzz(10); sendProfile({ avatar: S.me.avatar }, true); renderChar();
});
$("#cols").addEventListener("click", (e) => {
  const b = e.target.closest("[data-col]"); if (!b) return;
  if (b.getAttribute("aria-disabled") === "true") { toast("That colour belongs to another player"); buzz(30); return; }
  S.pendingColor = b.dataset.col; S.me.color = b.dataset.col; buzz(10); sendProfile({ color: S.me.color }, true); renderChar();
});
$("#teams").addEventListener("click", (e) => {
  const b = e.target.closest("[data-team]"); if (!b) return;
  S.me.team = b.dataset.team === "auto" ? null : Number(b.dataset.team); buzz(10); sendProfile({ team: S.me.team }, true); renderChar();
});
$("#ready").addEventListener("click", () => {
  sendProfile({ name: S.me.name }, true);
  if (S.fromPlay) { S.fromPlay = false; go("play"); return; }
  S.me.ready = true; sendProfile({ ready: true }, true); buzz([20, 40, 30]);
  go("ready");
  if (!S.status.lobby) setTimeout(() => { if (S.screen === "ready") go("play"); }, 900); // nobody else to wait for
});
$("#unready").addEventListener("click", () => { S.me.ready = false; sendProfile({ ready: false }, true); go("char"); });
$("#toplay").addEventListener("click", () => go("play"));
$("#mebtn").addEventListener("click", editChar);
function editChar() { S.fromPlay = true; go("char"); }
$("#seat-next").addEventListener("click", () => go("char"));

/* ============================== in-game status ============================== */
let lastTurnMine = false, lastFlow = "", lastLobby = null;
function setStatus(parts, mine) {
  const st = $("#status");
  const key = JSON.stringify([parts, mine]);
  if (st.dataset.k === key) return;
  st.dataset.k = key; st.innerHTML = "";
  parts.forEach((p, i) => { const s = document.createElement("span"); s.textContent = p; if (mine && i === 0) s.className = "pill"; st.appendChild(s); });
}
function paintAll() { onState(S.status, true); paintMe(); }
function onState(s, force) {
  S.status = s;
  const parts = [];
  let mine = false;
  const flow = s.flow || "";
  const r = s.roster && s.roster[String(S.seat)];
  if (s.lobby) parts.push("Waiting for players…");
  else if (flow === "home") parts.push("Host is picking the mode");
  else if (flow === "teams") { parts.push(r && r.ready ? "Ready — waiting for the others" : "Pick a side ◀ ▶ · A = ready"); mine = !!(r && !r.ready); }
  else if (flow === "intro") parts.push("Get ready…");
  else if (flow === "outro") parts.push("A = rematch");
  if (s.rps) { const r = rpsParts(s); parts.length = 0; parts.push(...r.parts); mine = r.mine; }
  if (typeof s.turn === "number" && s.turn > 0) {
    mine = s.turn === S.seat;
    parts.unshift(mine ? "Your turn" : `Player ${s.turn}'s turn`);
  } else if (!s.rps && typeof s.score === "number" && (flow === "play" || flow === "attract") && !s.lobby) parts.push(`Score ${s.score}`);
  if (mine && !lastTurnMine && s.turn === S.seat) buzz([30, 50, 30]);
  lastTurnMine = mine && s.turn === S.seat;
  if (S.screen === "play" || force) {
    setStatus(parts.length ? parts : ["Watch the panel"], mine);
    for (const el of $$(".info")) el.classList.toggle("turn", lastTurnMine);
    if (Array.isArray(s.seats)) {
      const sig = JSON.stringify(s.seats);
      for (const el of $$(".lineup")) {
        if (el.dataset.sig === sig) continue;
        el.dataset.sig = sig; el.innerHTML = "";
        for (const x of s.seats) {
          const me = x.seat === S.seat, chip = document.createElement("span"), col = x.color || SEATS[x.seat] || "#888";
          chip.className = "chip" + (me ? " me" : ""); chip.style.setProperty("--cc", col);
          if (x.avatar && S.avatars[x.avatar]) { const cv = document.createElement("canvas"); cv.className = "av"; cv.dataset.s = "20"; chip.appendChild(cv); drawAvatar(cv, x.avatar, col, false); }
          else chip.appendChild(document.createElement("i"));
          chip.appendChild(document.createTextNode(me ? "You" : x.seat === 1 ? "Host" : x.human ? x.name : "AI"));
          el.appendChild(chip);
        }
      }
    }
  }
  // the host started (or the game was already full): the ready screen hands over to the controller
  if (S.screen === "ready" && lastLobby === true && !s.lobby) { toast("Game on!"); buzz([20, 30, 20]); go("play"); }
  if (S.screen === "ready" && (flow !== lastFlow || s.lobby !== lastLobby)) renderReady();
  if (S.screen === "char") liveBanner();
  if (s.rps) renderRps(s);
  lastFlow = flow; lastLobby = !!s.lobby;
}

/* ============================== rock paper scissors ============================== */
// The hand picker (controller "rps"). Picks go out as ordinary keys: left = rock, up = paper, right = scissors,
// down = let the engine pick at random. The engine sends its own pixel-art hands (status.rps.art), so the buttons
// show exactly what the panel shows. Picks are secret: the status only says who has locked in until the reveal.
const RPS_DIGIT = { "1": "left", "2": "up", "3": "right", r: "left", p: "up", s: "right" };
const RPS_MOVE = { left: "rock", up: "paper", right: "scissors" };
const R = { pick: null, art: null, btnSig: "", key: "", showSig: "" }; // pick = {key: "match:round", mv}
const esc = (t) => String(t).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
function lighten(hex, k) {
  const n = parseInt(hex.slice(1), 16), f = (v) => Math.round(v + (255 - v) * k).toString(16).padStart(2, "0");
  return "#" + f(n >> 16) + f((n >> 8) & 255) + f(n & 255);
}
function drawHand(cv, mv, color, flip) { // LED dots on a 16 × 16 grid, like the panel
  const rows = R.art && R.art[mv], W = 160;
  if (cv.width !== W) { cv.width = W; cv.height = W; }
  const g = cv.getContext("2d");
  g.clearRect(0, 0, W, W);
  if (!rows || !/^#[0-9a-f]{6}$/i.test(color || "")) return;
  const n = 16, cell = W / n, h = rows.length, w = Math.max(...rows.map((r) => r.length));
  const ox = Math.floor((n - w) / 2), oy = Math.floor((n - h) / 2), glove = lighten(color, 0.35);
  const pal = { c: color, h: glove, l: lighten(color, 0.72), s: shade(glove, 0.5) };
  for (let y = 0; y < h; y++) for (let x = 0; x < rows[y].length; x++) {
    const fill = pal[rows[y][x]];
    if (!fill) continue;
    g.fillStyle = fill; g.beginPath();
    g.arc((ox + (flip ? w - 1 - x : x) + 0.5) * cell, (oy + y + 0.5) * cell, cell * 0.46, 0, Math.PI * 2); g.fill();
  }
}
function rpsWho(r, seat) { return (r.players && r.players[String(seat)]) || { name: "P" + seat, color: SEATS[seat] || "#888888", human: false }; }
function rpsName(r, seat) { return seat === S.seat ? "You" : rpsWho(r, seat).name; }
function rpsCtx(s) {
  const r = s.rps, pair = r.pair || [], me = S.seat;
  const inMatch = pair.includes(me) && !!rpsWho(r, me).human && r.kind !== "attract";
  const key = r.match + ":" + r.round;
  const mine = R.pick && R.pick.key === key ? R.pick : null; // tapped this round (the status may lag a moment)
  return { r, pair, inMatch, opp: inMatch ? pair.find((x) => x !== me) : null, key, mine,
    locked: (r.locked || []).includes(me) || (!!mine && r.phase === "pick") };
}
function knockedOut(r) {
  const t = r.tour;
  return !!t && t.format === "knockout" && t.rounds.some((rd) => rd.some(([a, b, w]) => w != null && (a === S.seat || b === S.seat) && w !== S.seat));
}
function rpsParts(s) {
  const flow = s.flow || "", c = rpsCtx(s), r = c.r;
  if (s.lobby) return { parts: ["Waiting for players…"], mine: false };
  if (flow === "home") return { parts: ["Host is picking the mode"], mine: false };
  if (flow === "intro") return { parts: ["Get ready…"], mine: false };
  if (flow === "outro") return { parts: [r.champion === S.seat ? "You won!" : "Match over", "A = rematch"], mine: false };
  if (r.kind === "attract") return { parts: ["Demo — the host starts a game"], mine: false };
  if (!c.inMatch) return { parts: [`Watching ${rpsName(r, c.pair[0])} vs ${rpsName(r, c.pair[1])}`], mine: false };
  if (r.phase === "pick") return { parts: [c.locked ? "Locked in" : "Your pick!"], mine: !c.locked };
  return { parts: [`vs ${rpsName(r, c.opp)}`], mine: false };
}
function rpsSide(el, r, seat, s) {
  if (seat == null) return;
  const who = rpsWho(r, seat), col = seat === S.seat ? S.me.color : who.color || "#888888";
  el.style.setProperty("--pc", col);
  $("b", el).textContent = rpsName(r, seat);
  const pips = $(".pips", el), n = r.first_to || 1, w = (r.wins || {})[String(seat)] || 0, sig = `${n}:${w}`;
  if (pips.dataset.sig !== sig) { pips.dataset.sig = sig; pips.innerHTML = Array.from({ length: n }, (_, i) => `<i${i < w ? ' class="on"' : ""}></i>`).join(""); }
  const info = (s.seats || []).find((x) => x.seat === seat);
  const av = seat === S.seat ? S.me.avatar : (who.human && info && info.avatar) || (seat === 1 && who.human ? "knight" : "bot");
  const cv = $("canvas", el), asig = av + col;
  if (cv.dataset.sig !== asig) { cv.dataset.sig = asig; drawAvatar(cv, av, col, false); }
}
function rpsBoard(el, r) {
  const t = r.tour;
  if (!t) { el.innerHTML = ""; return; }
  const sig = JSON.stringify([t, r.pair, S.seat, r.players]);
  if (el.dataset.sig === sig) return;
  el.dataset.sig = sig;
  const cur = (a, b) => r.pair && r.pair.includes(a) && r.pair.includes(b);
  const P = (seat, cls) => { const w = rpsWho(r, seat); return `<span class="p ${cls || ""}" style="--pc:${esc(w.color)}"><i></i>${esc(rpsName(r, seat))}</span>`; };
  const row = (a, b, w) => `<div class="bm${w == null && cur(a, b) ? " cur" : ""}${a === S.seat || b === S.seat ? " me" : ""}">${P(a, w == null ? "" : w === a ? "w" : "l")}<span class="v">vs</span>${P(b, w == null ? "" : w === b ? "w" : "l")}</div>`;
  let h = "";
  if (t.format === "robin") {
    h += "<h4>Standings</h4>";
    t.table.forEach((x, i) => { h += `<div class="bm${x.seat === S.seat ? " me" : ""}"><span class="v">${i + 1}</span>${P(x.seat)}<span class="n">${x.wins} W · ${x.played} P</span></div>`; });
    h += "<h4>Matches</h4>";
    for (const [a, b, w] of t.games) h += row(a, b, w);
  } else {
    const title = (i, n) => (n === 1 ? "Final" : n === 2 ? "Semi-finals" : n === 4 ? "Quarter-finals" : "Round " + (i + 1));
    t.rounds.forEach((rd, i) => {
      h += `<h4>${title(i, rd.length)}</h4>`;
      for (const [a, b, w] of rd) h += b == null ? `<div class="bm">${P(a, "w")}<span class="v">bye</span></div>` : row(a, b, w);
    });
  }
  el.innerHTML = h;
}
function rpsButtons() { // the three hands, in my colour
  const sig = S.me.color + (R.art ? "1" : "0");
  if (sig === R.btnSig) return;
  R.btnSig = sig;
  for (const b of $$(".rps-b")) drawHand($("canvas", b), b.dataset.mv, S.me.color, false);
}
function renderRps(s) {
  const c = rpsCtx(s), r = c.r, ph = r.phase, flow = s.flow || "";
  if (r.art && !R.art) R.art = r.art;
  rpsButtons();
  if (!R.howto && (S.rulebook || {}).rps && !store("deskdot.howto.rps")) { R.howto = true; openRulebook("rps", "how", true); } // once per phone
  if (R.pick && R.pick.key !== c.key) R.pick = null;
  if (c.key !== R.key) { R.key = c.key; if (c.inMatch && ph === "pick" && flow === "play" && !c.locked) buzz([30, 50, 30]); }
  const L = c.inMatch ? S.seat : c.pair[0], RR = c.inMatch ? c.opp : c.pair[1];
  rpsSide($(".rps-side.me"), r, L, s);
  rpsSide($(".rps-side.them"), r, RR, s);
  $("#rps-round").textContent = r.round ? "R" + r.round : "";
  const oppName = c.opp ? rpsName(r, c.opp) : "";
  let text = "Watch the panel", hot = false, view = "picks";
  if (s.lobby) text = "Waiting for players to join…";
  else if (flow === "home") text = "The host is picking a mode";
  else if (flow === "intro") text = c.inMatch ? `You vs ${oppName} — get ready!` : r.tour ? "The tournament is starting" : "Get ready…";
  else if (flow === "outro") {
    const ch = r.champion;
    text = ch === S.seat ? (r.tour ? "You're the champion!" : "You win the match!") : ch ? `${rpsName(r, ch)} ${r.tour ? "is the champion" : "wins the match"}` : "Match over";
    hot = ch === S.seat; view = r.tour ? "board" : "show";
  } else if (r.kind === "attract") text = "Demo match — the host starts a game";
  else if (!c.inMatch) {
    view = r.tour && (ph === "bracket" || ph === "vs") ? "board" : "show";
    text = `${ph === "bracket" || ph === "vs" ? "Next up" : "Watching"}: ${rpsName(r, c.pair[0])} vs ${rpsName(r, c.pair[1])}`;
    if (knockedOut(r)) text = "You're out — " + text;
  } else if (ph === "bracket") { view = "board"; text = `Next up: you vs ${oppName}`; hot = true; }
  else if (ph === "vs") text = `You vs ${oppName}`;
  else if (ph === "pick") {
    if (!c.locked) { text = "Pick your hand!"; hot = true; }
    else text = (r.locked || []).length >= 2 ? "Both locked in…" : `Locked in — waiting for ${oppName}`;
  } else if (ph === "pump") { view = "show"; text = "Rock… Paper… Scissors…"; }
  else if (ph === "reveal") {
    view = "show"; const w = r.winner;
    text = !r.picks ? "Shoot!" : w === 0 ? "Draw — go again!" : w === S.seat ? "You win the round!" : `${oppName} wins the round`;
    hot = w === S.seat;
  } else if (ph === "champ") {
    view = "show"; const ch = r.champion;
    text = ch === S.seat ? "You win the match!" : `${rpsName(r, ch)} wins the match`; hot = ch === S.seat;
  }
  const msg = $("#rps-msg");
  if (msg.textContent !== text) msg.textContent = text;
  msg.classList.toggle("hot", hot);
  const canPick = flow === "play" && c.inMatch && ph === "pick" && !c.locked;
  const timer = $("#rps-timer");
  timer.hidden = !(canPick && r.timer);
  if (!timer.hidden) {
    const k = clamp((r.left || 0) / r.timer, 0, 1);
    $("i", timer).style.width = Math.round(k * 100) + "%";
    timer.classList.toggle("warn", k <= 0.5 && k > 0.25); timer.classList.toggle("bad", k <= 0.25);
  }
  const picks = $("#rps-picks"), show = $("#rps-show"), board = $("#rps-board");
  picks.hidden = view !== "picks"; show.hidden = view !== "show"; board.hidden = view !== "board";
  $("#rps-rand").hidden = view !== "picks" || !canPick;
  picks.classList.toggle("wait", !canPick && !c.locked);
  picks.classList.toggle("done", c.locked);
  const mv = c.mine ? c.mine.mv : null;
  for (const b of $$(".rps-b", picks)) { b.classList.toggle("sel", !!mv && c.locked && b.dataset.mv === mv); b.setAttribute("aria-disabled", String(!canPick)); }
  if (view === "show") {
    const shown = r.picks && (ph === "reveal" || ph === "champ" || flow === "outro");
    const ml = shown ? r.picks[String(L)] : "rock", mr = shown ? r.picks[String(RR)] : "rock"; // the pump: two fists
    const cl = L === S.seat ? S.me.color : rpsWho(r, L).color, cr = rpsWho(r, RR).color, w = shown ? r.winner : null;
    show.classList.toggle("pump", ph === "pump");
    const sig = [ml, mr, cl, cr, w, ph].join();
    if (sig !== R.showSig) {
      R.showSig = sig;
      drawHand($("#rps-mine"), ml, cl, false);
      drawHand($("#rps-theirs"), mr, cr, true);
      $("#rps-mine").classList.toggle("lose", !!w && w !== L);
      $("#rps-theirs").classList.toggle("lose", !!w && w !== RR);
      $("#rps-res").textContent = ph === "pump" ? "VS" : w === 0 ? "DRAW" : w === L ? "◀ WIN" : w ? "WIN ▶" : "VS";
    }
  } else R.showSig = "";
  if (view === "board") rpsBoard(board, r);
}
function rpsPick(k) {
  const s = S.status, c = s.rps ? rpsCtx(s) : null;
  if (!c || !c.inMatch || c.r.phase !== "pick" || c.locked || (s.flow || "") !== "play") { buzz(30); return; }
  press(k); // instant: the panel locks this hand on the next frame
  R.pick = { key: c.key, mv: RPS_MOVE[k] || null }; // "down" = the engine picks at random; we find out at the reveal
  renderRps(s);
}
for (const b of $$(".rps-b")) {
  b.addEventListener("pointerdown", (e) => { e.preventDefault(); flash(b); rpsPick(b.dataset.k); });
}
$("#rps-rand").addEventListener("click", () => rpsPick("down"));
$("#rps-help").addEventListener("click", () => openRulebook("rps", "how"));

/* ------------------------------------------------ how to play / rulebook (casino/rulebook.py, from hello.rulebook) */
const mdb = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
function openRulebook(id, tab, first) {
  const g = (S.rulebook || {})[id];
  if (!g) return;
  document.querySelector(".rbk")?.remove();
  const el = document.createElement("div"); el.className = "rbk"; el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-label", g.title + " rules");
  const draw = (t) => {
    const body = t === "how"
      ? `<p class="tg">${mdb(g.tagline)}</p><ol>${g.how.map((s) => `<li>${mdb(s)}</li>`).join("")}</ol>`
      : g.rules.map((r) => `<h3>${esc(r.h)}</h3><ul>${r.items.map((i) => `<li>${mdb(i)}</li>`).join("")}</ul>`).join("");
    el.innerHTML = `<div class="in"><div class="sh-head"><h2>${first ? "How to play" : esc(g.title)}</h2><button class="done" data-x>${first ? "Got it" : "Done"}</button></div>
      <div class="tabs" role="tablist">${[["how", "How to play"], ["rules", "Rulebook"]].map(([k, l]) => `<button role="tab" data-t="${k}" aria-selected="${k === t}">${l}</button>`).join("")}</div>
      <div class="bd">${body}</div></div>`;
  };
  draw(tab);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-t]");
    if (b) { draw(b.dataset.t); buzz(6); return; }
    if (e.target === el || e.target.closest("[data-x]")) { store("deskdot.howto." + id, 1); el.remove(); }
  });
  document.body.append(el);
}

/* ============================== page hygiene ============================== */
// no zoom, no scroll/bounce, no long-press menus; control surfaces never generate click/mouse emulation
document.addEventListener("touchstart", (e) => { if (e.target.closest("[data-surface]") && !e.target.closest("[data-click]")) e.preventDefault(); }, { passive: false });
document.addEventListener("touchmove", (e) => { if (!e.target.closest(".sh-body, .scroll")) e.preventDefault(); }, { passive: false });
document.addEventListener("contextmenu", (e) => { if (!(e.target && e.target.tagName === "INPUT")) e.preventDefault(); });
document.addEventListener("dblclick", (e) => e.preventDefault());
document.addEventListener("gesturestart", (e) => e.preventDefault());

/* ============================== network ============================== */
let ended = false, backoff = 300, retryT = 0, lastMsg = 0, everConnected = false;
const LAT = [];
function net(state, ms) {
  for (const el of $$("[data-net]")) {
    el.classList.toggle("off", state !== "ok");
    const q = ms == null ? "" : ms < 60 ? "#50ff78" : ms < 120 ? "#ffb21a" : "#ff3c5a";
    el.style.setProperty("--q", q || (state === "ok" ? "#50ff78" : ""));
    $("span", el).textContent = state === "ok" ? (ms == null ? "online" : `${ms} ms`) : state === "wait" ? "connecting" : "offline";
    el.title = state === "ok" ? "Connected · round trip to the panel's computer" : "Not connected — reconnecting";
  }
  app.classList.toggle("offline", state !== "ok" && everConnected);
  $("#recon").hidden = state === "ok" || !everConnected || ended;
}
function onPong(t) {
  const ms = now() - Number(t);
  if (!(ms >= 0 && ms < 10000)) return;
  LAT.push(ms); if (LAT.length > 7) LAT.shift();
  const s = [...LAT].sort((a, b) => a - b);
  net("ok", Math.round(s[s.length >> 1]));
}
function end(title, text, label) {
  ended = true; releaseAll(); clearTimeout(retryT);
  $("#end-t").textContent = title; $("#end-p").textContent = text; $("#end-b").textContent = label; $("#end").hidden = false; $("#recon").hidden = true;
}
$("#end-b").addEventListener("click", () => location.reload());
function ping() { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "ping", t: now() })); }

function onHello(m) {
  const prevSeat = S.seat, firstHello = !S.hello;
  S.hello = true;
  S.seat = m.seat; S.game = m.game || "DeskDot"; S.maxPlayers = m.max_players || Math.max(2, m.seat);
  S.palette = Array.isArray(m.palette) && m.palette.length ? m.palette : Object.values(SEATS).map((c) => ({ color: c, name: c }));
  S.avatars = {}; S.avatarIds = [];
  for (const a of m.avatars || []) { S.avatars[a.id] = a; S.avatarIds.push(a.id); }
  S.modes = Array.isArray(m.modes) ? m.modes : [];
  if (m.rulebook && typeof m.rulebook === "object") S.rulebook = m.rulebook;
  if (typeof m.cid === "string" && m.cid !== cid) { cid = m.cid; store("deskdot.cid", cid); }
  const p = m.profile || {};
  const wasReady = S.me.ready;
  S.me = { name: p.name || "P" + S.seat, color: m.color || p.color || SEATS[S.seat], avatar: p.avatar || S.avatarIds[0], team: p.team ?? null, ready: !!p.ready };
  const newControls = (Array.isArray(m.controls) ? m.controls : []).filter((c) => MODES[c]);
  controls = newControls.length ? newControls : ["dpad"];
  document.title = `${S.game} · DeskDot controller`;
  $("#seat-game").textContent = S.game; $("#seat-n").textContent = "P" + S.seat; $("#seat-t").textContent = `You're Player ${S.seat}`;
  $("#p-sub").textContent = `P${S.seat} · ${S.game}`;
  loadCfg(); applyCfg();
  if (!m.resumed) { // a fresh seat: bring back what this phone used last time (if still free), else a fun name
    const saved = store("deskdot.profile") || {};
    const want = {};
    const nm = cleanName(saved.name).trim() || FUN[Math.floor(Math.random() * FUN.length)];
    if (nm !== S.me.name) { S.me.name = nm; want.name = nm; }
    if (saved.avatar && S.avatars[saved.avatar] && saved.avatar !== S.me.avatar) { S.me.avatar = saved.avatar; want.avatar = saved.avatar; }
    if (saved.color && S.palette.some((x) => x.color === saved.color) && saved.color !== S.me.color) { S.pendingColor = saved.color; want.color = saved.color; } // the server says if it's free
    if (saved.team === 0 || saved.team === 1) { S.me.team = saved.team; want.team = saved.team; }
    if (Object.keys(want).length) sendProfile(want, true);
  }
  paintMe();
  if (firstHello || S.screen === "join") {
    let last = "";
    try { last = sessionStorage.getItem("deskdot.scr:" + code) || ""; } catch (_) {}
    if (m.resumed && (last === "play" || last === "ready")) { S.me.ready = true; sendProfile({ ready: true }, true); go("play"); toast(`Welcome back, ${S.me.name}`); }
    else if (m.resumed && last === "char") go("char");
    else { go("seat"); setTimeout(() => { if (S.screen === "seat") go("char"); }, 1700); }
    buzz(25);
  } else { // a reconnect while the page stayed open
    if (prevSeat && prevSeat !== S.seat) toast(`Reconnected — you're Player ${S.seat} now`);
    else toast("Reconnected");
    if (wasReady && !S.me.ready) { S.me.ready = true; sendProfile({ ready: true }, true); }
    if (S.screen === "char") renderChar(); else if (S.screen === "ready") renderReady(); else paintAll();
  }
}
function onRoster(players) {
  S.roster = Array.isArray(players) ? players : [];
  const mine = S.roster.find((p) => p.seat === S.seat);
  if (mine) {
    if (S.pendingColor && mine.color !== S.pendingColor && taken().has(S.pendingColor)) { toast("Someone just took that colour"); S.pendingColor = ""; }
    if (S.pendingColor === mine.color) S.pendingColor = "";
    if (!S.pendingColor) S.me.color = mine.color;
    if (document.activeElement !== $("#name") && !profQ.name) S.me.name = mine.name;
    S.me.avatar = mine.avatar || S.me.avatar;
    remember();
  }
  if (S.screen === "char") renderChar(); else if (S.screen === "ready") renderReady(); else paintMe();
}
function connect() {
  if (ended) return;
  net("wait");
  let sock;
  try { sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/p/${code}?cid=${encodeURIComponent(cid)}`); }
  catch (_) { retryT = setTimeout(connect, backoff); return; }
  ws = sock;
  sock.onopen = () => { backoff = 300; lastMsg = now(); everConnected = true; ping(); net("ok"); };
  sock.onmessage = (ev) => {
    if (sock !== ws) return;
    lastMsg = now();
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === "hello") onHello(m);
    else if (m.type === "state") onState(m.status || {});
    else if (m.type === "roster") onRoster(m.players);
    else if (m.type === "pong") onPong(m.t);
    else if (m.type === "full") { end("This game is full", "All the seats are taken. Ask the host to open a new game, then scan the QR code on the panel again.", "Try again"); sock.close(); }
    else if (m.type === "closed") { end("Game over", "The host closed this game. Scan the QR code on the panel to join the next one.", "Rejoin"); sock.close(); }
    else if (m.type === "replaced") { end("Opened somewhere else", "This controller was opened in another tab or window, so this one stopped.", "Use this one"); sock.close(); }
  };
  sock.onclose = () => {
    if (sock !== ws || ended) return;
    releaseAll(); net("off");
    retryT = setTimeout(connect, backoff); backoff = Math.min(Math.round(backoff * 1.6), 3000);
  };
}
// keep-alive: pings every 1.5 s measure latency; silence for 5 s means a dead link (Wi-Fi switched) → reconnect now
setInterval(() => {
  ping();
  if (ws && ws.readyState === 1 && now() - lastMsg > 5000 && !ended) {
    const dead = ws; ws = null; // detach first so its late onclose doesn't schedule a second reconnect
    try { dead.close(); } catch (_) {}
    releaseAll(); net("off"); clearTimeout(retryT); connect();
  }
}, 1500);

/* ============================== boot ============================== */
{ const g = store("deskdot.pad") || {}; for (const k of COMFORT) if (validOpt(k, g[k])) cfg[k] = g[k]; }
$("#j-code").textContent = code.toUpperCase();
for (const s of $$(".scr")) s.inert = !s.classList.contains("on");
applyCfg();
connect();

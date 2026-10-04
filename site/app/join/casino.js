"use strict";
/* =====================================================================================================
   DeskDot casino phone page.
   Protocol (docs/CASINO.md §4, docs/API.md): the same /ws/p/<code> socket as the controller.
     in:  hello, roster, state {status (public), private (this seat only)}, pong, full, closed, replaced
     out: profile {name, color, avatar, ready}, casino {op, ...}, ping
   Game UIs are modules: registerGame(id, {title, mount(el, ctx), update(ctx), unmount(), replay(rng, rules),
   spotName(spot)}). The core owns the HUD, chips, undo/clear/rebet/done, toasts and the verify sheet.
   ===================================================================================================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const code = location.pathname.split("/").filter(Boolean).pop() || "";
const now = () => performance.now();
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const fmt = (n) => Math.round(Number(n) || 0).toLocaleString("en-US");
const short = (n) => n >= 1e6 ? (n / 1e6).toFixed(n % 1e6 ? 1 : 0) + "M" : n >= 1e4 ? Math.round(n / 1e3) + "K" : n >= 1000 ? (n / 1e3).toFixed(n % 1000 ? 1 : 0) + "K" : String(n);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || "null"); localStorage.setItem(k, JSON.stringify(v)); } catch (_) { return null; } return v; }
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
function buzz(p) { try { if (!REDUCED && navigator.vibrate) navigator.vibrate(p); } catch (_) {} }
function rand(n) { const a = new Uint8Array(n); if (crypto.getRandomValues) crypto.getRandomValues(a); else for (let i = 0; i < n; i++) a[i] = Math.random() * 256; return a; }
const B36 = "abcdefghijklmnopqrstuvwxyz0123456789";

/* ------------------------------------------------ identity: client id (seat back on reconnect) + fairness seed */
let cid = store("deskdot.cid");
if (typeof cid !== "string" || !/^[A-Za-z0-9_-]{8,40}$/.test(cid)) { cid = "p" + [...rand(12)].map((b) => B36[b % 36]).join(""); store("deskdot.cid", cid); }
let seed = store("deskdot.casino.seed");
if (typeof seed !== "string" || !/^[!-9;-~]{1,64}$/.test(seed)) { seed = [...rand(10)].map((b) => B36[b % 36]).join(""); store("deskdot.casino.seed", seed); }

const S = {
  screen: "join", seat: 0, game: "", palette: [], avatars: {}, avatarIds: [],
  me: { name: "", color: "#ffcc33", avatar: "" }, roster: [], pub: {}, priv: {}, chip: store("deskdot.casino.chip") || 5,
  undo: [], undoRound: null, seenHash: {}, lastResult: null, lastNote: 0, mod: null, modId: "", credits: null,
  countdown: { at: 0, left: null }, hello: false,
};

/* ------------------------------------------------ screens */
const ORDER = ["join", "seat", "table"];
function go(name) {
  if (S.screen === name) return;
  for (const s of $$(".scr")) { const on = s.id === "s-" + name; s.classList.toggle("on", on); s.inert = !on; }
  S.screen = name;
  try { sessionStorage.setItem("deskdot.casino.scr:" + code, name); } catch (_) {}
  if (name === "seat") renderSeat();
  if (name === "table") { paintMe(); renderAll(); }
}

/* ------------------------------------------------ avatars (same LED look as the controller) */
const FIXED = { w: "#ebebeb", k: "#000000", y: "#ffc800", r: "#ff283c" };
function shade(hex, k) { const n = parseInt(hex.slice(1), 16), f = (v) => Math.round(v * k).toString(16).padStart(2, "0"); return "#" + f(n >> 16) + f((n >> 8) & 255) + f(n & 255); }
function drawAvatar(cv, id, color) {
  const px = (S.avatars[id] || S.avatars[S.avatarIds[0]] || {}).px;
  const css = Number(cv.dataset.s) || 40, dpr = Math.min(2, devicePixelRatio || 1), W = Math.round(css * dpr);
  if (cv.width !== W) { cv.width = W; cv.height = W; }
  cv.style.width = cv.style.height = css + "px";
  const g = cv.getContext("2d"); g.clearRect(0, 0, W, W);
  if (!px) return;
  const n = px.length, cell = W / n, r = cell * 0.42, col = { c: color, d: shade(color, 0.5), ...FIXED };
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const ch = px[y][x], fill = ch === "." || ch === " " ? null : col[ch];
    g.beginPath(); g.arc(x * cell + cell / 2, y * cell + cell / 2, r, 0, Math.PI * 2);
    if (fill && fill !== "#000000") { g.shadowColor = fill; g.shadowBlur = cell * 0.5; g.fillStyle = fill; } else { g.shadowBlur = 0; g.fillStyle = "rgba(255,255,255,.06)"; }
    g.fill();
  }
}
function setColor(hex) {
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  document.documentElement.style.setProperty("--c", hex);
  document.documentElement.style.setProperty("--ca", `rgba(${r},${g},${b},.35)`);
}
function paintMe() {
  setColor(S.me.color);
  for (const cv of $$("#pv, .meb .av")) drawAvatar(cv, S.me.avatar, S.me.color);
  $("#me-name").textContent = S.me.name || "P" + S.seat;
}

/* ------------------------------------------------ seat screen (profile protocol shared with the controller) */
const FUN = ["Ace", "Lucky", "Jinx", "Dice", "Chip", "Nova", "Blaze", "Royal", "Maverick", "Pip", "Vegas", "Rio", "Dash", "Zippy", "Monte", "Bingo"];
const cleanName = (s) => String(s || "").replace(/[^A-Za-z0-9 !?.'_+&#*-]/g, "").replace(/\s+/g, " ").replace(/^\s+/, "").slice(0, 10);
let profT = 0, profQ = {};
function sendProfile(p, now_ = false) {
  Object.assign(profQ, p);
  const flush = () => { profT = 0; if (ws && ws.readyState === 1 && Object.keys(profQ).length) ws.send(JSON.stringify({ type: "profile", ...profQ })); profQ = {}; };
  clearTimeout(profT); if (now_) flush(); else profT = setTimeout(flush, 180);
  store("deskdot.profile", { name: S.me.name, color: S.me.color, avatar: S.me.avatar });
}
function taken() { const t = new Set(); for (const p of S.roster) if (p.seat !== S.seat) t.add(p.color); return t; }
function renderSeat() {
  const nm = $("#name"); if (document.activeElement !== nm) nm.value = S.me.name;
  $("#seat-k").textContent = `Seat ${S.seat} · ${S.game}`;
  const avs = $("#avs");
  if (avs.childElementCount !== S.avatarIds.length) {
    avs.innerHTML = "";
    for (const id of S.avatarIds) {
      const b = document.createElement("button"); b.className = "tile"; b.setAttribute("role", "radio"); b.dataset.av = id; b.setAttribute("aria-label", S.avatars[id].name);
      const cv = document.createElement("canvas"); cv.className = "av"; cv.dataset.s = "38"; b.append(cv); avs.append(b);
    }
  }
  for (const b of $$(".tile", avs)) { b.setAttribute("aria-checked", String(b.dataset.av === S.me.avatar)); drawAvatar($("canvas", b), b.dataset.av, S.me.color); }
  const cols = $("#cols"), tk = taken();
  if (cols.childElementCount !== S.palette.length) {
    cols.innerHTML = "";
    for (const p of S.palette) { const b = document.createElement("button"); b.setAttribute("role", "radio"); b.dataset.col = p.color; b.style.setProperty("--sc", p.color); b.setAttribute("aria-label", p.name); cols.append(b); }
  }
  for (const b of $$("button", cols)) { const c = b.dataset.col; b.setAttribute("aria-checked", String(c === S.me.color)); b.setAttribute("aria-disabled", String(tk.has(c) && c !== S.me.color)); }
  const h = S.pub.house;
  if (h) $("#seat-rules").textContent = `Everyone starts with ${fmt(h.base_credits)} credits. Bets ${fmt(h.min_bet)}–${fmt(h.max_bet)} per spot. Play money only — just for fun.`;
  paintMe();
}
$("#name").addEventListener("input", (e) => { const v = cleanName(e.target.value); if (v !== e.target.value) e.target.value = v; S.me.name = v.trim() || "P" + S.seat; paintMe(); sendProfile({ name: S.me.name }); });
$("#name").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
$("#avs").addEventListener("click", (e) => { const b = e.target.closest("[data-av]"); if (!b) return; S.me.avatar = b.dataset.av; buzz(8); sendProfile({ avatar: S.me.avatar }, true); renderSeat(); });
$("#cols").addEventListener("click", (e) => {
  const b = e.target.closest("[data-col]"); if (!b) return;
  if (b.getAttribute("aria-disabled") === "true") { toast("That colour belongs to another player", true); return; }
  S.me.color = b.dataset.col; buzz(8); sendProfile({ color: S.me.color }, true); renderSeat();
});
$("#sit").addEventListener("click", () => {
  sendProfile({ name: S.me.name, ready: true }, true); send("seed", { client_seed: seed });
  buzz([15, 40, 25]); go("table");
});

/* ------------------------------------------------ chips */
const CHIPS = [1, 5, 25, 100, 500];
function renderRack() {
  const rack = $("#rack"), h = S.pub.house || {}, free = S.priv.credits ?? 0;
  if (!rack.childElementCount) {
    for (const v of [...CHIPS, "all"]) {
      const b = document.createElement("button"); b.className = "chip " + (v === "all" ? "call" : "c" + v); b.setAttribute("role", "radio"); b.dataset.v = v;
      b.innerHTML = `<span>${v === "all" ? "ALL<br>IN" : short(v)}</span>`; b.setAttribute("aria-label", v === "all" ? "All in" : v + " credits"); rack.append(b);
    }
  }
  for (const b of $$(".chip", rack)) {
    const v = b.dataset.v === "all" ? "all" : Number(b.dataset.v);
    b.setAttribute("aria-checked", String(String(v) === String(S.chip)));
    b.disabled = !ctx.betting || (v !== "all" && (v > free || (h.max_bet && v > h.max_bet)));
  }
}
$("#rack").addEventListener("click", (e) => {
  const b = e.target.closest(".chip"); if (!b || b.disabled) return;
  S.chip = b.dataset.v === "all" ? "all" : Number(b.dataset.v); store("deskdot.casino.chip", S.chip); buzz(6); renderRack();
});
function chipAmount() {
  const free = S.priv.credits ?? 0, max = (S.pub.house || {}).max_bet || Infinity;
  if (S.chip === "all") return Math.min(free, max);
  return Math.min(Number(S.chip) || 1, free);
}
function chipClass(n) { return n >= 500 ? "c500" : n >= 100 ? "c100" : n >= 25 ? "c25" : n >= 5 ? "c5" : "c1"; }
function chipStyle(n) { const m = { c500: ["#7a35d6", "#fff"], c100: ["#1e1e26", "#fff"], c25: ["#119a54", "#fff"], c5: ["#d8203a", "#fff"], c1: ["#e8e4da", "#1a1a1a"] }[chipClass(n)]; return `--cc:${m[0]};--ct:${m[1]}`; }

/* ------------------------------------------------ the core API games use */
const ctx = {
  get pub() { return S.pub; }, get priv() { return S.priv; }, get phase() { return S.pub.phase || "idle"; },
  get betting() { return S.pub.phase === "betting" && !!S.priv.can_bet; },
  fmt, short, chipStyle, buzz, esc,
  send: (op, extra) => send(op, extra),
  /** place the selected chip on `spot` (the server validates everything) */
  bet(spot) {
    if (!ctx.betting) { toast(S.pub.phase === "betting" ? "Sit down first" : "Bets are closed — wait for the next round", true); buzz(30); return false; }
    const amt = chipAmount();
    if (amt <= 0) { toast("Out of credits — ask the host for a top-up", true); buzz(30); return false; }
    send("bet", { spot, amount: amt }); S.undo.push({ spot, amount: amt }); buzz(9); return true;
  },
  unbet(spot) { send("unbet", { spot }); S.undo = S.undo.filter((u) => u.spot !== spot); buzz([8, 30, 8]); },
  others(spot) { const t = (S.pub.totals || {})[spot] || 0; return t - ((S.priv.bets || {})[spot] || 0); },
};
function send(op, extra) { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "casino", op, ...(extra || {}) })); }
$("#undo").addEventListener("click", () => { const u = S.undo.pop(); if (!u) return; send("unbet", { spot: u.spot, amount: u.amount }); buzz(8); });
$("#clear").addEventListener("click", () => { send("clear"); S.undo = []; buzz([8, 30, 8]); });
$("#rebet").addEventListener("click", () => { send("rebet"); buzz(10); S.undo = Object.entries(S.priv.last_bets || {}).map(([spot, amount]) => ({ spot, amount })); });
$("#done").addEventListener("click", () => { send("done"); buzz([12, 30, 12]); });

/* ------------------------------------------------ game registry */
const GAMES = {};
function registerGame(id, mod) { GAMES[id] = mod; }
function ensureModule() {
  const id = S.pub.game || "";
  if (id === S.modId) return;
  if (S.mod && S.mod.unmount) S.mod.unmount();
  const board = $("#board"); board.innerHTML = "";
  S.mod = GAMES[id] || null; S.modId = id; S.undo = [];
  if (S.mod) S.mod.mount(board, ctx);
  else board.innerHTML = `<div class="generic"><div><b style="font-size:18px;color:var(--ink)">${esc(S.pub.name || "This table")}</b><p>Watch the panel — this game's phone controls are coming soon.</p></div></div>`;
}

/* ------------------------------------------------ HUD: credits (animated), phase, countdown, history */
let credAnim = 0;
function setCredits(v) {
  const el = $("#credits");
  if (S.credits === null) { S.credits = v; el.textContent = fmt(v); return; }
  if (v === S.credits) return;
  const from = S.credits, to = v, t0 = now(), dur = REDUCED ? 0 : clamp(Math.abs(to - from) * 2, 350, 1100);
  S.credits = v; cancelAnimationFrame(credAnim);
  el.classList.toggle("up", to > from); el.classList.toggle("down", to < from);
  const step = () => {
    const k = dur ? clamp((now() - t0) / dur, 0, 1) : 1, e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) credAnim = requestAnimationFrame(step); else setTimeout(() => el.classList.remove("up", "down"), 500);
  };
  step();
}
const TONE = (t) => "t-" + (t || "white");
const PHASES = {
  idle: ["Table closed", "Waiting for the host to open the next round"],
  betting: ["Place your bets", ""],
  locked: ["No more bets", "Watch the panel!"],
  spinning: ["", "Watch the panel!"],
  dealing: ["Dealing…", "Watch the panel!"],
  action: ["Your move", ""],
  result: ["", ""],
};
function renderPhase() {
  const p = S.pub, ph = p.phase || "idle", ring = $("#ring"), mod = S.mod || {};
  let [title, sub] = PHASES[ph] || ["", ""];
  if (ph === "spinning") title = mod.spinTitle || "Spinning…";
  if (ph === "betting" && p.ends_in == null) sub = "The countdown starts with the first chip";
  if (ph === "betting" && p.ends_in != null) sub = S.priv.done ? "You're done — waiting for the others" : `Round ${p.round} · tap Done when you're happy`;
  ring.classList.toggle("spin", ph === "spinning" || ph === "locked" || ph === "dealing");
  let ball = $(".ball", ring);
  if (ph === "result" && p.result) {
    const r = p.result;
    title = (mod.resultTitle ? mod.resultTitle(r) : r.label);
    const mine = S.priv.result;
    sub = mine ? (mine.net > 0 ? `You won ${fmt(mine.net)}` : mine.net < 0 ? `You lost ${fmt(-mine.net)}` : "Push — stake returned") : (r.winners && r.winners.length ? `${r.winners.length} winner${r.winners.length > 1 ? "s" : ""}` : "House wins");
    if (!ball) { ball = document.createElement("div"); ball.className = "ball"; ring.append(ball); }
    ball.className = "ball " + TONE(r.tone); ball.textContent = r.label;
  } else if (ball) ball.remove();
  if (p.paused) { title = "Paused"; sub = "The host paused the table"; }
  $("#ph-title").textContent = title; $("#ph-sub").textContent = sub || (p.hash ? `Round ${p.round} · sealed ${p.hash.slice(0, 10)}…` : " ");
  $("#paused").hidden = !p.paused;
  $("#s-table").classList.toggle("closed", ph !== "betting");
  // from the lock until settlement every bet is frozen: say so on the table itself
  const frozen = ["locked", "spinning", "dealing", "action"].includes(ph);
  $("#lockb").hidden = !(frozen || ph === "result" || ph === "idle");
  $("#lockb").style.top = $("#board").offsetTop + 10 + "px";
  $("#lockb-t").textContent = frozen ? "No more bets — bets locked" : ph === "result" ? "Paying out — next round soon" : "Table closed";
  if (frozen && sub === PHASES[ph]?.[1]) sub = "Your bets are locked in until the result";
  const hist = $("#hist"), items = (p.history || []).slice().reverse().slice(0, 12);
  const key = items.map((h) => h.round).join(",");
  if (hist.dataset.k !== key) {
    hist.dataset.k = key; hist.innerHTML = "";
    for (const h of items) { const i = document.createElement("i"); i.className = TONE(h.tone); i.textContent = h.label; hist.append(i); }
  }
}
function tickCountdown() {
  const p = S.pub, ring = $("#ring"), cd = $("#cd"), pr = $("#ring-p");
  let left = null;
  if (p.phase === "betting" && S.countdown.left != null && !p.paused) left = Math.max(0, S.countdown.left - (now() - S.countdown.at) / 1000);
  const span = (p.house || {}).bet_seconds || 20;
  if (left != null) {
    cd.textContent = Math.ceil(left - 1e-6); pr.style.strokeDashoffset = String(138.2 * (1 - clamp(left / span, 0, 1)));
    ring.classList.toggle("hurry", left <= 5);
  } else {
    ring.classList.remove("hurry");
    cd.textContent = p.phase === "betting" ? "" : ""; pr.style.strokeDashoffset = p.phase === "betting" ? "0" : "138.2";
  }
  requestAnimationFrame(tickCountdown);
}
function renderActions() {
  const b = ctx.betting, mine = Object.keys(S.priv.bets || {}).length > 0;
  $("#undo").disabled = !b || !S.undo.length;
  $("#clear").disabled = !b || !mine;
  $("#rebet").disabled = !b || mine || !Object.keys(S.priv.last_bets || {}).length;
  const d = $("#done"); d.disabled = !b || !mine; d.classList.toggle("on", !!S.priv.done); d.classList.toggle("hot", !S.priv.done);
  d.textContent = S.priv.done ? "✓ Done" : "Done";
}
function renderAll() {
  if (S.screen !== "table") return;
  ensureModule(); renderPhase(); renderRack(); renderActions(); maybeHowTo();
  const pv = S.priv;
  if (typeof pv.credits === "number") setCredits(pv.credits);
  $("#inplay").textContent = pv.staked ? `${fmt(pv.staked)} on the table` : pv.escrow ? `${fmt(pv.escrow)} in play` : " ";
  $("#me-sub").textContent = `${S.pub.name || S.game}${S.seat ? " · seat " + S.seat : ""}`;
  $("#pcount").textContent = String((S.pub.players || []).filter((p) => p.online).length || 1);
  if (S.mod && S.mod.update) S.mod.update(ctx);
  if (S.sheet === "players") renderPlayers();
}

/* ------------------------------------------------ state from the server */
function onState(m) {
  const prevPhase = S.pub.phase, prevRound = S.pub.round;
  S.pub = m.status || {}; S.priv = m.private || {};
  applyTheme(S.pub.table_theme);
  const p = S.pub;
  if (!p.casino) return;
  if (p.phase === "betting" && p.hash && p.round != null) S.seenHash[p.round] = p.hash; // the commitment we saw before betting
  if (p.round !== S.undoRound) { S.undoRound = p.round; S.undo = []; }
  S.countdown = { at: now(), left: p.ends_in };
  if (prevPhase !== p.phase) {
    if (p.phase === "locked") buzz(25);
    if (p.phase === "betting" && prevPhase) buzz(10);
  }
  const r = S.priv.result;
  if (p.phase === "result" && r && r.round !== S.lastResult) { S.lastResult = r.round; showResult(r, p.result); }
  const n = S.priv.notice;
  if (n && n.id !== S.lastNote) { const first = S.lastNote === 0; S.lastNote = n.id; if (!first && n.kind !== "result") toast(n.text, n.kind === "error"); }
  if (S.priv.kicked) end("You're off the table", "The host has taken you off this table. Ask them if you think that's a mistake.", "Reload");
  if (S.priv.seated === false && S.screen === "table" && S.hello) { /* the server re-seats us on the next profile */ }
  renderAll();
  void prevRound;
}

/* ------------------------------------------------ toasts, win card, confetti */
let toastT = 0;
function toast(s, bad) {
  const t = $("#toast"); t.textContent = s; t.className = "toast" + (bad ? " error" : ""); t.hidden = false;
  t.style.animation = "none"; void t.offsetWidth; t.style.animation = ""; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 2600);
}
let winT = 0;
function showResult(mine, pubRes) {
  const w = $("#win"), net = mine.net;
  w.classList.toggle("lose", net <= 0);
  $("#win-k").textContent = net > 0 ? "You won" : net < 0 ? "Not this time" : "Push";
  $("#win-v").textContent = net > 0 ? "+" + fmt(net) : net < 0 ? "−" + fmt(-net) : "±0";
  const what = pubRes ? (S.mod && S.mod.resultTitle ? S.mod.resultTitle(pubRes) : pubRes.label) : "";
  $("#win-s").textContent = `${what}${what ? " · " : ""}tap ⓘ to verify`;
  w.hidden = false; clearTimeout(winT); winT = setTimeout(() => { w.hidden = true; }, net > 0 ? 3200 : 2200);
  if (net > 0) { buzz([30, 50, 30, 50, 80]); confetti(Math.min(36, 8 + Math.round(Math.log2(1 + net) * 3))); } else buzz(net < 0 ? 40 : 15);
}
function confetti(n) {
  if (REDUCED) return;
  const box = $("#confetti"), cols = ["#ffcc33", "#d8203a", "#119a54", "#7a35d6", "#ff3f78"];
  for (let i = 0; i < n; i++) {
    const c = document.createElement("i"); c.style.left = Math.random() * 100 + "%"; c.style.setProperty("--cc", cols[i % cols.length]);
    c.style.animationDelay = Math.random() * 0.5 + "s"; c.style.animationDuration = 1.2 + Math.random() * 0.9 + "s"; box.append(c);
    setTimeout(() => c.remove(), 2800);
  }
}

/* ------------------------------------------------ sheets: players, me (verify, seed, rules) */
function openSheet(kind) { S.sheet = kind; $("#scrim").hidden = false; $("#sheet").hidden = false; $("#sh-b").scrollTop = 0; if (kind === "players") renderPlayers(); else if (kind === "help") renderHelp(); else renderMe(); }
function closeSheet() { S.sheet = ""; $("#scrim").hidden = true; $("#sheet").hidden = true; }
$("#sh-x").addEventListener("click", closeSheet); $("#scrim").addEventListener("click", closeSheet);
$("#players-btn").addEventListener("click", () => openSheet("players"));
$("#me-btn").addEventListener("click", () => openSheet("me"));
$("#help-btn").addEventListener("click", () => { S.helpTab = "how"; openSheet("help"); });

/* ------------------------------------------------ table theme (status.table_theme: felt + accent, cross-faded) */
let themeId = "classic";
function applyTheme(t) {
  const id = (t && t.id) || "classic";
  if (id === themeId) return;
  themeId = id;
  const st = document.documentElement.style, css = (t && t.css) || {};
  const map = { "--felt": css.felt, "--felt2": css.felt2, "--felt3": css.felt3, "--gold": css.accent, "--gold2": css.accent_lo, "--gold-hi": css.accent_hi, "--gold-rgb": css.accent_rgb, "--gold-ink": css.ink };
  for (const [k, v] of Object.entries(map)) { if (id !== "classic" && v) st.setProperty(k, v); else st.removeProperty(k); } // classic = the stylesheet's own look
  document.documentElement.dataset.theme = id;
}

/* ------------------------------------------------ how to play / rulebook / payouts (casino/rulebook.py) */
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
const guideFor = () => (S.rulebook || {})[S.pub.game || ""] || null;
function stepsHtml(g) { return `<ol class="steps">${g.how.map((s) => `<li>${md(s)}</li>`).join("")}</ol>`; }
function renderHelp() {
  const g = guideFor(), mod = S.mod || {}, tab = S.helpTab || "how";
  $("#sh-t").textContent = g ? g.title : (S.pub.name || "How to play");
  const tabs = [["how", "How to play"], ["rules", "Rulebook"], ["pays", "Payouts"]];
  let html = `<div class="htabs" role="tablist" aria-label="Help">${tabs.map(([k, l]) => `<button role="tab" data-ht="${k}" aria-selected="${k === tab}">${l}</button>`).join("")}</div>`;
  if (!g && tab !== "pays") html += `<p class="note">The rules for this table aren't available on this phone yet — reload the page.</p>`;
  else if (tab === "how") html += `<p class="tagl">${md(g.tagline)}</p>${stepsHtml(g)}`;
  else if (tab === "rules") html += `<div class="rb">${g.rules.map((r) => `<h3>${esc(r.h)}</h3><ul>${r.items.map((i) => `<li>${md(i)}</li>`).join("")}</ul>`).join("")}</div>`;
  else html += mod.paytable ? `<div class="eng" style="margin:4px 0 6px">Pays · house edge — this table's live numbers</div>${mod.paytable(ctx)}` : `<p class="note">Payouts appear once the table is live.</p>`;
  const b = $("#sh-b"); b.innerHTML = html;
  for (const x of $$("[data-ht]", b)) x.addEventListener("click", () => { S.helpTab = x.dataset.ht; buzz(6); renderHelp(); b.scrollTop = 0; });
}
/** The first time this phone sits at a game: a one-time "How to play" card (remembered per game). */
function maybeHowTo() {
  const g = guideFor(), id = S.pub.game;
  if (!g || !id || S.howtoShown === id || S.sheet || store("deskdot.casino.howto." + id)) return;
  S.howtoShown = id;
  const el = document.createElement("div"); el.className = "howto"; el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-label", "How to play " + g.title);
  el.innerHTML = `<div class="card"><div class="eng">How to play</div><h2>${esc(g.title)}</h2><p class="tagl">${md(g.tagline)}</p>${stepsHtml(g)}
    <div class="bt"><button class="pill" data-h="rules">Full rules</button><button class="pill hot" data-h="ok">Got it</button></div></div>`;
  const done = () => { store("deskdot.casino.howto." + id, 1); el.remove(); };
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-h]");
    if (b && b.dataset.h === "rules") { done(); S.helpTab = "rules"; openSheet("help"); }
    else if (b || e.target === el) done();
  });
  $("#app").append(el);
}
function renderPlayers() {
  $("#sh-t").textContent = "Leaderboard";
  const b = $("#sh-b"), ps = S.pub.players || [];
  b.innerHTML = ps.length ? "" : `<p class="note">Nobody has sat down yet.</p>`;
  ps.forEach((p, i) => {
    const row = document.createElement("div"); row.className = "row" + (p.seat === S.seat ? " me" : "");
    row.innerHTML = `<span class="rk">${i + 1}</span><canvas class="av" data-s="38"></canvas><div><b style="color:${esc(p.color)}">${esc(p.name)}${p.seat === S.seat ? " (you)" : ""}</b><small>${p.online ? (p.seat === "host" ? "Host" : "Seat " + p.seat) : "Away"}${p.staked ? " · " + fmt(p.staked) + " on the table" : ""}</small></div>
      <div class="cr num">${fmt(p.credits)}<small class="${p.net > 0 ? "pos" : p.net < 0 ? "neg" : ""}">${p.net > 0 ? "+" : p.net < 0 ? "−" : "±"}${fmt(Math.abs(p.net))}</small></div>`;
    b.append(row);
    if (p.avatar) drawAvatar($("canvas", row), p.avatar, p.color); else { const cv = $("canvas", row); cv.style.width = cv.style.height = "38px"; cv.style.background = p.color; cv.style.borderRadius = "50%"; }
  });
}
let verifySel = null;
function renderMe() {
  $("#sh-t").textContent = "Fair play";
  const b = $("#sh-b"), hist = (S.pub.history || []).filter((h) => h.proof && h.proof.server_seed).slice().reverse();
  if (verifySel == null || !hist.some((h) => h.round === verifySel)) verifySel = hist.length ? hist[0].round : null;
  const h = hist.find((x) => x.round === verifySel);
  const mod = S.mod || {};
  let html = `<p class="note">Every round is sealed before betting opens: the panel commits to a secret <b>server seed</b> by publishing its SHA-256. Your phone's own <b>seed</b> is mixed in when betting closes, so nobody — not even the host — can pick the result. After the round the seed is revealed and this phone re-computes the result itself.</p>`;
  html += `<div class="eng" style="margin-top:12px">Verify a round</div>`;
  if (!hist.length) html += `<p class="note">No finished rounds yet.</p>`;
  else {
    html += `<div class="rounds">${hist.slice(0, 16).map((x) => `<button class="${TONE(x.tone)}" data-r="${x.round}" aria-pressed="${x.round === verifySel}">${esc(x.label)}</button>`).join("")}</div>`;
    if (h) {
      const pr = h.proof, saw = S.seenHash[h.round];
      html += `<dl class="kv"><dt>Round</dt><dd>#${h.round} · ${esc(h.game)} · ${esc(h.label)}</dd><dt>Hash</dt><dd>${esc(pr.hash)}</dd><dt>Server seed</dt><dd>${esc(pr.server_seed)}</dd><dt>Client seed</dt><dd>${esc(pr.client_seed || "")}</dd><dt>Nonce</dt><dd>${pr.nonce}</dd></dl>`;
      html += `<div id="vres"></div><button class="pill hot" id="vgo" style="width:100%">Verify on this phone</button>`;
      html += saw ? "" : `<p class="note">This phone didn't see round #${h.round} open, so it can check the maths but not that the hash was shown before betting.</p>`;
    }
  }
  html += `<div class="eng" style="margin-top:18px">Your seed</div><p class="note">Mixed into every round you sit in. Change it whenever you like.</p>
    <div style="display:flex;gap:8px;align-items:center"><code class="num" style="flex:1;padding:10px;border-radius:10px;background:var(--s3);word-break:break-all;user-select:text;-webkit-user-select:text">${esc(seed)}</code><button class="pill" id="reseed">New seed</button></div>`;
  if (guideFor()) html = `<button class="pill hot" id="me-help" style="width:100%;margin-bottom:12px">How to play &amp; rulebook</button>` + html;
  if (mod.paytable) html += `<div class="eng" style="margin-top:18px">Pays · house edge</div>${mod.paytable(ctx)}`;
  html += `<div style="display:flex;gap:8px;margin-top:18px"><button class="pill" id="edit-me" style="flex:1">Change name / look</button></div>`;
  b.innerHTML = html;
  for (const x of $$("[data-r]", b)) x.addEventListener("click", () => { verifySel = Number(x.dataset.r); renderMe(); });
  const g = $("#vgo", b); if (g) g.addEventListener("click", () => runVerify(h));
  $("#reseed", b).addEventListener("click", () => { seed = [...rand(10)].map((v) => B36[v % 36]).join(""); store("deskdot.casino.seed", seed); send("seed", { client_seed: seed }); buzz(10); renderMe(); toast("New seed — used from the next round"); });
  $("#edit-me", b).addEventListener("click", () => { closeSheet(); go("seat"); });
  const mh = $("#me-help", b); if (mh) mh.addEventListener("click", () => { S.helpTab = "how"; openSheet("help"); });
}
function runVerify(h) {
  const box = $("#vres"), pr = h.proof, out = [];
  try {
    const seedBytes = hexBytes(pr.server_seed);
    const hashOk = hex(sha256(seedBytes)) === String(pr.hash).toLowerCase();
    out.push([hashOk, hashOk ? "The revealed seed matches the sealed hash" : "The seed does NOT match the hash"]);
    const saw = S.seenHash[h.round];
    if (saw) out.push([saw === pr.hash, saw === pr.hash ? "Same hash this phone saw before betting" : "The hash differs from the one shown before betting!"]);
    const mod = GAMES[h.game];
    if (mod && mod.replay) {
      S.verifying = h.round; // games whose round depends on more than its seeds (blackjack's shoe) get the stored outcome
      const got = mod.replay(new Rng(seedBytes, pr.client_seed || "deskdot", pr.nonce), h.rules || {}, h.outcome);
      S.verifying = 0;
      const same = JSON.stringify(canon(got)) === JSON.stringify(canon(h.outcome));
      out.push([same, same ? `Re-computed result: ${mod.describe ? mod.describe(got) : JSON.stringify(got)} ✓` : "The re-computed result differs!"]);
    }
    if ((pr.client_seed || "").split(".").includes(seed)) out.push([true, "Your seed was part of this round"]);
  } catch (e) { out.push([false, "Couldn't verify: " + e.message]); }
  box.innerHTML = out.map(([ok, t]) => `<div class="vr ${ok ? "ok" : "bad"}">${ok ? "✓" : "✗"} ${esc(t)}</div>`).join("");
  buzz(out.every((x) => x[0]) ? [10, 30, 10] : 60);
}
function canon(o) { if (Array.isArray(o)) return o.map(canon); if (o && typeof o === "object") { const r = {}; for (const k of Object.keys(o).sort()) r[k] = canon(o[k]); return r; } return o; }

/* ------------------------------------------------ provably fair maths (mirrors deskdot/casino/fair.py) */
const K256 = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
function sha256(bytes) {
  const l = bytes.length, total = ((l + 9 + 63) >> 6) << 6, m = new Uint8Array(total);
  m.set(bytes); m[l] = 0x80;
  const dv = new DataView(m.buffer), bits = l * 8;
  dv.setUint32(total - 8, Math.floor(bits / 4294967296)); dv.setUint32(total - 4, bits >>> 0);
  const h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19], w = new Uint32Array(64);
  const ror = (x, n) => (x >>> n) | (x << (32 - n));
  for (let o = 0; o < total; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15], b = w[i - 2];
      w[i] = (w[i - 16] + (ror(a, 7) ^ ror(a, 18) ^ (a >>> 3)) + w[i - 7] + (ror(b, 17) ^ ror(b, 19) ^ (b >>> 10))) >>> 0;
    }
    let [a, b, c, d, e, f, g, k] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (k + (ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)) + ((e & f) ^ (~e & g)) + K256[i] + w[i]) >>> 0;
      const t2 = ((ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      k = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0; h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0; h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + k) >>> 0;
  }
  const out = new Uint8Array(32), odv = new DataView(out.buffer);
  h.forEach((v, i) => odv.setUint32(i * 4, v));
  return out;
}
function hmac256(key, msg) {
  let k = key.length > 64 ? sha256(key) : key;
  const kb = new Uint8Array(64); kb.set(k);
  const ip = new Uint8Array(64 + msg.length), op = new Uint8Array(96);
  for (let i = 0; i < 64; i++) { ip[i] = kb[i] ^ 0x36; op[i] = kb[i] ^ 0x5c; }
  ip.set(msg, 64); op.set(sha256(ip), 64);
  return sha256(op);
}
const hex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
function hexBytes(s) { if (!/^([0-9a-f]{2})+$/i.test(s || "")) throw new Error("seed is not hex"); return new Uint8Array(s.match(/../g).map((x) => parseInt(x, 16))); }
class Rng { // HMAC-SHA256(server_seed, `${client}:${nonce}:${counter}`) as big-endian u32 words; rejection sampling
  constructor(serverSeed, clientSeed, nonce) { this.key = serverSeed; this.client = clientSeed; this.nonce = nonce; this.counter = 0; this.words = []; }
  u32() {
    if (!this.words.length) {
      const blk = hmac256(this.key, new TextEncoder().encode(`${this.client}:${this.nonce}:${this.counter}`)), dv = new DataView(blk.buffer);
      this.counter++; this.words = []; for (let i = 7; i >= 0; i--) this.words.push(dv.getUint32(i * 4));
    }
    return this.words.pop();
  }
  below(n) { const U = 4294967296, limit = U - (U % n); for (;;) { const x = this.u32(); if (x < limit) return x % n; } }
  randint(lo, hi) { return lo + this.below(hi - lo + 1); }
}

/* =====================================================================================================
   GAME: Roulette — a full table. Tap a number (straight), its edge (split), a corner, the rail (street / six
   line), or an outside box. Hold a finger down to see what a spot covers and what it pays; slide to adjust;
   release to bet. Long-press a spot holding your chips to take them back.
   ===================================================================================================== */
registerGame("roulette", (() => {
  const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  const EU = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26];
  const US = [0, 28, 9, 26, 30, 11, 7, 20, 32, 17, 5, 22, 34, 15, 3, 24, 36, 13, 1, 37, 27, 10, 25, 29, 12, 8, 19, 31, 18, 6, 21, 33, 16, 4, 23, 35, 14, 2];
  const lab = (n) => (n === 37 ? "00" : String(n));
  const num = (s) => (s === "00" ? 37 : Number(s));
  const col = (n) => (n === 0 || n === 37 ? "green" : RED.has(n) ? "red" : "black");
  const V0 = -2.35, V1 = 3, U0 = -1, U1 = 13, RAIL = -0.35;
  let el, root, felt, ctxr, us = false, land = false, geo = null, cells = {}, chipsEl, tip, ro, down = null, lpT = 0;

  function covers(spot) {
    const [k, a] = spot.split(":"), p = (a || "").split("-").map(num);
    if (k === "n") return [num(a)];
    if (k === "s" || k === "tr") return p;
    if (k === "st") return [p[0], p[0] + 1, p[0] + 2];
    if (k === "c") return [p[0], p[0] + 1, p[0] + 3, p[0] + 4];
    if (k === "sl") return [0, 1, 2, 3, 4, 5].map((i) => p[0] + i);
    if (spot === "ff") return [0, 1, 2, 3];
    if (spot === "tl") return [0, 37, 1, 2, 3];
    if (k === "dz") return Array.from({ length: 12 }, (_, i) => 12 * (p[0] - 1) + i + 1);
    if (k === "col") return Array.from({ length: 12 }, (_, i) => 3 * i + p[0]);
    const all = Array.from({ length: 36 }, (_, i) => i + 1);
    return { red: all.filter((n) => RED.has(n)), black: all.filter((n) => !RED.has(n)), odd: all.filter((n) => n % 2), even: all.filter((n) => !(n % 2)), low: all.filter((n) => n <= 18), high: all.filter((n) => n > 18) }[spot] || [];
  }
  function info(spot) { // [name, pays]
    const k = spot.split(":")[0], c = covers(spot);
    const names = { n: "Straight", s: "Split", tr: "Trio", st: "Street", c: "Corner", sl: "Six line", dz: "Dozen", col: "Column" };
    if (spot === "ff") return ["First four 0-1-2-3", "8:1"];
    if (spot === "tl") return ["Top line 0-00-1-2-3", "6:1"];
    if (["red", "black", "odd", "even", "low", "high"].includes(spot)) return [{ low: "1–18", high: "19–36" }[spot] || spot[0].toUpperCase() + spot.slice(1), "1:1"];
    const pays = { 1: "35:1", 2: "17:1", 3: "11:1", 4: "8:1", 6: "5:1", 12: "2:1" }[c.length];
    const what = k === "dz" ? `${12 * (c[0] > 24 ? 2 : c[0] > 12 ? 1 : 0) + 1}–${c[c.length - 1]}` : k === "col" ? `column ${spot.split(":")[1]}` : c.map(lab).join("/");
    return [`${names[k] || "Bet"} ${what}`, pays];
  }
  // logical (u along the table, v across) → screen; portrait: zero on top, outside bets on the left
  function S2(u, v) { return land ? [(u - U0) * geo.su + geo.x, (V1 - v) * geo.sv + geo.y] : [(v - V0) * geo.sv + geo.x, (u - U0) * geo.su + geo.y]; }
  function L2(x, y) { return land ? [(x - geo.x) / geo.su + U0, V1 - (y - geo.y) / geo.sv] : [(y - geo.y) / geo.su + U0, (x - geo.x) / geo.sv + V0]; }
  function box(e, ua, ub, va, vb) {
    const [x1, y1] = S2(ua, va), [x2, y2] = S2(ub, vb);
    Object.assign(e.style, { left: Math.min(x1, x2) + "px", top: Math.min(y1, y2) + "px", width: Math.abs(x2 - x1) + "px", height: Math.abs(y2 - y1) + "px" });
  }
  function cell(key, cls, html, ua, ub, va, vb) {
    const e = document.createElement("div"); e.className = "cell " + cls; e.innerHTML = html; box(e, ua, ub, va, vb); root.append(e); cells[key] = e; return e;
  }
  function layout() {
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
    land = r.width > r.height * 1.15;
    const pad = 6, W = r.width - pad * 2, H = r.height - pad * 2;
    geo = land ? { su: W / (U1 - U0), sv: H / (V1 - V0), x: pad, y: pad } : { su: H / (U1 - U0), sv: W / (V1 - V0), x: pad, y: pad };
    root.innerHTML = ""; cells = {};
    felt = document.createElement("div"); felt.className = "felt"; root.append(felt);
    Object.assign(felt.style, { left: "0px", top: "0px", width: r.width + "px", height: r.height + "px" });
    if (us) { cell("n:0", "n-green", "0", -1, 0, 0, 1.5); cell("n:00", "n-green", "00", -1, 0, 1.5, 3); }
    else cell("n:0", "n-green", "0", -1, 0, 0, 3);
    for (let row = 0; row < 12; row++) for (let k = 0; k < 3; k++) { const n = 3 * row + k + 1; cell("n:" + n, "n-" + col(n), n, row, row + 1, k, k + 1); }
    for (let k = 0; k < 3; k++) cell("col:" + (k + 1), "out", "2:1", 12, 13, k, k + 1);
    cell("rail", "rail", "", 0, 12, RAIL, 0);
    ["1st 12", "2nd 12", "3rd 12"].forEach((t, d) => cell("dz:" + (d + 1), "out", t, 4 * d, 4 * d + 4, RAIL - 1, RAIL));
    const ev = [["low", "1–18"], ["even", "Even"], ["red", '<i class="dia" style="background:#d8203a"></i>'], ["black", '<i class="dia" style="background:#16161c"></i>'], ["odd", "Odd"], ["high", "19–36"]];
    ev.forEach(([id, t], i) => cell(id, "out", t, 2 * i, 2 * i + 2, V0, RAIL - 1));
    const last = cell("last", "last", "", -1, 0, V0, RAIL); last.style.border = "0";
    cell("corner2", "last", "", 12, 13, V0, 0).style.border = "0";
    chipsEl = document.createElement("div"); root.append(chipsEl);
    tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; root.append(tip);
    paint();
  }
  // which spot is under a point (logical coords); edge bands are ~11 px wide whatever the phone
  function spotAt(u, v) {
    const tu = Math.min(0.3, 11 / geo.su), tv = Math.min(0.3, 11 / geo.sv);
    if (u < U0 || u >= U1 || v < V0 || v >= V1) return null;
    if (u >= 12) return v >= 0 ? "col:" + (Math.floor(v) + 1) : null;
    if (v < 0) {
      if (u < 0) return v >= RAIL && u > -0.3 ? (us ? "tl" : "ff") : null;
      if (v >= RAIL) {
        const r = Math.floor(u), fu = u - r;
        if (fu < tu * 1.4 && r > 0) return "sl:" + (3 * (r - 1) + 1);
        if (fu > 1 - tu * 1.4 && r < 11) return "sl:" + (3 * r + 1);
        if (u < 0.3) return us ? "tl" : "ff";
        return "st:" + (3 * r + 1);
      }
      if (v >= RAIL - 1) return "dz:" + (Math.floor(u / 4) + 1);
      return ["low", "even", "red", "black", "odd", "high"][Math.floor(u / 2)];
    }
    const zeroEdge = (vv) => { // a bet on the line between the zero(s) and the first street
      if (!us) { if (Math.abs(vv - 1) < tv) return "tr:0-1-2"; if (Math.abs(vv - 2) < tv) return "tr:0-2-3"; return "s:0-" + (Math.floor(vv) + 1); }
      if (Math.abs(vv - 1) < tv) return "tr:0-1-2"; if (Math.abs(vv - 1.5) < tv * 0.8) return "tr:0-00-2"; if (Math.abs(vv - 2) < tv) return "tr:00-2-3";
      return vv < 1 ? "s:0-1" : vv < 1.5 ? "s:0-2" : vv < 2 ? "s:00-2" : "s:00-3";
    };
    if (u < 0) {
      if (u > -tu) return zeroEdge(v);
      if (!us) return "n:0";
      if (Math.abs(v - 1.5) < tv) return "s:0-00";
      return v < 1.5 ? "n:0" : "n:00";
    }
    const r = Math.floor(u), k = Math.floor(v), fu = u - r, fv = v - k, n = 3 * r + k + 1;
    const nu = fu < tu ? -1 : fu > 1 - tu && r < 11 ? 1 : 0;
    const nv = fv < tv && k > 0 ? -1 : fv > 1 - tv && k < 2 ? 1 : 0;
    if (nu === -1 && r === 0) return nv ? zeroEdge(k + (nv > 0 ? 1 : 0)) : zeroEdge(v);
    if (nu && nv) { const r0 = nu < 0 ? r - 1 : r, k0 = nv < 0 ? k - 1 : k; return "c:" + (3 * r0 + k0 + 1); }
    if (nu) { const a = nu < 0 ? n - 3 : n; return `s:${a}-${a + 3}`; }
    if (nv) { const a = nv < 0 ? n - 1 : n; return `s:${a}-${a + 1}`; }
    return "n:" + n;
  }
  function anchor(spot) { // logical point where the chip sits
    const [k, a] = spot.split(":"), p = (a || "").split("-").map(num), at = (n) => [Math.floor((n - 1) / 3), (n - 1) % 3];
    if (k === "n") { const n = p[0]; if (n === 0) return us ? [-0.5, 0.75] : [-0.5, 1.5]; if (n === 37) return [-0.5, 2.25]; const [r, c] = at(n); return [r + 0.5, c + 0.5]; }
    if (k === "s") {
      const [x, y] = p;
      if (x === 0 && y === 37) return [-0.5, 1.5];
      if (x === 0 || x === 37) return [0, y === 1 ? 0.5 : y === 3 ? 2.5 : us ? (x === 0 ? 1.25 : 1.75) : 1.5];
      const [r, c] = at(x); return y - x === 1 ? [r + 0.5, c + 1] : [r + 1, c + 0.5];
    }
    if (k === "tr") return [0, a === "0-1-2" ? 1 : a === "0-2-3" || a === "00-2-3" ? 2 : 1.5];
    if (k === "st") return [Math.floor((p[0] - 1) / 3) + 0.5, RAIL / 2];
    if (k === "sl") return [Math.floor((p[0] - 1) / 3) + 1, RAIL / 2];
    if (k === "c") { const [r, c] = at(p[0]); return [r + 1, c + 1]; }
    if (spot === "ff" || spot === "tl") return [0, RAIL / 2];
    if (k === "dz") return [4 * p[0] - 2, RAIL - 0.5];
    if (k === "col") return [12.5, p[0] - 0.5];
    const i = ["low", "even", "red", "black", "odd", "high"].indexOf(spot); return [2 * i + 1, V0 + 0.5];
  }
  function cellsOf(spot) {
    if (cells[spot] && !spot.startsWith("n:") && spot !== "rail") return [cells[spot]];
    return covers(spot).map((n) => cells["n:" + lab(n)]).filter(Boolean);
  }
  function highlight(spot) { for (const e of $$(".hl", root)) e.classList.remove("hl"); if (spot) for (const e of cellsOf(spot)) e.classList.add("hl"); }
  function showTip(spot, x, y) {
    if (!spot) { tip.hidden = true; return; }
    const [n, p] = info(spot); tip.innerHTML = `${esc(n)}<small>${p}</small>`; tip.hidden = false;
    const r = el.getBoundingClientRect(); tip.style.left = clamp(x, 70, r.width - 70) + "px"; tip.style.top = Math.max(40, y) + "px";
  }
  function paint() {
    if (!geo || !chipsEl) return;
    const mine = ctxr.priv.bets || {}, totals = ctxr.pub.totals || {}, res = ctxr.pub.phase === "result" ? ctxr.pub.result : null;
    const wins = new Set((ctxr.priv.result || {}).wins || []);
    let html = "";
    for (const spot of new Set([...Object.keys(totals), ...Object.keys(mine)])) {
      const m = mine[spot] || 0, o = (totals[spot] || 0) - m, [u, v] = anchor(spot), [x, y] = S2(u, v);
      if (m) html += `<div class="chp${wins.has(spot) ? " win" : ""}" style="left:${x}px;top:${y}px;${chipStyle(m)}"><b>${short(m)}</b></div>`;
      else if (o > 0) html += `<div class="oth" style="left:${x}px;top:${y + 8}px">${short(o)}</div>`;
    }
    chipsEl.innerHTML = html;
    for (const e of $$(".won", root)) e.classList.remove("won");
    if (res && res.outcome) { const c = cells["n:" + res.outcome.label]; if (c) c.classList.add("won"); }
    const hist = (ctxr.pub.history || []).slice(-1)[0], last = cells.last;
    if (last) last.innerHTML = hist ? `<span>LAST</span><i class="t-${hist.tone}">${esc(hist.label)}</i>` : "";
  }
  function pt(e) { const r = el.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
  function onDown(e) {
    if (!geo) return;
    try { root.setPointerCapture(e.pointerId); } catch (_) {}
    const [x, y] = pt(e), spot = spotAt(...L2(x, y));
    down = { id: e.pointerId, spot, x, y, long: false };
    highlight(spot); showTip(spot, x, y);
    clearTimeout(lpT);
    if (spot && (ctxr.priv.bets || {})[spot]) lpT = setTimeout(() => { if (down && down.spot === spot) { down.long = true; ctxr.unbet(spot); toast("Chips taken back"); highlight(null); showTip(null); } }, 550);
  }
  function onMove(e) {
    if (!down || e.pointerId !== down.id) return;
    const [x, y] = pt(e), spot = spotAt(...L2(x, y));
    if (spot !== down.spot) { down.spot = spot; clearTimeout(lpT); highlight(spot); if (spot) buzz(4); }
    showTip(spot, x, y);
  }
  function onUp(e) {
    if (!down || e.pointerId !== down.id) return;
    clearTimeout(lpT);
    const d = down; down = null; highlight(null); showTip(null);
    if (e.type === "pointerup" && d.spot && !d.long) ctxr.bet(d.spot);
  }
  return {
    title: "Roulette",
    spinTitle: "The wheel is spinning…",
    resultTitle: (r) => `${r.label} ${r.tone === "green" ? "· zero" : r.tone}`,
    mount(host, c) {
      el = host; ctxr = c; us = ((c.pub.rules || {}).wheel === "american");
      root = document.createElement("div"); root.className = "rt"; el.append(root);
      root.addEventListener("pointerdown", onDown); root.addEventListener("pointermove", onMove);
      root.addEventListener("pointerup", onUp); root.addEventListener("pointercancel", onUp);
      ro = new ResizeObserver(() => layout()); ro.observe(el); layout();
    },
    update(c) {
      ctxr = c; const wantUs = (c.pub.rules || {}).wheel === "american";
      if (wantUs !== us) { us = wantUs; layout(); } else paint();
    },
    unmount() { if (ro) ro.disconnect(); el = root = null; geo = null; },
    replay(rng, rules) { const w = rules.wheel === "american" ? US : EU, i = rng.randint(0, w.length - 1), n = w[i]; return { pocket: i, number: n, label: lab(n), color: col(n) }; },
    describe: (o) => `${o.label} ${o.color}`,
    paytable(c) {
      const e = c.pub.edges || {}, pct = (k) => (e[k] != null ? (e[k] * 100).toFixed(2) + " %" : "");
      const rows = [["Straight (1 number)", "35:1", "straight"], ["Split (2)", "17:1", "split"], ["Street / trio (3)", "11:1", "street"], ["Corner (4)", "8:1", "corner"],
        us ? ["Top line 0-00-1-2-3", "6:1", "top_line"] : ["First four 0-1-2-3", "8:1", "first_four"], ["Six line (6)", "5:1", "six_line"], ["Dozen / column", "2:1", "dozen"], ["Red · black · odd · even · 1–18 · 19–36", "1:1", "red"]];
      return `<table class="pays">${rows.map(([a, b, k]) => `<tr><td>${a}<br><small class="note">house edge ${pct(k)}</small></td><td>${b}</td></tr>`).join("")}</table>` +
        ((c.pub.rules || {}).la_partage ? `<p class="note">La Partage: even-money bets get half back on 0.</p>` : "");
    },
  };
})());

/* =====================================================================================================
   GAME: 7 Up 7 Down — two dice; bet under 7, lucky 7 or over 7.
   ===================================================================================================== */
registerGame("sevens", (() => {
  const PIPS = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };
  const Z = [["down", "Under 7", "▼", "2 · 3 · 4 · 5 · 6"], ["seven", "Lucky 7", "7", "7"], ["up", "Over 7", "▲", "8 · 9 · 10 · 11 · 12"]];
  let el, tray, dice = [], zones = {}, sum, wait, rollT = 0, ctxs;
  function face(d, n) { $$("i", d).forEach((p, i) => p.classList.toggle("on", PIPS[n].includes(i))); }
  return {
    title: "7 Up 7 Down",
    spinTitle: "Rolling…",
    resultTitle: (r) => `${r.label} · ${{ down: "under 7", seven: "lucky 7!", up: "over 7" }[r.tone] || ""}`,
    mount(host, c) {
      el = document.createElement("div"); el.className = "sv"; host.append(el); ctxs = c;
      tray = document.createElement("div"); tray.className = "tray";
      for (let i = 0; i < 2; i++) { const d = document.createElement("div"); d.className = "die"; d.innerHTML = "<i></i>".repeat(9); face(d, i ? 4 : 3); tray.append(d); dice.push(d); }
      sum = document.createElement("div"); sum.className = "sum"; wait = document.createElement("div"); wait.className = "wait"; tray.append(sum, wait);
      const zs = document.createElement("div"); zs.className = "zones";
      for (const [id, name, icon, nums] of Z) {
        const z = document.createElement("button"); z.className = "zone z-" + id; z.dataset.spot = id;
        z.innerHTML = `<span class="zi">${icon}</span><span class="zl">${name}</span><span class="zs">${nums}</span><span class="zp"></span><span class="zb"></span><span class="zo"></span>`;
        z.addEventListener("click", () => ctxs.bet(id));
        let lp = 0; z.addEventListener("pointerdown", () => { clearTimeout(lp); if ((ctxs.priv.bets || {})[id]) lp = setTimeout(() => { ctxs.unbet(id); toast("Chips taken back"); z.dataset.lp = "1"; }, 550); });
        z.addEventListener("pointerup", () => clearTimeout(lp)); z.addEventListener("pointerleave", () => clearTimeout(lp));
        z.addEventListener("click", (e) => { if (z.dataset.lp) { delete z.dataset.lp; e.stopImmediatePropagation(); } }, true);
        zs.append(z); zones[id] = z;
      }
      el.append(tray, zs);
    },
    update(c) {
      ctxs = c; const p = c.pub, ph = p.phase, rules = p.rules || {}, mine = c.priv.bets || {}, totals = p.totals || {};
      const rolling = ph === "locked" || ph === "spinning";
      tray.classList.toggle("rolling", rolling && !REDUCED);
      clearInterval(rollT);
      if (rolling) rollT = setInterval(() => dice.forEach((d) => face(d, 1 + Math.floor(Math.random() * 6))), 110);
      const res = ph === "result" && p.result ? p.result : null;
      if (res) { dice.forEach((d, i) => face(d, res.outcome.dice[i])); sum.textContent = res.outcome.sum; } else sum.textContent = "";
      const last = (p.history || []).slice(-1)[0];
      if (!res && !rolling && last && last.outcome) dice.forEach((d, i) => face(d, last.outcome.dice[i]));
      wait.textContent = rolling ? "Watch the panel!" : ph === "betting" ? "Bet on where the next roll lands" : "";
      for (const [id] of Z) {
        const z = zones[id], m = mine[id] || 0, o = (totals[id] || 0) - m;
        $(".zp", z).textContent = id === "seven" ? `${rules.seven_pays || 4}:1` : "1:1";
        $(".zb", z).innerHTML = m ? `<span class="chp" style="${chipStyle(m)}"><b>${short(m)}</b></span><b class="num">${fmt(m)}</b>` : "";
        $(".zo", z).textContent = o > 0 ? `others ${fmt(o)}` : "";
        z.classList.toggle("won", !!res && res.tone === id); z.classList.toggle("lost", !!res && res.tone !== id);
      }
    },
    unmount() { clearInterval(rollT); dice = []; zones = {}; },
    replay(rng) { const a = rng.randint(1, 6), b = rng.randint(1, 6), s = a + b; return { dice: [a, b], sum: s, zone: s < 7 ? "down" : s === 7 ? "seven" : "up" }; },
    describe: (o) => `${o.dice[0]} + ${o.dice[1]} = ${o.sum}`,
    paytable(c) {
      const e = c.pub.edges || {}, pct = (k) => (e[k] != null ? (e[k] * 100).toFixed(2) + " %" : ""), sp = (c.pub.rules || {}).seven_pays || 4;
      return `<table class="pays"><tr><td>Under 7 (2–6)<br><small class="note">house edge ${pct("down")}</small></td><td>1:1</td></tr><tr><td>Lucky 7<br><small class="note">house edge ${pct("seven")}</small></td><td>${sp}:1</td></tr><tr><td>Over 7 (8–12)<br><small class="note">house edge ${pct("up")}</small></td><td>1:1</td></tr></table>`;
    },
  };
})());

/* =====================================================================================================
   BEGIN cards & wheels block: Texas Hold'em · Teen Patti · Andar Bahar · Big Six (rules in deskdot/casino/games/).
   PC.* are this block's helpers (playing cards, the deck replay, the player-vs-player chrome).
   ===================================================================================================== */
const PC = (() => {
  const SUIT = { S: "♠", H: "♥", D: "♦", C: "♣" }, SUITN = { S: "spades", H: "hearts", D: "diamonds", C: "clubs" };
  const RK = { 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A" };
  const rk = (c) => (c[0] === "T" ? "10" : c[0]);
  function card(code, cls = "") {
    if (!code) return `<span class="pc back ${cls}" aria-label="face-down card"></span>`;
    return `<span class="pc ${"HD".includes(code[1]) ? "red" : ""} ${cls}" aria-label="${rk(code)} of ${SUITN[code[1]]}"><b>${rk(code)}</b><i>${SUIT[code[1]]}</i></span>`;
  }
  const empty = () => `<span class="pc empty" aria-hidden="true"></span>`;
  /** cards.new_deck() order (suits S H D C, ranks 2..A) shuffled exactly like fair.Rng.shuffle (Fisher–Yates from the top) */
  function deck(rng) {
    const d = [];
    for (const s of "SHDC") for (let r = 2; r <= 14; r++) d.push((RK[r] || String(r)) + s);
    for (let i = d.length - 1; i > 0; i--) { const j = rng.randint(0, i); const t = d[i]; d[i] = d[j]; d[j] = t; }
    return d;
  }
  const cap = (s) => String(s || "").replace(/^./, (c) => c.toUpperCase());
  /** the player strip: everyone in the hand, their stack, what they did; `extra(seat)` adds a tag */
  function seats(c, extra) {
    const t = (c.pub.table || {}), list = t.seats || [];
    if (!list.length) {
      const sit = new Set(c.pub.sitting || []);
      return (c.pub.players || []).filter((p) => p.online && p.seat !== "host" || sit.has(p.seat)).map((p) =>
        `<div class="pv-seat ${sit.has(p.seat) ? "" : "out"} ${p.seat === S.seat ? "me" : ""}"><b style="color:${esc(p.color)}">${esc(p.name)}</b><small>${fmt(p.credits)}</small><small>${sit.has(p.seat) ? "in" : "sitting out"}</small></div>`).join("");
    }
    return list.map((s) => {
      const tag = extra ? extra(s) : "";
      return `<div class="pv-seat ${s.turn || t.turn_seat === s.seat ? "turn" : ""} ${s.folded ? "out" : ""} ${s.seat === S.seat ? "me" : ""}">${tag}<b style="color:${esc(s.color)}">${esc(s.name)}</b><small>${fmt(s.stack)} left</small><small>${s.folded ? (s.last || "out").toLowerCase() : s.allin ? "ALL-IN" : s.last ? s.last.toLowerCase() + (s.total ? " · " + fmt(s.total) : "") : "in " + fmt(s.total)}</small></div>`;
    }).join("");
  }
  /** a turn clock that runs smoothly between state pushes */
  function clock(el, left, span) {
    const at = performance.now();
    clearInterval(el._t);
    const tick = () => { const l = Math.max(0, left - (performance.now() - at) / 1000); const i = el.firstElementChild; if (i) i.style.width = (100 * Math.min(1, l / span)) + "%"; el.classList.toggle("hurry", l <= 5); };
    tick(); el._t = setInterval(tick, 250);
  }
  /** the PvP tables have no chip rack: hide the core dock while mounted, and say what the table is doing */
  function chrome(on) { const d = $(".dock"); if (d) d.hidden = on; }
  function phase(title, sub) { if (title != null) { $("#ph-title").textContent = title; $("#ph-sub").textContent = sub; } $("#lockb").hidden = true; $("#s-table").classList.remove("closed"); }
  function results(c, label) {
    const t = c.pub.table || {}, wins = new Map((t.winners || []).map((w) => [w.seat, w])), shown = t.showdown || {};
    const rows = (t.seats || []).filter((s) => wins.has(s.seat) || shown[String(s.seat)]);
    return `<div class="pv-res">${rows.map((s) => { const w = wins.get(s.seat), cs = shown[String(s.seat)] || [];
      return `<div class="r ${w ? "rw" : ""}">${cs.map((x) => card(x)).join("")}<b style="color:${esc(s.color)}">${esc(s.name)}</b><small class="num">${w ? "+" + fmt(w.won) : ""} ${esc(label(s, w))}</small></div>`; }).join("")}</div>`;
  }
  return { card, empty, deck, cap, seats, clock, chrome, phase, results };
})();

/* GAME: Texas Hold'em — own hole cards, the board, the pot, fold / check / call / raise (slider + ½ pot, pot, all-in). */
registerGame("holdem", (() => {
  let root, c, sig = "", raiseTo = 0, open = false, betKey = "";
  const HAND = { "high card": "High card", pair: "Pair", "two pair": "Two pair", "three of a kind": "Three of a kind", straight: "Straight", flush: "Flush", "full house": "Full house", "four of a kind": "Four of a kind", "straight flush": "Straight flush", "royal flush": "Royal flush" };
  function presets(p, t) {
    const pot = t.pot || 0, call = p.to_call || 0, cur = t.cur_bet || 0, lo = p.min_to || 0, hi = p.max_to || 0;
    const clampTo = (v) => Math.max(lo, Math.min(hi, Math.round(v)));
    return [["Min", lo], ["½ pot", clampTo(cur + (pot + call) / 2)], ["Pot", clampTo(cur + pot + call)], ["All-in", hi]];
  }
  function act(p, t) {
    const ops = p.ops || [];
    if (!p.my_turn || !ops.length) return "";
    const word = p.bet_word === "bet" ? "Bet" : "Raise";
    const call = ops.includes("call") ? `<button class="pv-btn call" data-op="call">Call<small>${fmt(p.to_call)}${p.to_call >= (p.max_to - p.my_bet) ? " · all-in" : ""}</small></button>` : `<button class="pv-btn call" data-op="check">Check<small>free</small></button>`;
    const canRaise = ops.includes("raise"), key = `${t.hand}:${t.street}:${t.cur_bet}`;
    if (key !== betKey) { betKey = key; raiseTo = p.min_to || p.max_to; }
    if (!raiseTo || raiseTo < p.min_to || raiseTo > p.max_to) raiseTo = p.min_to || p.max_to;
    let html = `<div class="pv-timer" id="he-tm"><i></i></div><div class="pv-btns"><button class="pv-btn fold" data-op="fold">Fold</button>${call}`;
    html += canRaise ? `<button class="pv-btn raise" data-op="open">${word}<small>${open ? "▲" : "to " + fmt(raiseTo)}</small></button>` : ops.includes("allin") ? `<button class="pv-btn raise" data-op="allin">All-in<small>${fmt(p.max_to)}</small></button>` : `<button class="pv-btn" disabled>${word}</button>`;
    html += `</div>`;
    if (canRaise && open) {
      html += `<div class="pv-slide"><div class="pv-amt"><span><small>${word} to </small><span id="he-amt">${fmt(raiseTo)}</span></span><small>min ${fmt(p.min_to)} · max ${fmt(p.max_to)}</small></div>
        <input type="range" id="he-rng" min="${p.min_to}" max="${p.max_to}" step="1" value="${raiseTo}" aria-label="${word} amount">
        <div class="pv-pre">${presets(p, t).map(([n, v]) => `<button data-to="${v}">${n}</button>`).join("")}</div>
        <button class="pv-btn raise" data-op="raise">${word} to <span id="he-amt2">${fmt(raiseTo)}</span></button></div>`;
    }
    return html;
  }
  function render() {
    const pub = c.pub, p = c.priv, t = pub.table || {}, ph = pub.phase;
    const inHand = !!(p.cards && p.cards.length) && ph !== "betting";
    let hand = "";
    if (inHand) hand = `<div class="pv-hand"><div class="pv-row">${p.cards.map((x) => PC.card(x, p.folded ? "dim" : "")).join("")}</div><div class="nm"><b>${p.folded ? "Folded" : HAND[p.hand] || "Your hole cards"}</b><small>${p.folded ? "Watch the rest of the hand" : p.hand ? "Best five with the board" : "Only you can see these"}</small></div></div>`;
    const board = t.board || [];
    const pots = t.pots || [];
    const felt = `<div class="pv-felt"><div class="pv-pot"><small>POT</small>${fmt(t.pot || 0)}</div>${pots.length > 1 ? `<div class="pv-sub">${pots.map((x, i) => (i ? "side " : "main ") + fmt(x.amount)).join(" · ")}</div>` : ""}<div class="pv-row">${[0, 1, 2, 3, 4].map((i) => (board[i] ? PC.card(board[i], (pub.phase === "result" && ((t.winners || [])[0] || {}).best || []).includes(board[i]) ? "hi" : "") : PC.empty())).join("")}</div><div class="pv-sub">Blinds ${(t.blinds || []).map(fmt).join(" / ")}${t.cur_bet ? " · bet " + fmt(t.cur_bet) : ""}</div></div>`;
    let below = "";
    if (ph === "betting" || ph === "idle") {
      const n = (pub.sitting || []).length;
      below = `<div class="pv-wait">${n >= 2 ? (pub.ends_in != null ? `Next hand in ${pub.ends_in}s` : "Dealing soon") : "Waiting for at least two players"} · ${n} in · you need ${fmt(pub.buy_in || 0)} to play</div>
        <button class="pv-sit ${p.sitting ? "pill" : "go"}" data-op="sit">${p.sitting ? "Sit out next hand" : "Deal me in"}</button>`;
    } else if (ph === "result") below = PC.results(c, (s, w) => (w && w.hand ? HAND[w.hand] : w ? "takes the pot" : ""));
    else if (inHand && p.my_turn) below = `<div class="pv-act">${act(p, t)}</div>`;
    else if (ph === "action" || ph === "dealing") { const ts = (t.seats || []).find((s) => s.seat === t.turn_seat); below = `<div class="pv-wait">${ts ? `${esc(ts.name)} is thinking…` : "Dealing…"}${inHand ? "" : " · you're not in this hand"}</div>`; }
    const html = `<div class="pv-seats">${PC.seats(c, (s) => (s.seat === t.button_seat ? `<span class="tag">D</span>` : s.allin ? `<span class="tag ai">AI</span>` : ""))}</div>${felt}${hand}${below}`;
    if (html !== sig) { sig = html; root.innerHTML = html; const tm = $("#he-tm", root); if (tm) PC.clock(tm, p.turn_in || 0, (pub.house || {}).turn_seconds || 20); }
    const me = (t.seats || []).find((s) => s.seat === S.seat);
    if (ph === "action" || ph === "dealing") PC.phase(p.my_turn ? "Your move" : "Hold'em", p.my_turn ? (p.to_call ? `${fmt(p.to_call)} to call` : "Check or bet") : me && !me.folded ? `Your stack ${fmt(me.stack)}` : "Watch the panel");
    else if (ph === "betting") PC.phase("Next hand", "Blinds " + ((t.blinds || []).map(fmt).join(" / ")));
    else PC.phase(null);
  }
  function onClick(e) {
    const b = e.target.closest("[data-op],[data-to]"); if (!b || b.disabled) return;
    if (b.dataset.to) { raiseTo = Number(b.dataset.to); sig = ""; render(); buzz(6); return; }
    const op = b.dataset.op;
    if (op === "open") { open = !open; sig = ""; render(); buzz(6); return; }
    if (op === "sit") { c.send("sit", { on: !c.priv.sitting }); buzz(10); return; }
    if (op === "raise") c.send("raise", { amount: raiseTo });
    else c.send(op);
    open = false; buzz(op === "fold" ? [8, 30, 8] : 14);
  }
  function onInput(e) { if (e.target.id !== "he-rng") return; raiseTo = Number(e.target.value); for (const id of ["he-amt", "he-amt2"]) { const x = $("#" + id, root); if (x) x.textContent = fmt(raiseTo); } }
  return {
    title: "Texas Hold'em",
    resultTitle: (r) => (r.winners && r.winners[0] ? `${r.winners[0].name}${r.winners.length > 1 ? " +" + (r.winners.length - 1) : ""} · ${r.hand ? HAND[r.hand] || r.hand : "uncontested"}` : r.hand ? HAND[r.hand] : "Hand over"),
    mount(host, cx) { c = cx; sig = ""; root = document.createElement("div"); root.className = "pv"; host.append(root); root.addEventListener("click", onClick); root.addEventListener("input", onInput); PC.chrome(true); render(); },
    update(cx) { c = cx; if (!c.priv.my_turn) open = false; render(); },
    unmount() { PC.chrome(false); root = null; },
    replay(rng) { return { deck: PC.deck(rng).join(" ") }; },
    describe: (o) => `deck ${o.deck.split(" ").slice(0, 6).join(" ")} …`,
    paytable(cx) { const r = cx.pub.rules || {}; return `<table class="pays"><tr><td>Blinds</td><td>${fmt(r.small_blind)} / ${fmt(r.big_blind)}</td></tr><tr><td>Blinds double every</td><td>${r.blind_up_every ? r.blind_up_every + " hands" : "never"}</td></tr><tr><td>Rake</td><td>${r.rake_percent ? r.rake_percent + " %" : "none"}</td></tr></table><p class="note">No-limit: raise at least the last raise; all-in any time. Side pots for every all-in; ties split, odd chip to the first winner left of the button. Timer: check if free, else fold.</p>`; },
  };
})());

/* GAME: Teen Patti — blind / seen, see cards, chaal, raise, pack, show, sideshow (accept / refuse). */
registerGame("teenpatti", (() => {
  let root, c, sig = "", shown = false;
  const HAND = { trail: "Trail", "pure sequence": "Pure sequence", sequence: "Sequence", colour: "Colour", pair: "Pair", "high card": "High card" };
  function render() {
    const pub = c.pub, p = c.priv, t = pub.table || {}, ph = pub.phase, ops = p.ops || [];
    const inHand = p.in_hand && ph !== "betting";
    let hand = "";
    if (inHand) {
      const cs = p.cards && p.cards.length ? p.cards : [null, null, null];
      const flip = p.cards && !shown; if (p.cards) shown = true;
      hand = `<div class="pv-hand"><div class="pv-row">${cs.map((x) => PC.card(x, (p.folded ? "dim " : "") + (flip ? "flip" : ""))).join("")}</div><div class="nm"><b>${p.folded ? "Packed" : p.seen ? HAND[p.hand] || "Seen" : "Playing blind"}</b><small>${p.seen ? "Seen: chaal is 2× the stake" : `Blind: chaal is 1× · ${p.blind_left} blind bet${p.blind_left === 1 ? "" : "s"} left`}</small></div></div>`;
      if (ops.includes("see") && !p.folded) hand += `<button class="pv-btn see" data-op="see">See cards<small>then you play seen (2×)</small></button>`;
      for (const [seat, cs2] of Object.entries(p.peeks || {})) { const s = (t.seats || []).find((x) => String(x.seat) === seat); hand += `<div class="pv-wait">Sideshow with ${esc(s ? s.name : "seat " + seat)}: ${cs2.map((x) => PC.card(x)).join(" ")}</div>`; }
    }
    const felt = `<div class="pv-felt"><div class="pv-pot"><small>POT</small>${fmt(t.pot || 0)}</div><div class="pv-sub">Stake ${fmt(t.stake || 0)} · boot ${fmt(t.boot || 0)} · blind chaal ${fmt(t.stake || 0)} / seen ${fmt(2 * (t.stake || 0))}</div></div>`;
    let below = "";
    if (ph === "betting" || ph === "idle") {
      const n = (pub.sitting || []).length;
      below = `<div class="pv-wait">${n >= 2 ? (pub.ends_in != null ? `Next hand in ${pub.ends_in}s` : "Dealing soon") : "Waiting for at least two players"} · ${n} in · boot ${fmt(pub.buy_in || 0)}</div>
        <button class="pv-sit ${p.sitting ? "pill" : "go"}" data-op="sit">${p.sitting ? "Sit out next hand" : "Deal me in"}</button>`;
    } else if (ph === "result") below = PC.results(c, (s, w) => { const h = (t.hands || {})[String(s.seat)]; return h ? HAND[h] : w ? "everyone else packed" : ""; });
    else if (ops.includes("accept")) below = `<div class="pv-ask">${esc(p.sideshow_from)} asks you for a sideshow — compare cards privately; the lower hand packs (equal: they pack).<div class="pv-timer" id="tp-tm"><i></i></div><div class="pv-btns"><button class="pv-btn call" data-op="accept">Accept</button><button class="pv-btn fold" data-op="refuse">Refuse</button></div></div>`;
    else if (p.my_turn) {
      const b = (op, cls, label, amt) => (ops.includes(op) ? `<button class="pv-btn ${cls}" data-op="${op}">${label}<small>${amt != null ? fmt(amt) : ""}</small></button>` : "");
      below = `<div class="pv-act"><div class="pv-timer" id="tp-tm"><i></i></div><div class="pv-btns">${b("pack", "fold", "Pack")}${b("chaal", "call", p.allin ? "All-in" : "Chaal", p.chaal)}${b("raise", "raise", "Raise", p.raise)}${b("show", "show", "Show", p.show)}${b("sideshow", "show", "Sideshow", p.sideshow)}</div>${ops.includes("sideshow") ? `<p class="note">Sideshow asks ${esc(p.sideshow_name)} to compare.</p>` : ""}</div>`;
    } else if (ph === "action" || ph === "dealing") {
      const ts = (t.seats || []).find((s) => s.seat === t.turn_seat), ss = t.sideshow;
      below = `<div class="pv-wait">${ss ? "Sideshow asked — waiting for the answer" : ts ? `${esc(ts.name)} is thinking…` : "Dealing…"}</div>`;
    }
    const html = `<div class="pv-seats">${PC.seats(c, (s) => (s.allin ? `<span class="tag ai">AI</span>` : s.seen ? `<span class="tag sn">S</span>` : `<span class="tag bl">B</span>`))}</div>${felt}${hand}${below}`;
    if (html !== sig) { sig = html; root.innerHTML = html; const tm = $("#tp-tm", root); if (tm) PC.clock(tm, p.turn_in || 0, (pub.house || {}).turn_seconds || 20); }
    if (ph === "action" || ph === "dealing") PC.phase(ops.includes("accept") ? "Sideshow?" : p.my_turn ? "Your move" : "Teen Patti", p.my_turn ? `Chaal ${fmt(p.chaal)}${p.seen ? " (seen)" : " (blind)"}` : `Pot ${fmt(t.pot || 0)} · stake ${fmt(t.stake || 0)}`);
    else if (ph === "betting") PC.phase("Next hand", `Boot ${fmt((pub.rules || {}).boot || 0)}`);
    else PC.phase(null);
    if (ph === "betting") shown = false;
  }
  function onClick(e) {
    const b = e.target.closest("[data-op]"); if (!b || b.disabled) return;
    const op = b.dataset.op;
    if (op === "sit") c.send("sit", { on: !c.priv.sitting }); else c.send(op);
    buzz(op === "pack" || op === "refuse" ? [8, 30, 8] : 14);
  }
  return {
    title: "Teen Patti",
    resultTitle: (r) => (r.winners && r.winners[0] ? `${r.winners[0].name} · ${r.hand ? HAND[r.hand] || r.hand : "all others packed"}` : r.hand ? HAND[r.hand] : "Hand over"),
    mount(host, cx) { c = cx; sig = ""; root = document.createElement("div"); root.className = "pv"; host.append(root); root.addEventListener("click", onClick); PC.chrome(true); render(); },
    update(cx) { c = cx; render(); },
    unmount() { PC.chrome(false); root = null; },
    replay(rng) { return { deck: PC.deck(rng).join(" ") }; },
    describe: (o) => `deck ${o.deck.split(" ").slice(0, 6).join(" ")} …`,
    paytable(cx) { const r = cx.pub.rules || {}; return `<table class="pays"><tr><td>Boot</td><td>${fmt(r.boot)}</td></tr><tr><td>Chaal limit</td><td>${fmt(r.chaal_limit)}</td></tr><tr><td>Pot limit (forces a show)</td><td>${fmt(r.pot_limit)}</td></tr><tr><td>Blind bets before you must see</td><td>${r.max_blind_rounds}</td></tr></table><p class="note">Trail › pure sequence › sequence › colour › pair › high card. A-K-Q is the top sequence, A-2-3 the second. Show only with two left (blind pays 1×, seen 2×; a seen player can't show a blind one; equal hands: the one who paid loses). Sideshow: seen players only, with the previous player; equal hands: the asker packs.</p>`; },
  };
})());

/* house games: big tap zones with the payout, own chips, others' totals (shared by Andar Bahar and Big Six) */
function hzZone(c, spot, color, big, label, extra = "") {
  const sp = ((c.pub.spots || []).find((s) => s.id === spot) || {}), pays = sp.pays ? sp.pays.replace(/^(\d+):(\d+)$/, (m, a, b) => (b === "1" ? a + ":1" : (Number(a) / Number(b)).toFixed(Number(a) % Number(b) ? 1 : 0) + ":1")) : "";
  const m = (c.priv.bets || {})[spot] || 0, o = ((c.pub.totals || {})[spot] || 0) - m;
  return `<button class="hz-z" data-spot="${spot}" style="--zc:${color}">${extra}<span class="n">${big}</span><span class="l">${label}</span><span class="p">${pays}</span><span class="m">${m ? `<span class="chp" style="${chipStyle(m)}"><b>${short(m)}</b></span> ${fmt(m)}` : ""}</span><span class="o">${o > 0 ? "others " + fmt(o) : ""}</span></button>`;
}
function hzBind(root, getC) {
  root.addEventListener("click", (e) => { const z = e.target.closest("[data-spot]"); if (!z) return; if (z.dataset.lp) { delete z.dataset.lp; return; } getC().bet(z.dataset.spot); });
  let lp = 0;
  root.addEventListener("pointerdown", (e) => { const z = e.target.closest("[data-spot]"); clearTimeout(lp); if (z && (getC().priv.bets || {})[z.dataset.spot]) lp = setTimeout(() => { getC().unbet(z.dataset.spot); toast("Chips taken back"); z.dataset.lp = "1"; }, 550); });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) root.addEventListener(ev, () => clearTimeout(lp));
}
function hzMark(root, c, winning) {
  const res = c.pub.phase === "result" && c.pub.result;
  root.style.paddingTop = c.pub.phase === "betting" ? "" : "50px"; // room for the core's "bets locked" banner
  for (const z of $$("[data-spot]", root)) { z.classList.toggle("won", !!res && winning.has(z.dataset.spot)); z.classList.toggle("lost", !!res && !winning.has(z.dataset.spot)); }
}

/* GAME: Andar Bahar — the joker, Andar / Bahar zones and the card-count side bets. */
registerGame("andarbahar", (() => {
  let root, c;
  const BANDS = [[1, 5], [6, 10], [11, 15], [16, 25], [26, 30], [31, 35], [36, 40], [41, 49]];
  function render() {
    const p = c.pub, r = p.rules || {}, res = p.phase === "result" ? p.result : null, o = res && res.outcome;
    const last = (p.history || []).slice(-1)[0], show = o || (last && last.outcome);
    const top = show ? `${PC.card(show.joker)}<div class="lbl">${o ? "This round's joker" : "Last joker"}<br>${show.count} card${show.count > 1 ? "s" : ""} · <b style="color:${show.winner === "andar" ? "#5aa8ff" : "#ff5a8a"}">${show.winner.toUpperCase()}</b></div>` : `${PC.card(null)}<div class="lbl">The joker is turned when betting closes.<br>Its rank decides the game.</div>`;
    const first = r.first || "andar";
    let html = `<div class="hz-top">${top}</div><div class="hz-grid" style="grid-template-columns:1fr 1fr">${hzZone(c, "andar", "#1b5bd8", "A", "Andar" + (first === "andar" ? " · first card" : ""))}${hzZone(c, "bahar", "#c81f53", "B", "Bahar" + (first === "bahar" ? " · first card" : ""))}</div>`;
    if (r.side_bets !== false) html += `<div class="hz-h">How many cards are dealt?</div><div class="hz-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">${BANDS.map(([a, b]) => hzZone(c, `c:${a}-${b}`, "#5b3a8c", `${a}–${b}`, "cards")).join("")}</div>`;
    root.innerHTML = html;
    const win = new Set();
    if (o) { win.add(o.winner); for (const [a, b] of BANDS) if (o.count >= a && o.count <= b) win.add(`c:${a}-${b}`); }
    hzMark(root, c, win);
    if (p.phase === "spinning" || p.phase === "dealing") $("#ph-title").textContent = "Dealing…";
  }
  return {
    title: "Andar Bahar",
    spinTitle: "Dealing…",
    resultTitle: (r) => `${(r.outcome || {}).winner === "andar" ? "Andar" : "Bahar"} wins · ${(r.outcome || {}).count} cards`,
    mount(host, cx) { c = cx; root = document.createElement("div"); root.className = "hz"; host.append(root); hzBind(root, () => c); render(); },
    update(cx) { c = cx; render(); },
    unmount() { root = null; },
    replay(rng, rules) {
      const d = PC.deck(rng), joker = d[0], dealt = [];
      for (const x of d.slice(1)) { dealt.push(x); if (x[0] === joker[0]) break; }
      const first = rules.first || "andar", other = first === "andar" ? "bahar" : "andar";
      return { joker, cards: dealt, first, winner: dealt.length % 2 ? first : other, count: dealt.length };
    },
    describe: (o) => `joker ${o.joker} · ${o.winner} after ${o.count} cards`,
    paytable(cx) {
      const e = cx.pub.edges || {}, pct = (k) => (e[k] != null ? (e[k] * 100).toFixed(2) + " %" : ""), f = (cx.pub.rules || {}).first || "andar";
      return `<table class="pays"><tr><td>${PC.cap(f)} (gets the first card, wins 51.5 %)<br><small class="note">house edge ${pct(f)}</small></td><td>0.9:1</td></tr><tr><td>${PC.cap(f === "andar" ? "bahar" : "andar")}<br><small class="note">house edge ${pct(f === "andar" ? "bahar" : "andar")}</small></td><td>1:1</td></tr>
        ${(cx.pub.spots || []).filter((s) => s.kind === "count").map((s) => `<tr><td>${s.label}</td><td>${s.pays}</td></tr>`).join("")}</table><p class="note">Card-count bets: fair odds less about 5–7 % (worst band ${pct("count")}).</p>`;
    },
  };
})());

/* GAME: Big Six — the money wheel: one zone per symbol with its payout and how many segments it has. */
registerGame("bigsix", (() => {
  let root, c;
  const WHEEL = ["joker", "2", "1", "1", "2", "1", "5", "2", "1", "1", "10", "2", "1", "5", "2", "1", "1", "20", "2", "1", "1", "5", "2", "1", "10", "2", "1", "logo", "1", "5", "2", "1", "2", "1", "1", "2", "5", "10", "1", "1", "2", "1", "1", "2", "20", "5", "1", "2", "1", "1", "2", "10", "5", "1"];
  const Z = [["s1", "1", "#c99a00", 24], ["s2", "2", "#1e5fd8", 15], ["s5", "5", "#0b9a52", 7], ["s10", "10", "#8a3ad6", 4], ["s20", "20", "#d8521a", 2], ["joker", "🃏", "#c8237a", 1], ["logo", "★", "#a08a3a", 1]];
  const SYM = { s1: "1", s2: "2", s5: "5", s10: "10", s20: "20", joker: "joker", logo: "logo" };
  function render() {
    const p = c.pub, res = p.phase === "result" ? p.result : null;
    const last = (p.history || []).slice(-1)[0];
    const top = `<div class="lbl" style="font-size:14px">${res ? `The wheel stopped on <b style="font-size:22px;color:var(--gold)">${esc(res.outcome.symbol.toUpperCase())}</b>` : p.phase === "spinning" || p.phase === "locked" ? "The wheel is spinning — watch the panel!" : last ? `Last spin: <b style="color:var(--gold)">${esc(last.outcome.symbol.toUpperCase())}</b><br>54 segments · pick a symbol` : "54 segments · pick a symbol"}</div>`;
    root.innerHTML = `<div class="hz-top">${top}</div><div class="hz-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">${Z.map(([id, big, col, n]) => hzZone(c, id, col, big, n > 1 ? `${n} segments` : `${id === "joker" ? "Joker" : "Logo"} · 1 of 54`)).join("")}</div>`;
    const win = new Set(); if (res) for (const [id] of Z) if (SYM[id] === res.outcome.symbol) win.add(id);
    hzMark(root, c, win);
  }
  return {
    title: "Big Six",
    spinTitle: "The wheel is spinning…",
    resultTitle: (r) => `${String((r.outcome || {}).symbol || "").toUpperCase()} on the wheel`,
    mount(host, cx) { c = cx; root = document.createElement("div"); root.className = "hz"; host.append(root); hzBind(root, () => c); render(); },
    update(cx) { c = cx; render(); },
    unmount() { root = null; },
    replay(rng) { const i = rng.randint(0, WHEEL.length - 1); return { segment: i, symbol: WHEEL[i] }; },
    describe: (o) => `segment ${o.segment} · ${o.symbol}`,
    paytable(cx) {
      const e = cx.pub.edges || {}, pct = (k) => (e[k] != null ? (e[k] * 100).toFixed(2) + " %" : "");
      return `<table class="pays">${Z.map(([id, big, , n]) => `<tr><td>${big} · ${n} of 54<br><small class="note">house edge ${pct("bigsix_" + SYM[id])}</small></td><td>${{ s1: "1:1", s2: "2:1", s5: "5:1", s10: "10:1", s20: "20:1" }[id] || "40:1"}</td></tr>`).join("")}</table>`;
    },
  };
})());
/* ===== END cards & wheels block ===== */

/* =====================================================================================================
   BEGIN house games block: Blackjack · Baccarat · Slots (rules in deskdot/casino/games/).
   HG.* are this block's helpers; cards reuse PC.card from the block above. Every replay() mirrors the Python
   draw order exactly (cards.DealingShoe: a lazy Fisher–Yates read from the bottom of the shoe).
   ===================================================================================================== */
const HG = (() => {
  const RK = { 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A" };
  const KINDS = []; // cards.CARD_KINDS: suits S H D C, ranks 2..A
  for (const s of "SHDC") for (let r = 2; r <= 14; r++) KINDS.push((RK[r] || String(r)) + s);
  /** cards.DealingShoe: `comp` is one digit per card kind; dealing card k = one Fisher–Yates step from the bottom */
  function shoe(comp, decks, rng) {
    let counts = [...String(comp)].map(Number), cards = [];
    const drawn = [];
    const expand = () => { cards = []; KINDS.forEach((k, i) => { for (let n = 0; n < counts[i]; n++) cards.push(k); }); };
    if (counts.length !== 52 || counts.some((n) => !(n >= 0 && n <= decks))) throw new Error("bad shoe composition");
    expand();
    return {
      draw() {
        if (!cards.length) { const on = {}; for (const c of drawn) on[c] = (on[c] || 0) + 1; counts = KINDS.map((k) => decks - (on[k] || 0)); expand(); }
        const i = cards.length - 1, j = rng.randint(0, i), c = cards[j];
        cards[j] = cards[i]; cards.pop(); drawn.push(c); return c;
      },
    };
  }
  const full = (decks) => String(decks).repeat(52);
  const chip = (n) => `<span class="hg-chp" style="${chipStyle(n)}"><b>${short(n)}</b></span>`;
  /** a smooth turn clock between state pushes */
  function clock(el, left, span) {
    if (!el) return;
    const at = performance.now();
    clearInterval(el._t);
    const tick = () => { const l = Math.max(0, left - (performance.now() - at) / 1000), i = el.firstElementChild; if (i) i.style.width = (100 * Math.min(1, l / span)) + "%"; el.classList.toggle("hurry", l <= 5); };
    tick(); el._t = setInterval(tick, 250);
  }
  /** tap = bet the chip, long-press = take the chips back (same gestures as the other tables) */
  function zone(el, c, id) {
    let lp = 0;
    el.addEventListener("pointerdown", () => { clearTimeout(lp); if ((c().priv.bets || {})[id]) lp = setTimeout(() => { c().unbet(id); toast("Chips taken back"); el.dataset.lp = "1"; }, 550); });
    for (const ev of ["pointerup", "pointerleave", "pointercancel"]) el.addEventListener(ev, () => clearTimeout(lp));
    el.addEventListener("click", () => { if (el.dataset.lp) { delete el.dataset.lp; return; } c().bet(id); });
  }
  const pct = (c, k) => { const e = (c.pub.edges || {})[k]; return e != null ? (e * 100).toFixed(2) + " %" : ""; };
  return { shoe, full, chip, clock, zone, pct, KINDS };
})();

/* GAME: Blackjack — the dealer, everyone's hands (public), your hands big, legal moves only, bet before the deal. */
registerGame("blackjack", (() => {
  let root, c, sig = "", myTurnWas = false, lastStatus = "";
  const MV = { hit: ["Hit", "bj-hit"], stand: ["Stand", "bj-stand"], double: ["Double", "bj-dbl"], split: ["Split", "bj-split"], surrender: ["Surrender", "bj-sur"], insurance: ["Insure", "bj-ins"], no_insurance: ["No thanks", "bj-sur"] };
  const cardH = (x) => PC.card(x === "??" ? null : x);
  const tot = (h) => !h.cards.length ? "" : h.bj ? "BJ" : h.soft ? `${h.total - 10}/${h.total}` : String(h.total);
  function rulesLine(r) {
    return `${r.decks || 6} decks · BJ pays ${r.blackjack_pays || "3:2"} · dealer ${r.soft17 === "hit" ? "hits" : "stands on"} soft 17${r.surrender === "late" ? " · surrender" : ""}${r.dealer_peek === false ? " · no peek" : ""}`;
  }
  function badge(h, seat) {
    if (seat.net != null && h === seat.hands[seat.hands.length - 1] && seat.hands.length === 1) {
      return seat.net > 0 ? (h.bj ? `<span class="bj-badge bjk">BLACKJACK +${fmt(seat.net)}</span>` : `<span class="bj-badge win">WIN +${fmt(seat.net)}</span>`) : seat.net < 0 ? `<span class="bj-badge lose">${h.status === "surrender" ? "SURRENDERED" : h.status === "bust" ? "BUST" : "LOSE"}</span>` : `<span class="bj-badge push">PUSH</span>`;
    }
    if (h.bj) return `<span class="bj-badge bjk">BLACKJACK</span>`;
    if (h.status === "bust") return `<span class="bj-badge bust">BUST</span>`;
    if (h.status === "surrender") return `<span class="bj-badge">SURRENDERED</span>`;
    if (h.doubled) return `<span class="bj-badge">DOUBLED</span>`;
    return h.status === "stand" ? `<span class="bj-badge">STAND</span>` : "";
  }
  function seatChip(s, t) {
    const h = s.hands[(t.turn && t.turn.seat === s.seat) ? t.turn.hand : 0] || { cards: [] };
    const what = s.net != null ? (s.net > 0 ? "+" + fmt(s.net) : s.net < 0 ? "−" + fmt(-s.net) : "push") : h.bj ? "BJ!" : h.status === "bust" ? "bust" : tot(h) || "…";
    return `<div class="pv-seat ${t.turn && t.turn.seat === s.seat ? "turn" : ""}"><b style="color:${esc(s.color)}">${esc(s.name)}</b><small>${s.hands.length > 1 ? s.hands.length + " hands · " : ""}${esc(what)}</small><small>${fmt(s.hands.reduce((a, x) => a + x.bet, 0))} bet</small></div>`;
  }
  function render() {
    const p = c.pub, t = p.table || {}, pv = c.priv, r = p.rules || {}, ph = p.phase || "idle";
    const seats = t.seats || [], me = seats.find((s) => s.seat === S.seat), d = t.dealer || { cards: [] };
    const moves = pv.moves || [], turn = pv.turn;
    const key = JSON.stringify([ph, t, pv.moves, pv.bets, pv.insurance_offer, pv.credits, (p.totals || {}).main]);
    if (key === sig) return; sig = key;
    let html = `<section class="hg-felt bj-dealer"><div class="bj-top"><span class="eng" style="color:rgba(255,255,255,.8)">Dealer</span><small>${esc(rulesLine(r))}</small></div>
      <div class="bj-row"><div class="bj-cards">${d.cards.length ? d.cards.map(cardH).join("") : PC.empty() + PC.empty()}</div>
      ${d.cards.length ? `<b class="bj-tot ${d.total > 21 ? "bust" : ""} ${d.bj ? "bjk" : ""}">${d.bj ? "BJ" : d.total > 21 ? "BUST" : d.hole ? d.total + "<small style='font-size:12px;opacity:.7'> +?</small>" : d.total}</b>` : ""}</div></section>`;
    const others = seats.filter((s) => s.seat !== S.seat);
    if (others.length) html += `<div class="pv-seats">${others.map((s) => seatChip(s, t)).join("")}</div>`;
    if (ph === "betting" || ph === "idle" || !me) {
      if (ph === "betting" || ph === "idle") {
        const mine = (pv.bets || {}).main || 0, oth = c.others("main");
        html += `<button class="hg-felt bj-spot ${mine ? "has" : ""}" id="bj-spot"><span class="ring2">${mine ? `${HG.chip(mine)}<b class="num">${fmt(mine)}</b>` : `<b>Tap to bet</b><small>${c.betting ? "pick a chip below" : ""}</small>`}</span>
          <small>Blackjack pays ${esc(r.blackjack_pays || "3:2")} · insurance 2:1</small><span class="others">${oth > 0 ? fmt(oth) + " from the others" : ""}</span></button>`;
      } else html += `<div class="bj-watch"><div><b style="color:var(--ink)">You're watching this hand</b><p>Place a bet when the next round opens.</p></div></div>`;
    } else {
      html += `<div class="bj-hands">${me.hands.map((h, i) => `<article class="bj-hand ${turn && turn.hand === i ? "on" : ""} ${me.hands.length > 1 && turn && turn.hand !== i ? "out" : ""}">
        <header><span>${me.hands.length > 1 ? "Hand " + (i + 1) + " · " : "Your hand · "}${fmt(h.bet)}</span>${badge(h, me)}</header>
        <div class="bj-row"><div class="bj-cards big">${h.cards.map(cardH).join("")}</div><b class="bj-tot ${h.total > 21 ? "bust" : ""} ${h.bj ? "bjk" : ""}">${tot(h)}</b></div></article>`).join("")}</div>`;
      if (me.insurance) html += `<p class="note" style="margin:0 4px">Insured for ${fmt(me.insurance)} (pays 2:1 if the dealer has blackjack)</p>`;
    }
    if (moves.length) {
      const h = me && turn ? me.hands[turn.hand] : null;
      const sub = { double: h ? "+" + fmt(h.bet) : "", split: h ? "+" + fmt(h.bet) : "", surrender: h ? "half back" : "", insurance: pv.insurance_offer ? fmt(pv.insurance_offer) : "" };
      html += `<div class="hg-clock" id="bj-clock"><i></i></div><div class="bj-moves">${moves.map((m) => `<button class="bj-mv ${MV[m][1]}" data-mv="${m}">${MV[m][0]}${sub[m] ? `<small>${sub[m]}</small>` : ""}</button>`).join("")}</div>`;
    }
    root.innerHTML = html;
    const spot = $("#bj-spot", root); if (spot) HG.zone(spot, () => c, "main");
    for (const b of $$("[data-mv]", root)) b.addEventListener("click", () => { c.send(b.dataset.mv); buzz(b.dataset.mv === "hit" ? 12 : [10, 30, 10]); b.disabled = true; });
    if (moves.length) {
      const left = turn ? turn.ends_in : t.insurance_in, span = turn ? ((p.house || {}).turn_seconds || 20) : Math.min(12, (p.house || {}).turn_seconds || 20);
      if (left != null) HG.clock($("#bj-clock", root), left, span);
    }
    if (me) { const h = me.hands[turn ? turn.hand : 0] || {}; const st = (h.status || "") + (h.bj ? "bj" : ""); if (st !== lastStatus) { if (st === "bust") buzz(45); if (h.bj) buzz([20, 40, 20, 40, 60]); lastStatus = st; } }
  }
  function phaseText() {
    const p = c.pub, t = p.table || {}, pv = c.priv;
    if (p.phase === "action" && pv.turn) PC.phase("Your turn", `Hand total ${((t.seats || []).find((s) => s.seat === S.seat) || { hands: [] }).hands.map(tot)[pv.turn.hand] || ""} — choose a move`);
    else if (p.phase === "action" && pv.insurance_offer) PC.phase("Insurance?", `The dealer shows an ace — insure for ${fmt(pv.insurance_offer)}, pays 2:1`);
    else if (p.phase === "action" && t.turn) { const s = (t.seats || []).find((x) => x.seat === t.turn.seat); $("#ph-title").textContent = s ? `${s.name} is playing` : "Players are playing"; }
    else if (p.phase === "dealing" && t.stage === "dealer") $("#ph-title").textContent = "Dealer plays";
    else if (p.phase === "action" && t.stage === "insurance") $("#ph-title").textContent = "Insurance?";
  }
  return {
    title: "Blackjack",
    spinTitle: "Dealing…",
    resultTitle: (r) => (r.outcome && r.outcome.dealer_bj ? "Dealer blackjack" : r.label === "BUST" ? "Dealer busts!" : `Dealer ${r.label}`),
    mount(host, cc) { c = cc; sig = ""; root = document.createElement("div"); root.className = "bj"; host.append(root); },
    update(cc) {
      c = cc; const myTurn = !!(c.priv.moves || []).length;
      PC.chrome(myTurn || (c.pub.phase !== "betting" && c.pub.phase !== "idle"));
      render(); phaseText();
      if (["action", "result", "dealing"].includes(c.pub.phase)) $("#lockb").hidden = true; // the hand itself says it
      if (myTurn && !myTurnWas) buzz([20, 60, 20]);
      myTurnWas = myTurn;
    },
    unmount() { PC.chrome(false); root = null; sig = ""; },
    replay(rng, rules, stored) {
      const o = stored || {}, decks = Number(rules.decks || o.decks || 6);
      const comp = o.shuffled ? HG.full(decks) : o.shoe;
      // the chain: this round's shoe must be the previous round's minus its cards (unless a new shoe started)
      const hist = ((S.pub && S.pub.history) || []).filter((h) => h.game === "blackjack" && h.round < (S.verifying || Infinity));
      const prev = hist.filter((h) => h.outcome && h.outcome.cards).pop();
      let chain = true;
      if (prev && !o.shuffled && S.verifying) {
        const n = [...String(prev.outcome.shoe)].map(Number);
        for (const cd of prev.outcome.cards) n[HG.KINDS.indexOf(cd)]--;
        chain = n.join("") === comp;
      }
      const sh = HG.shoe(comp, decks, rng);
      const cards = (o.cards || []).map(() => sh.draw());
      return chain ? { ...o, shoe: comp, cards } : { chain: "broken" };
    },
    describe: (o) => `${(o.cards || []).length} cards from ${o.shuffled ? "a new shoe" : "the shoe"} · dealer ${o.dealer_bj ? "blackjack" : o.dealer_total}`,
    paytable(cc) {
      const r = cc.pub.rules || {};
      return `<table class="pays"><tr><td>Win<br><small class="note">house edge ≈ ${HG.pct(cc, "main")} with basic strategy (rule-table estimate)</small></td><td>1:1</td></tr>
        <tr><td>Blackjack (ace + ten-card)</td><td>${esc(r.blackjack_pays || "3:2")}</td></tr>
        ${r.insurance !== false ? `<tr><td>Insurance (dealer shows an ace)<br><small class="note">house edge ${HG.pct(cc, "insurance")}</small></td><td>2:1</td></tr>` : ""}
        <tr><td>Push</td><td>bet back</td></tr>${r.surrender === "late" ? `<tr><td>Surrender (first two cards)</td><td>half back</td></tr>` : ""}</table>
        <p class="note">${esc(rulesLine(r))}. Double on ${r.double_on === "9-11" ? "hard 9–11" : "any two cards"}${r.double_after_split === false ? "" : ", also after a split"}; split up to ${(r.max_splits || 3) + 1} hands; split aces get one card each. Bet even amounts for exact 3:2.</p>`;
    },
  };
})());

/* GAME: Baccarat (Punto Banco) — Player / Tie / Banker zones, pair side bets, the coup as it's dealt, a bead road. */
registerGame("baccarat", (() => {
  let root, c, sig = "", zones = {};
  const VAL = (cd) => (cd[0] === "A" ? 1 : "TJQK".includes(cd[0]) ? 0 : Number(cd[0]));
  const total = (cs) => cs.reduce((a, x) => a + VAL(x), 0) % 10;
  function banker(b, third) {
    if (third == null) return b <= 5;
    if (b <= 2) return true; if (b === 3) return third !== 8; if (b === 4) return third >= 2 && third <= 7;
    if (b === 5) return third >= 4 && third <= 7; if (b === 6) return third === 6 || third === 7; return false;
  }
  function coup(draw) { // games/baccarat.deal_coup
    const p = [draw()], b = [draw()]; p.push(draw()); b.push(draw());
    const pt = total(p), bt = total(b);
    if (!(pt >= 8 || bt >= 8)) { let third = null; if (pt <= 5) { p.push(draw()); third = VAL(p[2]); } if (banker(bt, third)) b.push(draw()); }
    const P = total(p), B = total(b);
    return { player: p, banker: b, p: P, b: B, winner: P > B ? "player" : B > P ? "banker" : "tie", natural: p.length === 2 && b.length === 2 && (pt >= 8 || bt >= 8), ppair: p[0][0] === p[1][0], bpair: b[0][0] === b[1][0] };
  }
  const Z = [["player", "Player", "bc-p"], ["tie", "Tie", "bc-t"], ["banker", "Banker", "bc-b"]], PZ = [["ppair", "Player pair", "bc-pp"], ["bpair", "Banker pair", "bc-bp"]];
  function pays(id, r) {
    if (id === "player") return "1:1"; if (id === "tie") return (r.tie_pays || 8) + ":1"; if (id === "banker") return r.commission === "no_commission" ? "1:1 · 6 pays ½" : "0.95:1"; return "11:1";
  }
  function side(cls, name, cs, done, w, me) {
    return `<div class="bc-side ${cls} ${done ? (w === me ? "won" : w === "tie" ? "" : "lost") : ""}"><h3>${name}</h3><div class="tot">${cs.length >= 2 ? total(cs) : ""}</div>
      <div class="cs">${cs.length ? cs.map((x, i) => PC.card(x, i === 2 ? "third" : "")).join("") : PC.empty() + PC.empty()}</div></div>`;
  }
  function render() {
    const p = c.pub, ph = p.phase, r = p.rules || {}, mine = c.priv.bets || {}, totals = p.totals || {};
    const res = ph === "result" && p.result ? p.result.outcome : null;
    const hist = (p.history || []).filter((h) => h.game === "baccarat");
    let shown = { player: [], banker: [] }, done = false, w = "";
    if (ph === "dealing" && p.cards) shown = p.cards;
    else if (res) { shown = res; done = true; w = res.winner; }
    else if (hist.length && ph !== "locked") { const o = hist[hist.length - 1].outcome; if (o) { shown = o; } }
    const key = JSON.stringify([ph, shown, mine, totals, hist.length, r]);
    if (key === sig) return; sig = key;
    let felt = `<section class="hg-felt bc-felt">${side("p", "PLAYER", shown.player, done, w, "player")}${side("b", "BANKER", shown.banker, done, w, "banker")}${done && w === "tie" ? `<span class="bc-tie">TIE ${res.p}–${res.b}</span>` : ""}</section>`;
    const beads = hist.slice(-16).map((h) => { const o = h.outcome || {}; return `<i class="t-${h.tone} ${o.ppair ? "pp" : ""} ${o.bpair ? "bp" : ""}" title="${esc(h.label)}">${h.tone === "tie" ? "T" : h.tone === "player" ? "P" : "B"}</i>`; }).join("");
    const zone = ([id, name, cls], small) => {
      const m = mine[id] || 0, o = (totals[id] || 0) - m;
      const won = res && ((id === res.winner) || (id === "ppair" && res.ppair) || (id === "bpair" && res.bpair));
      const push = res && res.winner === "tie" && (id === "player" || id === "banker");
      return `<button class="bc-z ${cls} ${small ? "small" : ""} ${won ? "won" : push ? "push" : res ? "lost" : ""}" data-z="${id}"><span class="zl">${name}</span><span class="zp">${pays(id, r)}</span>
        <span class="zb">${m ? HG.chip(m) + fmt(m) : ""}</span>${small ? "" : `<span class="zo">${o > 0 ? "others " + fmt(o) : ""}</span>`}</button>`;
    };
    root.innerHTML = felt + `<div class="bc-beads" aria-label="Bead road">${beads}</div><div class="bc-zones">${Z.map((z) => zone(z, false)).join("")}</div><div class="bc-pairs">${PZ.map((z) => zone(z, true)).join("")}</div>`;
    for (const b of $$("[data-z]", root)) HG.zone(b, () => c, b.dataset.z);
  }
  return {
    title: "Baccarat",
    spinTitle: "Dealing…",
    resultTitle: (r) => (r.tone === "tie" ? "Tie" : r.tone === "player" ? "Player wins" : "Banker wins") + (r.outcome ? ` ${r.outcome.p}–${r.outcome.b}` : ""),
    mount(host, cc) { c = cc; sig = ""; root = document.createElement("div"); root.className = "bc"; host.append(root); },
    update(cc) { c = cc; render(); },
    unmount() { root = null; sig = ""; },
    replay(rng, rules) { const d = Number(rules.decks || 8), sh = HG.shoe(HG.full(d), d, rng); return coup(() => sh.draw()); },
    describe: (o) => `Player ${o.player.join(" ")} = ${o.p} · Banker ${o.banker.join(" ")} = ${o.b}`,
    paytable(cc) {
      const r = cc.pub.rules || {};
      return `<table class="pays"><tr><td>Player<br><small class="note">house edge ${HG.pct(cc, "player")}</small></td><td>1:1</td></tr>
        <tr><td>Banker<br><small class="note">house edge ${HG.pct(cc, "banker")}</small></td><td>${r.commission === "no_commission" ? "1:1 (½ on a 6)" : "0.95:1"}</td></tr>
        <tr><td>Tie (Player and Banker bets push)<br><small class="note">house edge ${HG.pct(cc, "tie")}</small></td><td>${r.tie_pays || 8}:1</td></tr>
        <tr><td>Player pair · Banker pair<br><small class="note">house edge ${HG.pct(cc, "pair")}</small></td><td>11:1</td></tr></table>
        <p class="note">A fresh ${r.decks || 8}-deck shoe every coup. Player draws on 0–5; the Banker follows the standard tableau. Payouts are whole credits, rounded down${r.commission === "no_commission" ? "" : " — bet Banker in 20s for the exact 5 %"}.</p>`;
    },
  };
})());

/* GAME: Slots — your own machine: pick a bet, pull the lever (drag down + release) or tap SPIN; the reels spin in
   sync with the panel and stop one by one as the panel's do. */
registerGame("slots", (() => {
  // mirror of games/slots.STRIPS (tests check they match): theme → volatility → [reel 1, 2, 3]
  const STRIPS = {
    classic: { low: ["OCL_C_COBL_PC7_CXOL_CBC_P", "BCPO_LC_CO_LCBP_CO_7CLXC_", "7C_BOXPLC_C_OCL_BCP_COLC_"], medium: ["OLC_CPXBLC7OPC_LXCBP", "BPCOLCPXCBO_CLP7CX", "7XPBCLOCP_CLXBCOPLC_"], high: ["OL_X7CBXP_7OLX_7BXP", "BPOLX_7CXB_P7OLXC_7X", "7XBPOX7L_XB7POXCL_"] },
    neon: { low: ["321_12_12U1_S321G_21R2_1U", "R21U_312_121_2U13_2S12G1_", "S12_G1U23_R121_12_1U23_121_"], medium: ["_12_31RU_S312G_1R_U", "RU1_231_21R_U31_S21G_", "SR_G1U32_1_R1U_321_"], high: ["_12_31RU_S12G_1R_U", "RU_12_3_1RU_2_S1G_", "S_R_U_1_G31R_2U_1_"] },
    space: { low: ["MCS_SCMRSCPASCUM_SCRSP", "RSCPMSC_SMCSRPSCMAS_CUS", "ASCRMUPSCSMCSRPCSMCS"], medium: ["MCSAUSMRC_PSMCAUSRP", "RPMSCSAMUCRPS_MCSAU", "AURMSPCSMACURSPMCS_"], high: ["M_SCA_U_RP_AM_S_UAR_P", "A_PM_A_CU_RS_P_M_ARU_", "AU_RP_MA_RU_A_CPM_S_"] },
  };
  const LINES = [[1, 1, 1], [0, 0, 0], [2, 2, 2], [0, 1, 2], [2, 1, 0]];
  let root, c, mach, reelsEl = [], strips = null, themeKey = "", imgs = {}, bet = null, raf = 0, lever, knob, rod, drag = null;
  let R = [0, 0, 0].map(() => ({ pos: 0, mode: "idle", from: 0, to: 0, t0: 0, vel: 0 })), spinId = null, shownResult = null, lastT = 0;
  const cellPx = () => (reelsEl[0] ? reelsEl[0].clientHeight / 3 : 64);
  function sprite(sym) { // the panel's pixels as LED dots on a canvas (data URL cached per theme)
    const m = c.pub.machine || {}, sp = (m.sprites || {}).symbols || {}, pal = (m.sprites || {}).palette || [];
    if (imgs[sym] !== undefined) return imgs[sym];
    const rows = sp[sym]; if (!rows) return (imgs[sym] = null);
    const n = 7, k = 12, cv = document.createElement("canvas"); cv.width = cv.height = n * k; const g = cv.getContext("2d");
    rows.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === ".") return; const col = pal[parseInt(ch, 36)]; g.fillStyle = col; g.shadowColor = col; g.shadowBlur = 5; g.beginPath(); g.arc(x * k + k / 2, y * k + k / 2, k * 0.44, 0, Math.PI * 2); g.fill(); }));
    return (imgs[sym] = cv.toDataURL());
  }
  function build() {
    const m = c.pub.machine || {};
    themeKey = `${m.theme}/${m.volatility}`; imgs = {}; strips = m.strips || STRIPS.classic.medium;
    root.innerHTML = `<div class="sl-cab"><section class="sl-mach ${esc(m.theme || "")}" id="sl-mach"><div class="sl-name"><span>${esc(m.name || "Slots")}</span><small id="sl-rtp"></small></div><div class="sl-win" id="sl-win">${strips.map((s, i) =>
      `<div class="sl-reel" data-r="${i}"><div class="sl-strip">${[...(s + s + s)].map((ch) => `<div class="sl-cell">${ch === "_" ? "" : `<img alt="${esc((m.names || {})[ch] || ch)}" src="${sprite(ch) || ""}" style="width:74%;height:74%">`}</div>`).join("")}</div></div>`).join("")}</div></section>
      <div class="sl-lever" id="sl-lever" role="button" aria-label="Pull the lever"><div class="slot"></div><div class="rod"></div><div class="sl-knob"></div><div class="hint">PULL</div></div></div>
      <div class="sl-msg" id="sl-msg"></div><div class="sl-bets" id="sl-bets" role="radiogroup" aria-label="Bet per line"></div><button class="sl-go" id="sl-go">SPIN</button><div class="sl-seal" id="sl-seal"></div>`;
    mach = $("#sl-mach", root); reelsEl = $$(".sl-reel", root); lever = $("#sl-lever", root); knob = $(".sl-knob", lever); rod = $(".rod", lever);
    $("#sl-go", root).addEventListener("click", pull);
    lever.addEventListener("pointerdown", onDown); lever.addEventListener("pointermove", onMove); lever.addEventListener("pointerup", onUp); lever.addEventListener("pointercancel", onUp);
    $("#sl-bets", root).addEventListener("click", (e) => { const b = e.target.closest("[data-b]"); if (!b || b.disabled) return; bet = Number(b.dataset.b); buzz(6); paint(); });
    const last = c.priv.last;
    R.forEach((r, i) => { r.pos = last && last.stops && last.stops[i] != null ? last.stops[i] : i * 5; r.mode = "idle"; });
  }
  function canPull() { return !!c.priv.can_pull && !c.pub.paused; }
  function pull() {
    if (!canPull()) { toast(c.priv.spin ? "Your reels are still spinning" : "Not now", true); buzz(30); return; }
    const m = c.pub.machine || {}, b = bet || c.priv.bet || (m.bets || [1])[0];
    if ((c.priv.credits || 0) < b * (m.lines || 1)) { toast("Not enough credits — pick a smaller bet", true); buzz(30); return; }
    c.send("pull", { bet: b }); buzz([15, 30, 40]);
    R.forEach((r) => { r.mode = "spin"; r.vel = 0; });
    shownResult = null; clearMarks();
  }
  // the lever: drag the knob down, let go past ~60 % to pull; it springs back either way
  function travel() { return lever.clientHeight - 70; }
  function setKnob(y) { knob.style.transform = `translateY(${y}px)`; rod.style.height = Math.max(0, y) + "px"; }
  function onDown(e) { if (!canPull()) { buzz(20); return; } try { lever.setPointerCapture(e.pointerId); } catch (_) {} drag = { id: e.pointerId, y0: e.clientY, y: 0, tick: 0 }; lever.classList.add("drag"); }
  function onMove(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const max = travel(), raw = Math.max(0, e.clientY - drag.y0), y = Math.min(max, raw < max * 0.8 ? raw : max * 0.8 + (raw - max * 0.8) * 0.35);
    drag.y = y; setKnob(y);
    const step = Math.floor((y / max) * 5); if (step > drag.tick) { drag.tick = step; buzz(step >= 3 ? 12 : 5); }
  }
  function onUp(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const go = drag.y >= travel() * 0.6; drag = null; lever.classList.remove("drag"); setKnob(0);
    if (go) pull();
  }
  function clearMarks() { for (const x of $$(".sl-mark, .sl-pay", root)) x.remove(); }
  function showWin(res) {
    clearMarks();
    const win = $("#sl-win", root), cell = cellPx();
    for (const w of res.wins || []) {
      const rows = LINES[w.line - 1];
      rows.forEach((row, i) => { const reel = reelsEl[i]; const mk = document.createElement("div"); mk.className = "sl-mark"; mk.style.top = (row * cell + 2) + "px"; reel.append(mk); });
    }
    if (res.win > 0) {
      const p = document.createElement("div"); p.className = "sl-pay";
      p.innerHTML = `<b class="num">+${fmt(res.win)}<small>${esc((res.wins || []).map((w) => w.what).join(" · "))}</small></b>`; win.append(p);
      buzz([30, 50, 30, 50, 90]); confetti(Math.min(36, 10 + Math.round(Math.log2(1 + res.win) * 3)));
    } else buzz(15);
  }
  // reel motion: spin fast until the server reveals the stop (when the panel's reel stops), then ease onto it
  function frame(ts) {
    raf = requestAnimationFrame(frame);
    if (!root || !reelsEl.length) return;
    const dt = Math.min(0.05, (ts - (lastT || ts)) / 1000); lastT = ts;
    const cell = cellPx();
    R.forEach((r, i) => {
      const n = strips[i].length;
      if (r.mode === "spin") { r.vel = Math.min(16, r.vel + dt * 40); r.pos += r.vel * dt; }
      else if (r.mode === "land") {
        const u = Math.min(1, (ts - r.t0) / 420), e = 1 - Math.pow(1 - u, 3), over = Math.sin(u * Math.PI) * 0.28 * (1 - u);
        r.pos = r.from + (r.to - r.from) * e + over; if (u >= 1) { r.pos = r.to; r.mode = "idle"; buzz(8); }
      }
      const pos = ((r.pos % n) + n) % n;
      const strip = reelsEl[i].firstElementChild;
      strip.style.transform = `translateY(${-((pos + n - 1) * cell)}px)`;
      reelsEl[i].classList.toggle("blur", r.mode === "spin" && r.vel > 6 && !REDUCED);
    });
    if (shownResult && shownResult.pending && R.every((r) => r.mode === "idle")) { shownResult.pending = false; showWin(shownResult); }
  }
  function land(i, stop) {
    const r = R[i], n = strips[i].length;
    if (r.mode === "idle" && Math.round(r.pos) % n === stop) return;
    const cur = r.pos, base = Math.floor(cur / n) * n; let to = base + stop; while (to < cur + 1.5) to += n;
    r.mode = "land"; r.from = cur; r.to = to; r.t0 = performance.now() + i * (REDUCED ? 0 : 60);
  }
  function paint() {
    const m = c.pub.machine || {}, pv = c.priv, sp = pv.spin;
    if (`${m.theme}/${m.volatility}` !== themeKey) build();
    $("#sl-rtp", root).textContent = `RTP ${(m.rtp * 100).toFixed(2)} % · ${m.lines} line${m.lines > 1 ? "s" : ""}`;
    const opts = m.bets || [1]; if (bet == null || !opts.includes(bet)) bet = opts.includes(pv.bet) ? pv.bet : opts[0];
    const bets = $("#sl-bets", root), free = (pv.credits || 0) + 0;
    bets.innerHTML = opts.map((b) => `<button class="sl-bet" role="radio" data-b="${b}" aria-checked="${b === bet}" ${b * m.lines > free && b !== bet ? "disabled" : ""}>${short(b)}<small>${fmt(b * m.lines)}</small></button>`).join("");
    const go = $("#sl-go", root), ok = canPull();
    go.disabled = !ok; go.textContent = ok ? `SPIN · ${fmt(bet * m.lines)}` : sp ? (sp.t == null ? "QUEUED…" : "SPINNING…") : "SPIN";
    lever.classList.toggle("off", !ok);
    // my spin: sync the reels with the panel
    if (sp) {
      if (spinId !== sp.id) { spinId = sp.id; shownResult = null; clearMarks(); R.forEach((r) => { if (r.mode !== "spin") { r.mode = "spin"; r.vel = 0; } }); }
      (sp.stops || []).forEach((st, i) => { if (st != null && R[i].mode === "spin") land(i, st); });
    } else if (pv.last && spinId === pv.last.id && !shownResult) {
      pv.last.stops.forEach((st, i) => { if (R[i].mode === "spin" || R[i].mode === "idle") land(i, st); });
      shownResult = { ...pv.last, pending: true };
    }
    const msg = $("#sl-msg", root);
    if (c.pub.paused) msg.textContent = "The host paused the machines";
    else if (sp && sp.t == null) msg.innerHTML = `<b>${sp.ahead} spin${sp.ahead === 1 ? "" : "s"} ahead of you</b> — yours is next on the panel${sp.starts_in != null ? " in ~" + sp.starts_in + " s" : ""}`;
    else if (sp) msg.innerHTML = `<b>Spinning on the panel!</b> ${fmt(sp.stake)} in play`;
    else if (pv.last && pv.last.win > 0) msg.innerHTML = `Last spin <b style="color:var(--gold)">+${fmt(pv.last.win)}</b> — pull again!`;
    else msg.textContent = "Drag the lever down and let go — or tap SPIN";
    const pl = c.pub.playing;
    if (pl && pl.seat !== S.seat && !sp) msg.innerHTML += `<br><small>${esc(pl.name)} is spinning on the panel</small>`;
    const s = pv.sealed; $("#sl-seal", root).textContent = s ? `Next spin sealed · #${s.round} · ${s.hash.slice(0, 16)}…` : "";
  }
  function phaseText() {
    const sp = c.priv.spin, m = c.pub.machine || {};
    PC.phase(sp ? (sp.t == null ? "In the queue" : "Spinning…") : "Pull the lever", sp ? `${fmt(sp.stake)} credits in play — locked until the reels stop` : `${m.name || "Slots"} · ${m.volatility || ""} volatility · RTP ${((m.rtp || 0) * 100).toFixed(2)} %`);
  }
  return {
    title: "Slots",
    resultTitle: (r) => r.label,
    mount(host, cc) { c = cc; root = document.createElement("div"); root.className = "sl"; host.append(root); PC.chrome(true); themeKey = ""; spinId = null; build(); cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); },
    update(cc) { c = cc; PC.chrome(true); paint(); phaseText(); },
    unmount() { cancelAnimationFrame(raf); PC.chrome(false); root = null; reelsEl = []; },
    replay(rng, rules) { const s = (STRIPS[rules.theme] || STRIPS.classic)[rules.volatility] || STRIPS.classic.medium; return { stops: s.map((x) => rng.randint(0, x.length - 1)) }; },
    describe: (o) => `stops ${o.stops.join(" · ")}`,
    paytable(cc) {
      const m = cc.pub.machine || {}, names = m.names || {}, img = (ch) => `<span class="sl-pt">${[0, 1, 2].map(() => `<img alt="" src="${sprite(ch) || ""}">`).join("")}</span>`;
      const rows = Object.entries(m.three || {}).sort((a, b) => b[1] - a[1]).map(([ch, p]) => `<tr><td>${img(ch)} ${esc(names[ch] || ch)}${ch === m.wild ? " (wild: stands in for any symbol)" : ""}</td><td>${p}×</td></tr>`);
      for (const [lbl, mem, p] of m.groups || []) rows.push(`<tr><td>${esc(lbl)} (any mix of ${[...mem].map((x) => esc(names[x] || x)).join(", ")})</td><td>${p}×</td></tr>`);
      for (const [n, p] of Object.entries(m.lead || {}).sort((a, b) => b[0] - a[0])) rows.push(`<tr><td>${n} × ${esc(names[m.lead_symbol] || m.lead_symbol)} from the left</td><td>${p}×</td></tr>`);
      return `<table class="pays">${rows.join("")}</table><p class="note">Pays are × your bet per line; each of the ${m.lines} line${m.lines > 1 ? "s" : ""} pays its best win. <b>RTP ${((m.rtp || 0) * 100).toFixed(3)} %</b> — computed exactly from these reel strips (every stop combination), hit rate 1 in ${(1 / (m.hit || 1)).toFixed(1)} per line, ${esc(m.volatility || "")} volatility. Each spin is its own sealed round: the stops are uniform draws from the fair RNG.</p>`;
    },
  };
})());
/* ===== END house games block ===== */

/* ------------------------------------------------ connection */
let ws = null, backoff = 300, retryT = 0, lastMsg = 0, ended = false;
function net(ok) { const d = $("#netdot"); if (d) d.classList.toggle("off", !ok); }
function end(title, text, label) {
  if (ended) return; ended = true; clearTimeout(retryT);
  $("#end-t").textContent = title; $("#end-p").textContent = text; $("#end-b").textContent = label; $("#end").hidden = false;
}
$("#end-b").addEventListener("click", () => location.reload());
function onHello(m) {
  const first = !S.hello; S.hello = true;
  S.seat = m.seat; S.game = m.game || "Casino";
  if (m.rulebook && typeof m.rulebook === "object") S.rulebook = m.rulebook;
  S.palette = Array.isArray(m.palette) ? m.palette : []; S.avatars = {}; S.avatarIds = [];
  for (const a of m.avatars || []) { S.avatars[a.id] = a; S.avatarIds.push(a.id); }
  if (typeof m.cid === "string" && m.cid !== cid) { cid = m.cid; store("deskdot.cid", cid); }
  const p = m.profile || {};
  S.me = { name: p.name || "P" + S.seat, color: m.color || p.color || "#ffcc33", avatar: p.avatar || S.avatarIds[0] };
  document.title = `${S.game} · DeskDot casino`;
  if (!m.resumed) {
    const saved = store("deskdot.profile") || {}, want = {};
    const nm = cleanName(saved.name).trim() || FUN[Math.floor(Math.random() * FUN.length)];
    if (nm !== S.me.name) { S.me.name = nm; want.name = nm; }
    if (saved.avatar && S.avatars[saved.avatar] && saved.avatar !== S.me.avatar) { S.me.avatar = saved.avatar; want.avatar = saved.avatar; }
    if (saved.color && S.palette.some((x) => x.color === saved.color) && saved.color !== S.me.color) want.color = saved.color;
    if (Object.keys(want).length) sendProfile(want, true);
  }
  send("seed", { client_seed: seed });
  let last = ""; try { last = sessionStorage.getItem("deskdot.casino.scr:" + code) || ""; } catch (_) {}
  if (first) { if (m.resumed || last === "table") { sendProfile({ ready: true }, true); go("table"); toast(`Welcome back, ${S.me.name}`); } else go("seat"); }
  else { toast("Reconnected"); if (S.screen === "table") sendProfile({ ready: true }, true); }
  paintMe();
}
function onRoster(players) {
  S.roster = Array.isArray(players) ? players : [];
  const mine = S.roster.find((p) => p.seat === S.seat);
  if (mine) { S.me.color = mine.color; if (document.activeElement !== $("#name") && !profQ.name) S.me.name = mine.name; S.me.avatar = mine.avatar || S.me.avatar; }
  if (S.screen === "seat") renderSeat(); else paintMe();
}
function connect() {
  if (ended) return;
  let sock;
  try { sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/p/${code}?cid=${encodeURIComponent(cid)}`); }
  catch (_) { retryT = setTimeout(connect, backoff); return; }
  ws = sock;
  sock.onopen = () => { backoff = 300; lastMsg = now(); net(true); };
  sock.onmessage = (ev) => {
    if (sock !== ws) return; lastMsg = now(); net(true);
    let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === "hello") onHello(m);
    else if (m.type === "state") onState(m);
    else if (m.type === "roster") onRoster(m.players);
    else if (m.type === "full") { end("The table is full", "Every seat is taken. Ask the host to make room, then scan the QR code on the panel again.", "Try again"); sock.close(); }
    else if (m.type === "closed") { end("The table closed", "The host closed this game. Your credits are kept — scan the QR code on the panel to join the next one.", "Rejoin"); sock.close(); }
    else if (m.type === "replaced") { end("Opened somewhere else", "This seat was opened in another tab or window, so this one stopped.", "Use this one"); sock.close(); }
  };
  sock.onclose = () => { if (sock !== ws || ended) return; net(false); retryT = setTimeout(connect, backoff); backoff = Math.min(Math.round(backoff * 1.6), 3000); };
}
setInterval(() => {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "ping", t: now() }));
  if (ws && ws.readyState === 1 && now() - lastMsg > 5000 && !ended) { const dead = ws; ws = null; try { dead.close(); } catch (_) {} net(false); clearTimeout(retryT); connect(); }
}, 1500);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && !ended && (!ws || ws.readyState > 1)) { clearTimeout(retryT); connect(); } });

/* ------------------------------------------------ boot */
$("#j-code").textContent = code.toUpperCase();
for (const s of $$(".scr")) s.inert = !s.classList.contains("on");
requestAnimationFrame(tickCountdown);
connect();
window.DeskDotCasino = { registerGame, Rng, sha256, hmac256, hex, ctx }; // for game modules added later and for tests

// tv-games.js — TV scenes for the games category (and pets): the live panel big as the hero, plus what a
// living-room audience needs to follow the match. Contract: docs/TV_VIEW.md (TV.registerScene, ctx).
//
// What each game family shows (statuses: src/deskdot/apps/games_core.py GameApp.status + per-game extras;
// samples in tests/js/fixtures/game_statuses.json):
//
// | Family            | Games                                                     | Side of the panel shows                                   |
// | ----------------- | --------------------------------------------------------- | --------------------------------------------------------- |
// | Solo arcade       | every game in Solo mode, penguin                          | huge score + best (NEW BEST), lives ♥, level / screen /   |
// |                   |                                                           | lap / day, who plays (you · AI demo · fruit fly)          |
// | Co-op             | invaders, maze, asteroids, infinity, mines, starship,     | one team card: shared score + lives, the crew in their    |
// |                   | breakout, leafleap, tetris, 2048 relay, digworld, snake   | colours, per-seat extras (mines points, ore, lines)       |
// |                   |                                                           | 2048 relay: whose turn                                    |
// | Free-for-all      | snake battle, cycles party, flappy/dino/racer race,       | a card per seat in its colour: name, avatar, phone / CPU, |
// |                   | street surge, neon heat rush, 2048 race, mines race,      | the game's per-seat number (apples, rounds won, place,    |
// |                   | starship ace, invaders duel, maze hunt, digworld rush …   | cash, top tile, points, ore), lives, OUT, a crown on the  |
// |                   |                                                           | leader; match clock (time_left), lap                      |
// | Versus (teams)    | pong, tetris versus, breakout versus, snake/asteroids/    | Team A vs Team B columns (members, team totals), side     |
// |                   | cycles/street surge teams, neon heat cops                 | select board while picking sides                          |
// | Board duels       | tictactoe (X and 0), fourup                               | two big player cards (X / O, coloured discs), match tally |
// |                   |                                                           | and draws, whose move (glowing), variant                  |
// | Rock paper sc.    | rps (cpu / pvp / tournament)                              | bespoke: both hands as big pixel art in seat colours,     |
// |                   |                                                           | first-to pips, pick timer + locked badges, reveal +       |
// |                   |                                                           | winner, bracket / round-robin table, champion; panel inset|
// | Quiz              | trivia                                                    | the question + options big, highlighted pick, score/streak|
// | Chess puzzle      | chess                                                     | puzzle title, side to move, move stepper (never the       |
// |                   |                                                           | solution text)                                            |
// | Pets              | pet, petworld                                             | the character, what it's doing, world / time of day       |
//
// Every multiplayer family also shows the match flow (attract demo · menu · side select · 3-2-1 countdown · live ·
// results with a winner banner), the controls legend for the game, and "scan to join" while a lobby has free seats.
(function () {
  "use strict";

  const SEAT = { 1: "#00c8ff", 2: "#ff3c5a", 3: "#50ff78", 4: "#ffc800", 5: "#c864ff", 6: "#ff7419", 7: "#ff8cc8", 8: "#a0f0ff" };
  const TEAM = ["#00c8ff", "#ff3c5a"];
  const TEAM_NAME = ["Team A", "Team B"];

  // id → modes "id:Name:teams" (teams = solo | coop | ffa | versus), mirrors GameApp.modes
  const MODE_SPEC = {
    arcade: "solo:Solo:solo battle:Battle:ffa teams:Teams:versus coop:Co-op:coop",
    invaders: "solo:Solo:solo coop:Co-op:coop duel:Duel:ffa",
    maze: "solo:Solo:solo coop:Co-op:coop hunt:Hunt:ffa",
    asteroids: "solo:Solo:solo coop:Co-op:coop battle:Battle:ffa teams:Teams:versus",
    infinity: "solo:Solo:solo survive:Survive:ffa coop:Co-op:coop",
    tictactoe: "solo:Solo:solo duel:Duel:ffa",
    mines: "solo:Solo:solo coop:Co-op:coop race:Race:ffa",
    starship: "solo:Solo:solo coop:Co-op:coop ace:Ace_duel:ffa",
    neonheat: "solo:Solo:solo rush:Rush:ffa cops:Cops_and_robbers:versus",
    pong: "classic:Classic:versus doubles:Doubles:versus fourway:Four-way:ffa",
    breakout: "solo:Solo:solo coop:Co-op:coop versus:Versus:versus",
    flappy: "solo:Solo:solo race:Race:ffa",
    dino: "solo:Solo:solo race:Race:ffa",
    racer: "solo:Solo:solo race:Race:ffa",
    fourup: "solo:Solo:solo duel:Duel:ffa",
    cycles: "solo:Solo:solo party:Party:ffa teams:Teams:versus",
    penguin: "solo:Solo:solo",
    leafleap: "solo:Solo:solo coop:Co-op:coop race:Race:ffa",
    tetris: "solo:Solo:solo versus:Versus:versus coop:Co-op:coop",
    g2048: "solo:Solo:solo race:Race:ffa relay:Relay:coop",
    streetsurge: "solo:Solo:solo race:Race:ffa teams:Teams:versus",
    rps: "cpu:Versus_CPU:solo pvp:Player_vs_player:ffa tour:Tournament:ffa demo:Demo:solo",
    digworld: "solo:Solo:solo coop:Co-op:coop rush:Ore_rush:ffa",
  };
  const MODES = {};
  for (const [app, spec] of Object.entries(MODE_SPEC)) {
    MODES[app] = {};
    for (const part of spec.split(" ")) {
      const [id, name, teams] = part.split(":");
      MODES[app][id] = { id, name: name.replace(/_/g, " "), teams };
    }
  }

  // controls legend: the studio's PlayMode HINTS plus the games it leaves to defaults
  const HINTS = {
    arcade: { move: "Steer" },
    maze: { move: "Steer" },
    g2048: { move: "Slide the tiles" },
    tetris: { left: "Move", right: "Move", up: "Rotate", down: "Soft drop", a: "Hard drop", b: "Rotate back" },
    invaders: { left: "Move", right: "Move", a: "Fire" },
    starship: { left: "Move", right: "Move", a: "Bomb" },
    asteroids: { left: "Turn", right: "Turn", up: "Thrust", down: "Brake", a: "Fire", b: "Hyperspace" },
    infinity: { up: "Climb", down: "Dive", a: "Climb", b: "Dive" },
    tictactoe: { move: "Pick a square", a: "Place" },
    mines: { move: "Move", a: "Reveal", b: "Flag" },
    pong: { up: "Paddle up", down: "Paddle down" },
    breakout: { left: "Paddle", right: "Paddle" },
    flappy: { up: "Flap", a: "Flap" },
    dino: { up: "Jump", a: "Jump", down: "Duck" },
    racer: { left: "Lane left", right: "Lane right" },
    penguin: { move: "Waddle / slide", a: "Undo", b: "Restart · levels" },
    neonheat: { move: "Drive · turn at junctions" },
    streetsurge: { left: "Steer", right: "Steer", down: "Brake", a: "Nitro", b: "Brake" },
    leafleap: { left: "Run", right: "Run", up: "Jump", a: "Jump" },
    digworld: { move: "Walk · dig", a: "Dig / place", b: "Dig ⇄ build" },
    fourup: { left: "Column", right: "Column", a: "Drop", up: "Pop out (Pop-out)" },
    cycles: { move: "Steer" },
    rps: { left: "Rock", up: "Paper", right: "Scissors", down: "Let fate pick" },
    trivia: { move: "Choose an answer", a: "Lock in · next", b: "Read the question again" },
    chess: { left: "Step back", right: "Step forward", a: "Back to the start", b: "Show the solution" },
  };
  const GLYPH = { up: "↑", down: "↓", left: "←", right: "→", a: "A", b: "B" };

  const BOARD = new Set(["tictactoe", "fourup"]);
  const GAME_IDS = new Set([...Object.keys(MODE_SPEC), "trivia", "chess"]);
  const PET_IDS = new Set(["pet", "petworld"]);

  // per-seat numbers games publish as {seat: value}; the first one present is the seat's headline number
  const PER_SEAT = [
    { k: "apples", label: "Apples" },
    { k: "lines", label: "Lines" },
    { k: "cash", label: "Cash", fmt: "cash" },
    { k: "places", label: "Place", fmt: "ord", low: true },
    { k: "tops", label: "Top tile" },
    { k: "cells", label: "Points" },
    { k: "ore", label: "Ore" },
    { k: "wins", label: "Rounds" },
  ];

  // ================================================================== pure helpers (tested in Node)
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function ordinal(n) {
    n = Number(n);
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  function mmss(sec) {
    sec = Math.max(0, Math.round(Number(sec) || 0));
    return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
  }

  function num(n) {
    n = Number(n) || 0;
    return Math.abs(n) >= 10000 ? n.toLocaleString("en-US") : String(n);
  }

  function hexRgb(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || ""));
    if (!m) return [255, 255, 255];
    const v = parseInt(m[1], 16);
    return [v >> 16, (v >> 8) & 255, v & 255];
  }
  const rgbHex = (c) => "#" + c.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, k) => rgbHex(hexRgb(a).map((v, i) => v + (hexRgb(b)[i] - v) * k));
  const shade = (a, k) => rgbHex(hexRgb(a).map((v) => v * k));

  /** The current mode: {id, name, teams}. Unknown games infer the kind from the roster's teams. */
  function modeInfo(app, st) {
    st = st || {};
    const id = String(st.play_mode || st.mode || "solo"); // digworld reports its menu mode as play_mode
    const known = MODES[app] && MODES[app][id];
    if (known) return known;
    const roster = Object.values(st.roster || {});
    const teams = new Set(roster.map((r) => r.team));
    let kind = "solo";
    if (roster.length > 1) kind = teams.has(1) ? "versus" : teams.has(0) ? "coop" : "ffa";
    return { id, name: id.charAt(0).toUpperCase() + id.slice(1), teams: kind };
  }

  /** Is this a match with seats (not the attract demo / a one-player game)? */
  function matchKind(app, st) {
    st = st || {};
    if (!st.roster || Object.keys(st.roster).length < 1) return "solo";
    const m = modeInfo(app, st);
    if (Object.keys(st.roster).length < 2 && m.teams !== "versus") return "solo";
    return m.teams;
  }

  function seatNo(x) {
    const n = parseInt(x, 10);
    return Number.isFinite(n) ? n : null;
  }

  /** A per-seat dict ({"1": 3} or {1: 3}) read for one seat. */
  function perSeat(d, seat) {
    if (!d || typeof d !== "object" || Array.isArray(d)) return undefined;
    return d[seat] !== undefined ? d[seat] : d[String(seat)];
  }
  const isSeatDict = (d) => d && typeof d === "object" && !Array.isArray(d) && Object.keys(d).length > 0 && Object.keys(d).every((k) => /^\d+$/.test(k));

  /**
   * The seats to show, in seat order: [{seat, name, color, ownColor, human, team, ready, avatar, alive, stats,
   * headline}]. A match shows its roster; otherwise the seats with a person (phones, the host) — or none.
   */
  function seatList(app, st, lobby) {
    st = st || {};
    const roster = st.roster || {};
    const info = {};
    for (const s of st.seats || []) info[s.seat] = s;
    // a lobby seat is a person on a phone: its name / colour / avatar win over a status that may lag behind
    for (const s of (lobby && lobby.seats) || []) {
      const prev = info[s.seat] || {};
      info[s.seat] = Object.assign({}, prev, { seat: s.seat, name: s.name || prev.name, color: s.color || prev.color, avatar: s.avatar || prev.avatar, ready: !!(s.ready || prev.ready), human: true });
    }
    let seats = Object.keys(roster).map(seatNo).filter((n) => n != null);
    if (!seats.length) seats = Object.values(info).filter((s) => s.human || (lobby && (lobby.seats || []).some((l) => l.seat === s.seat))).map((s) => s.seat);
    seats = [...new Set(seats)].sort((a, b) => a - b);
    const mode = modeInfo(app, st);
    const alive = Array.isArray(st.alive) ? new Set(st.alive.map(Number)) : null;
    const teamRank = { 0: 0, 1: 0 };
    return seats.map((n) => {
      const i = info[n] || {};
      const r = roster[n] || roster[String(n)] || {};
      const human = r.human !== undefined ? !!r.human : !!i.human;
      const own = i.color || SEAT[n] || "#ffffff";
      let color = own;
      const team = r.team === 0 || r.team === 1 ? r.team : null;
      if (mode.teams === "versus" && team != null) {
        const rank = teamRank[team]++;
        color = rank ? mix(TEAM[team], "#ffffff", Math.min(0.9, 0.45 * rank)) : TEAM[team];
      }
      let name = i.name;
      if (!name || name === "YOU") name = n === 1 ? "Player 1" : "Player " + n;
      if (!human && (!i.name || i.name === "AI")) name = "CPU " + n;
      const stats = [];
      for (const p of PER_SEAT) {
        const d = st[p.k];
        if (!isSeatDict(d)) continue;
        const v = perSeat(d, n);
        if (v === undefined || v === null) continue;
        stats.push({ k: p.k, label: p.label, value: v, text: fmtStat(p.fmt, v), low: !!p.low });
      }
      const lives = isSeatDict(st.lives) ? perSeat(st.lives, n) : undefined;
      return {
        seat: n,
        name: String(name),
        color,
        ownColor: own,
        human,
        team,
        ready: !!(r.ready || i.ready),
        avatar: i.avatar || null,
        alive: alive ? alive.has(n) : lives !== undefined ? lives > 0 : true,
        lives,
        stats,
        headline: stats[0] || null,
      };
    });
  }

  function fmtStat(kind, v) {
    if (kind === "cash") return "$" + num(v);
    if (kind === "ord") return ordinal(v);
    return num(v);
  }

  /** The seat(s) in front on the headline number (none while everyone is level at the start). */
  function leaders(seats) {
    const scored = seats.filter((s) => s.headline && typeof s.headline.value === "number");
    if (scored.length < 2) return [];
    const low = scored[0].headline.low;
    const vals = scored.map((s) => s.headline.value);
    const best = low ? Math.min(...vals) : Math.max(...vals);
    if (vals.every((v) => v === best)) return [];
    return scored.filter((s) => s.headline.value === best).map((s) => s.seat);
  }

  /** Team totals for versus: [{team, name, color, members, total, label}] (total null if no per-seat number). */
  function teamsOf(seats) {
    return [0, 1].map((t) => {
      const members = seats.filter((s) => s.team === t);
      const h = members.map((s) => s.headline).filter(Boolean);
      const additive = h.length && !h[0].low && h[0].k !== "tops";
      const total = additive ? h.reduce((a, x) => a + (Number(x.value) || 0), 0) : null;
      return { team: t, name: TEAM_NAME[t], color: TEAM[t], members, total, label: h.length ? h[0].label : "" };
    });
  }

  /** Match-wide chips: [{label, value, tone?, hearts?}] from whatever the status carries. */
  function globalStats(app, st) {
    st = st || {};
    const out = [];
    if (typeof st.level === "number") out.push({ k: "level", label: "Level", value: st.levels ? `${st.level} / ${st.levels}` : String(st.level) });
    if (typeof st.screen === "number") out.push({ k: "screen", label: "Screen", value: String(st.screen) });
    if (typeof st.lap === "number") out.push({ k: "lap", label: "Lap", value: String(st.lap) });
    if (typeof st.lives === "number") out.push({ k: "lives", label: "Lives", value: String(st.lives), hearts: st.lives });
    if (typeof st.hearts === "number") out.push({ k: "hearts", label: "Hearts", value: String(st.hearts), hearts: st.hearts });
    if (typeof st.day === "number") out.push({ k: "day", label: "Day", value: st.time ? `${st.day} · ${st.time}` : String(st.day) });
    if (typeof st.blocks === "number") out.push({ k: "blocks", label: "Blocks", value: String(st.blocks) });
    if (typeof st.fish === "number") out.push({ k: "fish", label: "Fish", value: "★".repeat(Math.max(0, Math.min(3, st.fish))) + "☆".repeat(Math.max(0, 3 - Math.min(3, st.fish))) });
    if (typeof st.moves === "number") out.push({ k: "moves", label: "Moves", value: String(st.moves) });
    if (typeof st.stars_total === "number" && st.stars_total > 0) out.push({ k: "stars", label: "Stars", value: String(st.stars_total) });
    if (typeof st.time_left === "number") out.push({ k: "time", label: "Time", value: mmss(st.time_left), tone: st.time_left <= 10 ? "bad" : st.time_left <= 30 ? "warn" : undefined });
    return out;
  }

  /** The match flow as a chip: {label, tone}. */
  function flowLabel(st) {
    const f = (st && st.flow) || "";
    switch (f) {
      case "attract": return { label: (st.player === "fly" ? "Fruit-fly brain playing" : st.player === "you" ? "Playing" : "Demo · AI playing"), tone: st.player === "you" ? "ok" : "gold" };
      case "home": return { label: "Choosing a mode", tone: "warn" };
      case "teams": return { label: "Pick your side", tone: "warn" };
      case "intro": return { label: "Get ready", tone: "ember" };
      case "play": return { label: "Live", tone: "ok" };
      case "outro": return { label: "Results", tone: "gold" };
      default: return null;
    }
  }

  /** The intro countdown the panel shows (games_core.draw_intro): 3 · 2 · 1 every 0.6 s, then GO. */
  function countdown(elapsed) {
    const n = 3 - Math.floor(Math.max(0, elapsed) / 0.6);
    return n > 0 ? String(n) : "GO";
  }

  /** The results banner: {title, sub, color} or null. */
  function outcomeBanner(app, st, seats) {
    st = st || {};
    if (st.flow !== "outro") return null;
    const o = st.outcome || {};
    if (o.team === 0 || o.team === 1) return { title: TEAM_NAME[o.team] + " wins", sub: seats.filter((s) => s.team === o.team).map((s) => s.name).join(" · "), color: TEAM[o.team] };
    if (o.seat != null) {
      const s = seats.find((x) => x.seat === o.seat);
      const humans = seats.filter((x) => x.human).length;
      const name = s ? s.name : "Player " + o.seat;
      return { title: (o.seat === 1 && humans <= 1 ? "You win" : name + " wins"), sub: s && !s.human ? "The CPU takes it" : "", color: s ? s.color : SEAT[o.seat] || "#ffcc33" };
    }
    if (o.text) return { title: String(o.text), sub: st.score ? "Score " + num(st.score) : "", color: "#ffcc33" };
    const best = Number(st.best) || 0, score = Number(st.score) || 0;
    return { title: "Game over", sub: score > 0 && score >= best ? `New best · ${num(score)}` : `Score ${num(score)} · Best ${num(best)}`, color: score > 0 && score >= best ? "#ffcc33" : "#efece4" };
  }

  /** Rows for the controls legend: [{keys:["←","→"], label}]. */
  function controlsFor(app, st) {
    const h = HINTS[app] || {};
    const rows = [];
    if (h.move) rows.push({ keys: ["↑", "↓", "←", "→"], label: h.move });
    else {
      const seen = new Map();
      for (const k of ["up", "down", "left", "right"]) if (h[k]) seen.set(h[k], [...(seen.get(h[k]) || []), GLYPH[k]]);
      if (!seen.size) rows.push({ keys: ["↑", "↓", "←", "→"], label: "Move" });
      for (const [label, keys] of seen) rows.push({ keys, label });
    }
    if (h.a) rows.push({ keys: ["A"], label: h.a });
    if (h.b) rows.push({ keys: ["B"], label: h.b });
    if (!h.a && !h.b && !h.move && !Object.keys(h).length) rows.push({ keys: ["A"], label: "Action" });
    const f = st && st.flow;
    if (f === "outro") return [{ keys: ["A"], label: "Rematch" }, { keys: ["B"], label: "Back to the menu" }];
    if (f === "teams") return [{ keys: ["←", "→"], label: "Choose a side" }, { keys: ["A"], label: "Ready" }, { keys: ["B"], label: "Not ready / back" }];
    if (f === "home") return [{ keys: ["↑", "↓"], label: "Choose a row" }, { keys: ["←", "→"], label: "Change it" }, { keys: ["A"], label: "Start" }];
    return rows;
  }

  /** Is a lobby open with seats left? (the panel shows its QR then; the TV shows "scan to join") */
  function lobbyOpen(st, lobby) {
    if (!lobby || !lobby.url) return false;
    if (st && typeof st.lobby === "boolean") return st.lobby || (lobby.seats || []).length < Math.max(1, (lobby.max_players || 1) - 1);
    return (lobby.seats || []).length < Math.max(1, (lobby.max_players || 1) - 1);
  }

  /** Board duels: who moves and the tally. */
  function boardView(app, st, seats) {
    st = st || {};
    const w = st.wins || {};
    const tally = app === "tictactoe" ? { 1: w.x || 0, 2: w.o || 0, draws: w.draws || 0 } : { 1: w["1"] || 0, 2: w["2"] || 0, draws: w.draws || 0 };
    const sym = app === "tictactoe" ? { 1: "X", 2: "O" } : { 1: "●", 2: "●" };
    const players = [1, 2].map((n) => {
      const s = seats.find((x) => x.seat === n) || { seat: n, name: n === 1 ? "Player 1" : "CPU", color: SEAT[n], human: n === 1 };
      return Object.assign({}, s, { symbol: sym[n], wins: tally[n], toMove: st.turn === n && (st.flow === "play" || st.flow === "attract") });
    });
    return { players, draws: tally.draws, turn: st.turn || null };
  }

  /** Rock paper scissors: everything the duel arena needs, from status.rps. */
  function rpsView(st) {
    const r = (st && st.rps) || null;
    if (!r) return null;
    const pl = (s) => {
      const p = (r.players || {})[s] || {};
      return { seat: s, name: p.name || "P" + s, color: p.color || SEAT[s] || "#fff", human: !!p.human };
    };
    const [a, b] = r.pair || [1, 2];
    const side = (s) => Object.assign(pl(s), {
      wins: (r.wins || {})[s] || 0,
      locked: (r.locked || []).map(Number).includes(Number(s)),
      pick: r.picks ? r.picks[s] : null,
      tell: r.tell ? r.tell[s] : null,
    });
    const left = side(a), right = side(b);
    let result = null;
    if (r.picks && r.winner !== undefined) result = r.winner === 0 ? "draw" : r.winner === 1 ? "left" : "right";
    let bracket = null;
    const t = r.tour;
    if (t && t.format === "knockout") {
      bracket = { format: "knockout", rounds: (t.rounds || []).map((rnd) => rnd.map(([x, y, w]) => ({ a: x == null ? null : pl(x), b: y == null ? null : pl(y), winner: w, bye: y == null }))) };
    } else if (t && t.format === "robin") {
      bracket = { format: "robin", table: (t.table || []).map((row) => Object.assign(pl(row.seat), row)) };
    }
    return {
      phase: r.phase,
      kind: r.kind,
      match: r.match,
      round: r.round,
      firstTo: r.first_to || 1,
      left,
      right,
      result,
      timer: r.phase === "pick" ? { left: r.left, of: r.timer } : null,
      champion: r.champion != null ? pl(r.champion) : null,
      bracket,
      art: r.art || null,
    };
  }

  /** Trivia: question, options, pick. */
  function triviaView(st) {
    st = st || {};
    const opts = Array.isArray(st.options) ? st.options : [];
    return {
      phase: st.phase || "idle",
      question: st.question || null,
      options: opts.map((o, i) => ({ letter: "ABCDEFGH"[i], text: String(o), selected: st.phase === "board" || st.phase === "reveal" ? st.selected === i : false })),
      category: st.category || "",
      difficulty: st.difficulty || "",
      score: st.score || 0,
      answered: st.answered || 0,
      streak: st.streak || 0,
      player: st.player === "you" ? "Playing" : "Auto-play",
    };
  }

  /** Which family layout a game uses. */
  function family(app, st) {
    if (app === "rps") return "rps";
    if (app === "trivia") return "quiz";
    if (app === "chess") return "chess";
    if (PET_IDS.has(app)) return "pet";
    if (BOARD.has(app)) return "board";
    const k = matchKind(app, st);
    return k === "solo" ? "solo" : k;
  }

  const API = { MODES, HINTS, SEAT, TEAM, esc, ordinal, mmss, num, mix, modeInfo, matchKind, seatList, leaders, teamsOf, globalStats, flowLabel, countdown, outcomeBanner, controlsFor, lobbyOpen, boardView, rpsView, triviaView, family, chessHtml, isGame: (app, meta) => GAME_IDS.has(app) || PET_IDS.has(app) };
  globalThis.TVGames = API;

  // ================================================================== DOM scene
  const CSS = `
.tvg{position:absolute;inset:0;display:grid;grid-template-columns:912px 1fr;gap:44px;padding:36px 52px 36px 48px;box-sizing:border-box;font-family:var(--font,system-ui,sans-serif);color:var(--ink-1,#efece4);
  background:radial-gradient(1200px 900px at 22% 50%,rgba(255,255,255,.05),transparent 60%),var(--chassis-0,#08080a);overflow:hidden}
.tvg *{box-sizing:border-box}
.tvg-hero{position:relative;display:flex;align-items:center;justify-content:center;min-height:0}
.tvg-hero .tv-bezel{position:relative;padding:22px;border-radius:30px;line-height:0}
.tvg-glow{position:absolute;inset:-6%;opacity:.3;pointer-events:none;background:radial-gradient(closest-side,var(--tvg-glow,#00c8ff),transparent)}
.tvg-badge{position:absolute;left:8px;top:2px;z-index:3}
.tvg-over{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;z-index:4}
.tvg-count{font-size:360px;font-weight:900;line-height:1;color:#fff;text-shadow:0 0 60px var(--c,#ff4818),0 10px 0 rgba(0,0,0,.4);animation:tvg-pop .6s cubic-bezier(.2,.9,.25,1.15) both}
@keyframes tvg-pop{0%{transform:scale(1.8);opacity:0}100%{transform:scale(1);opacity:1}}
.tvg-banner{position:absolute;left:-60px;right:-60px;top:50%;transform:translateY(-50%);padding:34px 40px;text-align:center;
  background:linear-gradient(90deg,transparent,rgba(8,8,10,.92) 12%,rgba(8,8,10,.92) 88%,transparent);border-top:4px solid var(--c);border-bottom:4px solid var(--c);
  box-shadow:0 0 120px -10px var(--c);animation:tvg-ribbon .7s cubic-bezier(.2,.9,.25,1.15) both}
.tvg-banner b{display:block;font-size:110px;font-weight:900;line-height:1.02;color:var(--c);text-transform:uppercase;letter-spacing:.02em;text-shadow:0 0 40px var(--c)}
.tvg-banner span{display:block;margin-top:10px;font-size:36px;color:var(--ink-2,#a9a7b0)}
@keyframes tvg-ribbon{0%{transform:translateY(-50%) scaleX(.2);opacity:0}100%{transform:translateY(-50%) scaleX(1);opacity:1}}
.tvg-confetti{position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:3}
.tvg-confetti i{position:absolute;top:-30px;width:16px;height:26px;border-radius:3px;animation:tvg-fall linear infinite;will-change:transform}
@keyframes tvg-fall{to{transform:translateY(1060px) rotate(720deg)}}
.tvg-side{display:flex;flex-direction:column;gap:22px;min-width:0;min-height:0}
.tvg-head .tv-label{font-size:24px}
.tvg-title{font-size:76px;font-weight:850;line-height:1;margin:6px 0 14px;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tvg-chips{display:flex;flex-wrap:wrap;gap:12px}
.tvg-chips .tv-chip{font-size:26px}
.tvg-main{flex:1;min-height:0;display:flex;flex-direction:column;gap:18px;overflow:hidden}
.tvg-stats{display:flex;flex-wrap:wrap;gap:14px}
.tvg-stat{padding:14px 22px;border-radius:16px;background:var(--chassis-2,#16161b);border:1px solid var(--line,#25252d);min-width:150px}
.tvg-stat .tv-label{font-size:20px}
.tvg-stat b{display:block;font-size:46px;font-weight:800;line-height:1.1;font-variant-numeric:tabular-nums}
.tvg-stat[data-tone=bad] b{color:var(--bad,#ff3b5c);animation:tvg-blink 1s steps(2) infinite}
.tvg-stat[data-tone=warn] b{color:var(--warn,#ffb020)}
@keyframes tvg-blink{50%{opacity:.45}}
.tvg-hearts{color:#ff3b5c;letter-spacing:4px}
.tvg-foot{display:flex;gap:18px;align-items:stretch}
.tvg-legend{flex:1;padding:16px 22px;display:flex;flex-direction:column;gap:10px;min-width:0}
.tvg-legend .rows{display:flex;flex-wrap:wrap;gap:10px 28px}
.tvg-legend .row{display:flex;align-items:center;gap:12px;font-size:26px;color:var(--ink-2,#a9a7b0)}
.tvg-keys{display:flex;gap:5px}
.tvg-key{display:inline-flex;align-items:center;justify-content:center;min-width:44px;height:44px;padding:0 8px;border-radius:9px;font-size:24px;font-weight:800;color:var(--ink-1,#efece4);
  background:linear-gradient(180deg,var(--chassis-4,#27272f),var(--chassis-2,#16161b));border:1px solid var(--line-2,#33333d);box-shadow:0 3px 0 rgba(0,0,0,.6)}
.tvg-join{position:relative;display:flex;gap:18px;align-items:center;padding:16px 22px 16px 16px;border:2px solid var(--gold,#ffcc33)}
.tvg-join::after{content:"";position:absolute;inset:-2px;border-radius:inherit;pointer-events:none;box-shadow:0 0 50px -12px var(--gold,#ffcc33);opacity:0;animation:tvg-breathe 2.4s ease-in-out infinite}
.tvg-join canvas{width:170px;height:170px;border-radius:10px;background:#fff}
.tvg-join b{display:block;font-size:44px;font-weight:900;letter-spacing:.12em;color:var(--gold,#ffcc33)}
.tvg-join span{display:block;font-size:24px;color:var(--ink-2,#a9a7b0);max-width:200px}
@keyframes tvg-breathe{50%{opacity:1}}
/* scoreboard */
.tvg-solo{display:flex;flex-direction:column;justify-content:center;flex:1;padding:24px 34px}
.tvg-solo .tvg-score{font-size:180px;font-weight:900;line-height:.95;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
.tvg-solo .tvg-best{font-size:40px;color:var(--ink-2,#a9a7b0);margin-top:10px}
.tvg-solo .tvg-best.new{color:var(--gold,#ffcc33)}
.tvg-who{display:flex;align-items:center;gap:14px;font-size:32px;color:var(--ink-2,#a9a7b0);margin-bottom:10px}
.tvg-seats{display:grid;gap:14px;grid-template-columns:1fr}
.tvg-seats.n3,.tvg-seats.n4{grid-template-columns:1fr 1fr}
.tvg-seat{position:relative;display:flex;align-items:center;gap:18px;padding:16px 22px 16px 26px;border-radius:18px;background:linear-gradient(180deg,var(--chassis-2,#16161b),var(--chassis-1,#0f0f13));
  border:1px solid var(--line,#25252d);overflow:hidden;min-width:0;transition:opacity .4s,filter .4s}
.tvg-seat::before{content:"";position:absolute;left:0;top:0;bottom:0;width:10px;background:var(--c)}
.tvg-seat.lead{border-color:var(--c);box-shadow:0 0 36px -8px var(--c)}
.tvg-seat.out{opacity:.38;filter:grayscale(.8)}
.tvg-seat.turn{border-color:var(--c);box-shadow:0 0 0 3px var(--c),0 0 50px -6px var(--c)}
.tvg-seat.turn::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;box-shadow:inset 0 0 40px -4px var(--c);opacity:.3;animation:tvg-turn 1.4s ease-in-out infinite}
@keyframes tvg-turn{50%{opacity:1}}
.tvg-av{flex:none;width:72px;height:72px;border-radius:14px;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:900;color:var(--c);image-rendering:pixelated}
.tvg-seat .who{flex:1;min-width:0}
.tvg-seat .nm{font-size:36px;font-weight:800;color:var(--c);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tvg-seat .sub{font-size:22px;color:var(--ink-3,#6f6d78);text-transform:uppercase;letter-spacing:.08em;margin-top:2px}
.tvg-seat .val{text-align:right;flex:none}
.tvg-seat .val b{display:block;font-size:64px;font-weight:900;line-height:1;font-variant-numeric:tabular-nums}
.tvg-seat .val small{font-size:20px;color:var(--ink-3,#6f6d78);text-transform:uppercase;letter-spacing:.1em}
.tvg-seats.n3 .tvg-seat .val b,.tvg-seats.n4 .tvg-seat .val b{font-size:52px}
.tvg-crown{position:absolute;right:14px;top:6px;font-size:26px;color:var(--gold,#ffcc33)}
.tvg-tag{display:inline-block;margin-left:10px;padding:2px 10px;border-radius:99px;font-size:18px;font-weight:800;letter-spacing:.08em;background:rgba(255,255,255,.08);color:var(--ink-2,#a9a7b0);vertical-align:middle}
.tvg-tag.ok{background:rgba(61,220,151,.18);color:var(--ok,#3ddc97)}
.tvg-tag.bad{background:rgba(255,59,92,.18);color:var(--bad,#ff3b5c)}
.tvg-vs{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:stretch;flex:1;min-height:0}
.tvg-team{border-radius:22px;padding:20px;background:linear-gradient(180deg,color-mix(in srgb,var(--c) 18%,#111) ,var(--chassis-1,#0f0f13));border:2px solid color-mix(in srgb,var(--c) 55%,transparent);display:flex;flex-direction:column;gap:12px;min-width:0}
.tvg-team.win{box-shadow:0 0 60px -6px var(--c)}
.tvg-team h3{margin:0;font-size:40px;font-weight:900;color:var(--c);text-transform:uppercase;letter-spacing:.06em}
.tvg-team .tot{font-size:96px;font-weight:900;line-height:1;font-variant-numeric:tabular-nums}
.tvg-team .tot small{display:block;font-size:20px;color:var(--ink-3,#6f6d78);letter-spacing:.1em;text-transform:uppercase}
.tvg-mem{display:flex;align-items:center;gap:12px;font-size:30px;font-weight:700;min-width:0}
.tvg-mem i{flex:none;width:22px;height:22px;border-radius:6px;background:var(--c)}
.tvg-mem span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tvg-mem em{margin-left:auto;font-style:normal;font-size:26px;color:var(--ink-2,#a9a7b0)}
.tvg-vsword{align-self:center;font-size:56px;font-weight:900;color:var(--ink-3,#6f6d78)}
.tvg-pick{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;flex:1}
.tvg-pick .col{border-radius:20px;padding:16px;border:2px dashed var(--line-2,#33333d);display:flex;flex-direction:column;gap:12px}
.tvg-pick .col h4{margin:0;font-size:28px;text-transform:uppercase;letter-spacing:.1em;color:var(--c,#a9a7b0)}
.tvg-pick .col.a,.tvg-pick .col.b{border-style:solid;border-color:color-mix(in srgb,var(--c) 60%,transparent);background:color-mix(in srgb,var(--c) 10%,transparent)}
.tvg-pill{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:14px;background:var(--chassis-2,#16161b);font-size:28px;font-weight:800;color:var(--p)}
.tvg-pill.ready::after{content:"READY";margin-left:auto;font-size:18px;color:var(--ok,#3ddc97);letter-spacing:.1em}
.tvg-board{display:grid;grid-template-columns:1fr auto 1fr;gap:20px;align-items:center;flex:1}
.tvg-duel{position:relative;border-radius:24px;padding:26px 20px;text-align:center;background:linear-gradient(180deg,var(--chassis-2,#16161b),var(--chassis-1,#0f0f13));border:2px solid var(--line,#25252d)}
.tvg-duel .sym{font-size:120px;font-weight:900;line-height:1;color:var(--c);text-shadow:0 0 40px var(--c)}
.tvg-duel .nm{font-size:38px;font-weight:800;margin-top:8px;color:var(--c);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tvg-duel .w{font-size:88px;font-weight:900;line-height:1;margin-top:10px;font-variant-numeric:tabular-nums}
.tvg-duel .w small{display:block;font-size:20px;color:var(--ink-3,#6f6d78);letter-spacing:.12em}
.tvg-duel.turn{border-color:var(--c);box-shadow:0 0 70px -6px var(--c)}
.tvg-duel .mv{position:absolute;left:50%;top:-22px;transform:translateX(-50%);padding:6px 18px;border-radius:99px;background:var(--c);color:#000;font-weight:900;font-size:22px;letter-spacing:.1em;white-space:nowrap}
.tvg-draws{text-align:center;font-size:24px;color:var(--ink-3,#6f6d78);letter-spacing:.12em}
.tvg-draws b{display:block;font-size:64px;color:var(--ink-2,#a9a7b0)}
.tvg-note{font-size:30px;color:var(--ink-2,#a9a7b0);line-height:1.35}
/* rps */
.tvg.rps{grid-template-columns:1fr 520px}
.tvg-arena{position:relative;display:flex;flex-direction:column;align-items:stretch;justify-content:center;gap:24px}
.tvg-hands{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:20px}
.tvg-hand{display:flex;flex-direction:column;align-items:center;gap:14px;min-width:0}
.tvg-hand canvas{width:400px;height:327px;image-rendering:pixelated}
.tvg-arena .tvg-main{flex:none;max-height:250px}
.tvg-arena .tvg-bracket{flex-direction:row;flex-wrap:wrap;gap:18px;justify-content:center}
.tvg-arena .tvg-bracket table{width:auto;min-width:560px}
.tvg-coop{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:16px 30px}
.tvg-coop .tvg-score{font-size:110px;font-weight:900;line-height:1;font-variant-numeric:tabular-nums}
.tvg-hand .nm{font-size:52px;font-weight:900;color:var(--c);max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tvg-hand.win canvas{filter:drop-shadow(0 0 40px var(--c))}
.tvg-hand.lose{opacity:.45}
.tvg-pips{display:flex;gap:12px}
.tvg-pips i{width:34px;height:34px;border-radius:50%;border:3px solid var(--c);background:transparent}
.tvg-pips i.on{background:var(--c);box-shadow:0 0 18px var(--c)}
.tvg-pickword{font-size:34px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-1,#efece4)}
.tvg-mid{display:flex;flex-direction:column;align-items:center;gap:10px}
.tvg-mid .vs{font-size:96px;font-weight:900;color:var(--ink-3,#6f6d78)}
.tvg-ring{position:relative;width:170px;height:170px}
.tvg-ring svg{position:absolute;inset:0;transform:rotate(-90deg)}
.tvg-ring b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:76px;font-weight:900;font-variant-numeric:tabular-nums}
.tvg-rpsmsg{text-align:center;font-size:64px;font-weight:900;letter-spacing:.04em;text-transform:uppercase;min-height:80px}
.tvg-pump canvas{animation:tvg-pump .42s ease-in-out infinite alternate}
@keyframes tvg-pump{to{transform:translateY(-36px)}}
.tvg-lock{font-size:22px;font-weight:900;letter-spacing:.12em;padding:6px 16px;border-radius:99px;background:rgba(61,220,151,.18);color:var(--ok,#3ddc97)}
.tvg-wait{font-size:22px;font-weight:900;letter-spacing:.12em;padding:6px 16px;border-radius:99px;background:rgba(255,255,255,.06);color:var(--ink-3,#6f6d78)}
.tvg-inset .tv-bezel{padding:14px;border-radius:20px;line-height:0;align-self:flex-start}
.tvg-bracket{display:flex;flex-direction:column;gap:10px;font-size:26px}
.tvg-bracket .rnd{display:flex;flex-direction:column;gap:8px}
.tvg-bracket .m{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:12px;background:var(--chassis-2,#16161b)}
.tvg-bracket .m span{font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:170px}
.tvg-bracket .m span.w{text-decoration:underline;text-underline-offset:6px}
.tvg-bracket .m span.l{opacity:.4}
.tvg-bracket table{border-collapse:collapse;width:100%;font-size:26px}
.tvg-bracket td{padding:6px 8px;border-bottom:1px solid var(--line,#25252d)}
/* quiz */
.tvg.quiz{grid-template-columns:640px 1fr}
.tvg-q{font-size:50px;font-weight:800;line-height:1.2;margin:4px 0 8px}
.tvg-opts{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.tvg-opt{display:flex;gap:16px;align-items:center;padding:18px 20px;border-radius:18px;background:var(--chassis-2,#16161b);border:2px solid var(--line,#25252d);font-size:32px;font-weight:700;min-height:100px}
.tvg-opt i{flex:none;width:56px;height:56px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-style:normal;font-weight:900;background:var(--chassis-4,#27272f)}
.tvg-opt.sel{border-color:var(--gold,#ffcc33);box-shadow:0 0 40px -8px var(--gold,#ffcc33)}
.tvg-opt.sel i{background:var(--gold,#ffcc33);color:#000}
/* the lite tier (tv.js): no blurred shadows or glows, they are full repaints on a weak TV stick */
html[data-q=lite] .tvg-glow{display:none}
html[data-q=lite] .tvg-count{text-shadow:0 8px 0 rgba(0,0,0,.4)}
html[data-q=lite] .tvg-banner{box-shadow:none}
html[data-q=lite] .tvg-banner b{text-shadow:none}
html[data-q=lite] .tvg-seat.lead,html[data-q=lite] .tvg-team.win,html[data-q=lite] .tvg-duel.turn,html[data-q=lite] .tvg-opt.sel{box-shadow:none}
html[data-q=lite] .tvg-seat.turn{box-shadow:0 0 0 3px var(--c)}
html[data-q=lite] .tvg-seat.turn::after,html[data-q=lite] .tvg-join::after{display:none}
html[data-q=lite] .tvg-duel .sym{text-shadow:none}
html[data-q=lite] .tvg-hand.win canvas{filter:none}
html[data-q=lite] .tvg-pips i.on{box-shadow:none}
`;

  function ensureCss() {
    if (typeof document === "undefined" || document.getElementById("tvg-css")) return;
    const s = document.createElement("style");
    s.id = "tvg-css";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /** Set innerHTML only when it changed (keeps CSS animations running at 5 Hz updates). */
  function put(el, html) {
    if (el && el.__h !== html) {
      el.__h = html;
      el.innerHTML = html;
      return true;
    }
    return false;
  }

  function chip(label, tone) {
    return `<span class="tv-chip"${tone ? ` data-tone="${tone}"` : ""}>${esc(label)}</span>`;
  }

  function hearts(n) {
    n = Math.max(0, Math.min(9, Number(n) || 0));
    return `<span class="tvg-hearts">${"♥".repeat(n)}</span>`;
  }

  function avatarHtml(s) {
    return `<div class="tvg-av" data-av="${esc(s.avatar || "")}" data-col="${esc(s.ownColor || s.color)}">${s.avatar ? "" : esc((s.name || "?").trim().charAt(0).toUpperCase())}</div>`;
  }

  function paintAvatars(root, ctx) {
    if (!ctx.drawAvatar) return;
    for (const el of root.querySelectorAll(".tvg-av[data-av]")) {
      const id = el.getAttribute("data-av");
      if (!id || el.__av === id) continue;
      el.__av = id;
      const c = document.createElement("canvas");
      c.className = "tv-avatar";
      c.style.width = c.style.height = "64px";
      try {
        ctx.drawAvatar(c, id, el.getAttribute("data-col"));
        el.textContent = "";
        el.appendChild(c);
      } catch (e) {
        /* keep the initial */
      }
    }
  }

  function seatSub(s) {
    if (!s.human) return "CPU";
    if (s.seat === 1) return "Host";
    return "Phone";
  }

  function seatCard(s, opts) {
    const cls = ["tvg-seat"];
    if (opts.lead) cls.push("lead");
    if (!s.alive) cls.push("out");
    if (opts.turn) cls.push("turn");
    const h = s.headline;
    const extra = s.lives !== undefined ? ` ${hearts(s.lives)}` : "";
    const tag = !s.alive ? `<span class="tvg-tag bad">OUT</span>` : opts.turn ? `<span class="tvg-tag ok">TURN</span>` : "";
    return `<div class="${cls.join(" ")}" style="--c:${esc(s.color)}">${opts.lead ? '<span class="tvg-crown">♛</span>' : ""}${avatarHtml(s)}
<div class="who"><div class="nm">${esc(s.name)}${tag}</div><div class="sub">P${s.seat} · ${seatSub(s)}${extra}</div></div>
${h ? `<div class="val"><b>${esc(h.text)}</b><small>${esc(h.label)}</small></div>` : ""}</div>`;
  }

  function soloHtml(app, st, seats) {
    const score = Number(st.score) || 0, best = Number(st.best) || 0;
    const who = st.player === "fly" ? "Fruit-fly brain" : st.player === "you" ? (seats[0] ? seats[0].name : "Player 1") : "AI demo";
    const isNew = score > 0 && score >= best && st.flow !== "attract";
    return `<div class="tvg-solo tv-card"><div class="tvg-who">${chip(who, st.player === "you" ? "ok" : "gold")}</div>
<div class="tv-label">Score</div><div class="tvg-score">${esc(num(score))}</div>
<div class="tvg-best${isNew ? " new" : ""}">${isNew ? "★ New best" : "Best " + esc(num(best))}</div></div>`;
  }

  function coopHtml(app, st, seats) {
    const lead = leaders(seats);
    return `<div class="tvg-coop tv-card"><div><div class="tv-label">Team score</div><div class="tvg-score">${esc(num(st.score || 0))}</div></div>
<div class="tvg-best" style="font-size:34px;color:var(--ink-2,#a9a7b0)">Best ${esc(num(st.best || 0))}</div></div>
<div class="tvg-seats n${Math.min(4, seats.length)}">${seats.map((s) => seatCard(s, { lead: lead.includes(s.seat), turn: st.turn === s.seat && st.flow === "play" })).join("")}</div>`;
  }

  function ffaHtml(app, st, seats) {
    const lead = leaders(seats);
    return `<div class="tvg-seats n${Math.min(4, seats.length)}">${seats.map((s) => seatCard(s, { lead: lead.includes(s.seat) })).join("")}</div>`;
  }

  function versusHtml(app, st, seats) {
    const teams = teamsOf(seats);
    const won = st.flow === "outro" && st.outcome ? st.outcome.team : null;
    const col = (t) => `<div class="tvg-team${won === t.team ? " win" : ""}" style="--c:${t.color}"><h3>${t.name}</h3>
${t.total != null ? `<div class="tot">${esc(num(t.total))}<small>${esc(t.label)}</small></div>` : ""}
${t.members.map((m) => `<div class="tvg-mem" style="--c:${esc(m.color)}"><i></i><span>${esc(m.name)}</span><em>${m.headline ? esc(m.headline.text) : m.human ? "" : "CPU"}</em></div>`).join("")}
${t.members.length ? "" : '<div class="tvg-note">CPU fills this side</div>'}</div>`;
    return `<div class="tvg-vs">${col(teams[0])}<div class="tvg-vsword">VS</div>${col(teams[1])}</div>`;
  }

  function sidesHtml(app, st, seats) {
    const pill = (s) => `<div class="tvg-pill${s.ready ? " ready" : ""}" style="--p:${esc(s.ownColor)}">${esc(s.name)}</div>`;
    const people = seats.filter((s) => s.human);
    const col = (t, cls, title, c) => `<div class="col ${cls}" style="--c:${c}"><h4>${title}</h4>${people.filter((s) => s.team === t).map(pill).join("")}</div>`;
    const ai = seats.length - people.length;
    return `<div class="tvg-note">Everyone picks a side with ← →, then presses A.${ai ? ` ${ai} CPU player${ai > 1 ? "s" : ""} fill the smaller side.` : ""}</div>
<div class="tvg-pick">${col(0, "a", "Team A", TEAM[0])}${col(null, "", "Undecided", "#a9a7b0")}${col(1, "b", "Team B", TEAM[1])}</div>`;
  }

  function boardHtml(app, st, seats) {
    const v = boardView(app, st, seats);
    const card = (p) => `<div class="tvg-duel${p.toMove ? " turn" : ""}" style="--c:${esc(p.color)}">${p.toMove ? '<div class="mv">TO MOVE</div>' : ""}
<div class="sym">${esc(p.symbol)}</div><div class="nm">${esc(p.name)}</div><div class="w">${p.wins}<small>WINS</small></div></div>`;
    const variant = st.map && st.map !== "classic" ? `<div class="tvg-note">Variant: <b>${esc(st.map === "vanish" ? "Vanishing marks — only your last three stay" : st.map === "misere" ? "Misère — three in a row loses" : st.map === "popout" ? "Pop-out — pull a disc from the bottom" : st.map === "stones" ? "Stones — blocked cells" : st.map)}</b></div>` : "";
    return `<div class="tvg-board">${card(v.players[0])}<div class="tvg-draws"><b>${v.draws}</b>DRAWS</div>${card(v.players[1])}</div>${variant}`;
  }

  function lobbyHtml(st, seats) {
    const people = seats.filter((s) => s.human);
    if (!people.length) return '<div class="tvg-note">Waiting for players…</div>';
    return `<div class="tvg-seats n${Math.min(4, people.length)}">${people.map((s) => seatCard(s, {})).join("")}</div>`;
  }

  function attractHtml(app, st, meta) {
    const max = (meta && meta.max_players) || st.max_players || 1;
    return `<div class="tvg-note">${max > 1 ? `Up to ${max} players — grab a controller or scan the code with your phone. ` : "Press any key to take over from the AI. "}Press B on the host for the menu.</div>`;
  }

  function petHtml(app, st) {
    const rows = [];
    if (st.character) rows.push(["Character", st.character]);
    if (st.world) rows.push(["World", st.world]);
    if (st.animation || st.doing) rows.push(["Doing", st.animation || st.doing]);
    if (st.period) rows.push(["Time", st.period]);
    if (st.music) rows.push(["Music", "Dancing to the music"]);
    return `<div class="tvg-stats">${rows.map(([l, v]) => `<div class="tvg-stat"><div class="tv-label">${esc(l)}</div><b>${esc(String(v).replace(/_/g, " "))}</b></div>`).join("")}</div>`;
  }

  function chessHtml(app, st) {
    if (!st || st.loaded === false) return '<div class="tvg-note">Fetching today\'s puzzle…</div>';
    const moves = st.solution ? String(st.solution).split(/\s+/).filter(Boolean).length : 0; // only the count — never the moves
    const ply = st.manual_ply;
    return `<div class="tvg-q">${esc(st.title || "Puzzle")}</div>
<div class="tvg-chips">${chip((st.to_move === "black" ? "Black" : "White") + " to move", st.to_move === "black" ? "" : "gold")}${moves ? chip(`${moves}-move solution`) : ""}${ply != null ? chip(`Move ${ply} / ${moves}`, "ember") : ""}</div>
<div class="tvg-note" style="margin-top:14px">Find the best move. The panel plays the solution through.</div>`;
  }

  function quizHtml(st) {
    const v = triviaView(st);
    if (!v.question) return '<div class="tvg-note">Fetching questions…</div>';
    return `<div class="tvg-chips">${v.category ? chip(v.category, "gold") : ""}${v.difficulty ? chip(v.difficulty) : ""}${chip(v.player, v.player === "Playing" ? "ok" : "")}</div>
<div class="tvg-q">${esc(v.question)}</div>
<div class="tvg-opts">${v.options.map((o) => `<div class="tvg-opt${o.selected ? " sel" : ""}"><i>${o.letter}</i><span>${esc(o.text)}</span></div>`).join("")}</div>`;
  }

  // ------------------------------------------------------------------ rps arena
  function drawHand(canvas, art, move, color, flip, ratio) {
    const rows = art && art[move];
    const W = 22, H = 18, px = 20;
    const r = Math.max(1, ratio || 1);
    canvas.width = W * px * r;
    canvas.height = H * px * r;
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, canvas.width, canvas.height);
    if (!rows) return;
    const glove = mix(color, "#ffffff", 0.35);
    const pal = { c: color, h: glove, l: mix(color, "#ffffff", 0.72), s: shade(glove, 0.5) };
    const w = Math.max(...rows.map((x) => x.length)), h = rows.length;
    const ox = Math.floor((W - w) / 2), oy = Math.floor((H - h) / 2);
    const p = px * r, gap = Math.max(1, Math.round(p * 0.08));
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const c = pal[row[x]];
        if (!c) continue;
        const xx = flip ? w - 1 - x : x;
        g.fillStyle = c;
        g.fillRect((ox + xx) * p + gap, (oy + y) * p + gap, p - 2 * gap, p - 2 * gap);
      }
    });
  }

  // ------------------------------------------------------------------ scene
  function makeScene() {
    let root, el = {}, lastFlow = null, flowAt = 0, lastQr = null, lastFam = null;

    function build(fam) {
      lastFam = fam;
      root.innerHTML = "";
      const wrap = document.createElement("div");
      wrap.className = "tvg" + (fam === "rps" ? " rps" : fam === "quiz" ? " quiz" : "");
      if (fam === "rps") {
        wrap.innerHTML = `<div class="tvg-arena"><div class="tvg-hands">
<div class="tvg-hand" data-s="l"><canvas></canvas><div class="nm"></div><div class="tvg-pips"></div><div class="st"></div></div>
<div class="tvg-mid"></div>
<div class="tvg-hand" data-s="r"><canvas></canvas><div class="nm"></div><div class="tvg-pips"></div><div class="st"></div></div></div>
<div class="tvg-rpsmsg"></div><div class="tvg-main"></div><div class="tvg-over"></div><div class="tvg-confetti"></div></div>
<div class="tvg-side"><div class="tvg-head"><div class="tv-label kick"></div><div class="tvg-title"></div><div class="tvg-chips flow"></div></div>
<div class="tvg-inset"><div class="tv-bezel"><canvas class="panel"></canvas></div></div>
<div class="tvg-foot"><div class="tvg-legend tv-card"></div></div><div class="tvg-foot join"></div></div>`;
      } else {
        wrap.innerHTML = `<div class="tvg-hero"><div class="tvg-glow"></div><div class="tv-bezel"><canvas class="panel"></canvas></div><div class="tvg-confetti"></div><div class="tvg-over"></div></div>
<div class="tvg-side"><div class="tvg-head"><div class="tv-label kick"></div><div class="tvg-title"></div><div class="tvg-chips flow"></div></div>
<div class="tvg-main"></div><div class="tvg-stats"></div><div class="tvg-foot"><div class="tvg-legend tv-card"></div><div class="joinbox"></div></div></div>`;
      }
      root.appendChild(wrap);
      const q = (s) => wrap.querySelector(s);
      el = {
        wrap, panel: q("canvas.panel"), kick: q(".kick"), title: q(".tvg-title"), flow: q(".flow"), main: q(".tvg-main"),
        stats: q(".tvg-stats"), legend: q(".tvg-legend"), join: q(".joinbox") || q(".join"), over: q(".tvg-over"), confetti: q(".tvg-confetti"),
        glow: q(".tvg-glow"), hands: q(".tvg-hands"), msg: q(".tvg-rpsmsg"),
      };
      lastQr = null;
    }

    function pitch(fam) {
      return fam === "rps" ? 11 : fam === "quiz" ? 18 : 26;
    }

    function paintPanel(ctx) {
      if (!el.panel || !ctx.drawPanel) return;
      try {
        ctx.drawPanel(el.panel, { pitch: pitch(lastFam), glow: 0.65, round: true });
      } catch (e) {
        /* the core logs scene errors; a missing frame just leaves the canvas */
      }
    }

    function confetti(color) {
      if (!el.confetti) return;
      if (!color) return put(el.confetti, "");
      const bits = [];
      const n = typeof TV !== "undefined" && TV.quality === "lite" ? 12 : 36;
      for (let i = 0; i < n; i++) {
        const c = i % 3 === 0 ? "#ffcc33" : i % 3 === 1 ? color : "#ffffff";
        bits.push(`<i style="left:${(i * 37) % 100}%;background:${c};animation-duration:${2.4 + ((i * 13) % 20) / 10}s;animation-delay:${-((i * 7) % 30) / 10}s"></i>`);
      }
      put(el.confetti, bits.join(""));
    }

    function header(ctx, st, fam) {
      const meta = ctx.meta || {};
      const m = modeInfo(ctx.app, st);
      const kick = [PET_IDS.has(ctx.app) ? "Pets" : "Games"];
      if (MODES[ctx.app] && Object.keys(MODES[ctx.app]).length > 1) kick.push(m.name);
      if (st.map && fam !== "board") kick.push(String(st.map).replace(/_/g, " ") + " map");
      put(el.kick, esc(kick.join(" · ")));
      put(el.title, esc(meta.name || ctx.app || ""));
      const chips = [];
      const fl = flowLabel(st);
      if (fl) chips.push(chip(fl.label, fl.tone));
      if (st.flow === "play" && fam !== "solo") {
        const humans = (st.seats || []).filter((s) => s.human && (!st.roster || st.roster[s.seat] || st.roster[String(s.seat)])).length;
        if (humans) chips.push(chip(`${humans} player${humans > 1 ? "s" : ""}`));
      }
      put(el.flow, chips.join(""));
    }

    function legend(ctx, st) {
      const rows = controlsFor(ctx.app, st);
      put(el.legend, `<div class="tv-label">Controls · keyboard or phone</div><div class="rows">${rows.map((r) => `<div class="row"><span class="tvg-keys">${r.keys.map((k) => `<span class="tvg-key">${esc(k)}</span>`).join("")}</span><span>${esc(r.label)}</span></div>`).join("")}</div>`);
    }

    function join(ctx, st) {
      if (!el.join) return;
      const lobby = ctx.lobby;
      if (!lobbyOpen(st, lobby)) {
        lastQr = null;
        put(el.join, "");
        return;
      }
      const free = Math.max(0, (lobby.max_players || 1) - 1 - (lobby.seats || []).length);
      const changed = put(el.join, `<div class="tvg-join tv-card"><canvas></canvas><div><div class="tv-label">Scan to join</div><b>${esc(lobby.code || "")}</b><span>${free} seat${free === 1 ? "" : "s"} free · same Wi-Fi</span></div></div>`);
      if ((changed || lastQr !== lobby.url) && ctx.qr) {
        lastQr = lobby.url;
        try {
          ctx.qr(lobby.url, el.join.querySelector("canvas"), { size: 170, quiet: 2 });
        } catch (e) {
          /* QR is a nicety; the code is printed too */
        }
      }
    }

    function overlay(ctx, st, seats) {
      const now = ctx.now ? ctx.now() : performance.now() / 1000;
      if (st.flow !== lastFlow) {
        lastFlow = st.flow;
        flowAt = now;
      }
      if (st.flow === "intro") {
        const c = countdown(now - flowAt);
        put(el.over, `<div class="tvg-count" style="--c:${c === "GO" ? "#50ff78" : "#ff4818"}">${c}</div>`);
        confetti(null);
        return;
      }
      const b = outcomeBanner(ctx.app, st, seats);
      if (b) {
        put(el.over, `<div class="tvg-banner" style="--c:${esc(b.color)}"><b>${esc(b.title)}</b>${b.sub ? `<span>${esc(b.sub)}</span>` : ""}</div>`);
        confetti(b.color);
        return;
      }
      put(el.over, "");
      confetti(null);
    }

    function updateGames(ctx, st, fam) {
      const seats = seatList(ctx.app, st, ctx.lobby);
      header(ctx, st, fam);
      overlay(ctx, st, seats);
      if (el.glow) {
        const lead = seats[0] ? seats[0].color : "#00c8ff";
        if (el.glow.__c !== lead) {
          el.glow.__c = lead; // a 1100 px gradient: repaint it only when the colour changes
          el.glow.style.setProperty("--tvg-glow", lead);
        }
      }
      let main = "";
      const open = lobbyOpen(st, ctx.lobby);
      if (fam === "pet") main = petHtml(ctx.app, st);
      else if (fam === "chess") main = chessHtml(ctx.app, st);
      else if (fam === "quiz") main = quizHtml(st);
      else if (st.flow === "teams") main = sidesHtml(ctx.app, st, seats);
      else if (st.flow === "home") main = `<div class="tvg-note">The host is picking the mode, players, map and colours on the panel.</div>${seats.some((s) => s.human && s.seat > 1) ? lobbyHtml(st, seats) : ""}`;
      else if (fam === "board") main = boardHtml(ctx.app, st, seats);
      else if (fam === "versus") main = versusHtml(ctx.app, st, seats);
      else if (fam === "coop") main = coopHtml(ctx.app, st, seats);
      else if (fam === "ffa") main = ffaHtml(ctx.app, st, seats);
      else {
        main = soloHtml(ctx.app, st, seats);
        if (st.flow === "attract") main += attractHtml(ctx.app, st, ctx.meta);
        if (open || seats.some((s) => s.seat > 1 && s.human)) main += lobbyHtml(st, seats);
      }
      if (fam === "quiz") {
        const v = triviaView(st);
        put(el.stats, [["Score", v.score], ["Answered", v.answered], ["Streak", v.streak]].map(([l, x]) => `<div class="tvg-stat"><div class="tv-label">${l}</div><b>${esc(num(x))}</b></div>`).join(""));
      } else if (el.stats) {
        const gs = globalStats(ctx.app, st);
        put(el.stats, gs.map((g) => `<div class="tvg-stat"${g.tone ? ` data-tone="${g.tone}"` : ""}><div class="tv-label">${esc(g.label)}</div><b>${g.hearts !== undefined ? (g.hearts > 0 ? hearts(g.hearts) : "0") : esc(g.value)}</b></div>`).join(""));
      }
      if (put(el.main, main)) paintAvatars(el.main, ctx);
      legend(ctx, st);
      join(ctx, st);
    }

    function updateRps(ctx, st) {
      const v = rpsView(st);
      header(ctx, st, "rps");
      const seats = seatList(ctx.app, st, ctx.lobby);
      const champ = v && v.phase === "champ" && v.champion && st.flow !== "outro";
      if (champ) {
        put(el.over, `<div class="tvg-banner" style="--c:${esc(v.champion.color)}"><b>${esc(v.champion.name)}</b><span>Champion</span></div>`);
        confetti(v.champion.color);
      } else overlay(ctx, st, seats);
      legend(ctx, st);
      join(ctx, st);
      if (!v) return;
      if (v.art) el.art = v.art;
      const art = el.art;
      const ph = v.phase;
      const reveal = !!v.result;
      const hands = el.hands.querySelectorAll(".tvg-hand");
      const ratio = (typeof TV !== "undefined" && TV.pixelRatio) || 1;
      [v.left, v.right].forEach((p, i) => {
        const h = hands[i];
        const won = reveal && v.result === (i ? "right" : "left");
        const lost = reveal && v.result !== "draw" && !won;
        h.className = "tvg-hand" + (won ? " win" : "") + (lost ? " lose" : "") + (ph === "pump" ? " tvg-pump" : "");
        h.style.setProperty("--c", p.color);
        put(h.querySelector(".nm"), esc(p.name) + (p.human ? "" : ' <span class="tvg-tag">CPU</span>'));
        put(h.querySelector(".tvg-pips"), Array.from({ length: v.firstTo }, (_, k) => `<i class="${k < p.wins ? "on" : ""}"></i>`).join(""));
        const move = reveal && p.pick ? p.pick : "rock";
        const key = [move, p.color, i, ratio].join("|");
        const cv = h.querySelector("canvas");
        if (cv.__k !== key) {
          cv.__k = key;
          drawHand(cv, art, move, p.color, i === 1, ratio);
        }
        let stHtml = "";
        if (reveal && p.pick) stHtml = `<span class="tvg-pickword">${esc(p.pick)}</span>`;
        else if (ph === "pick" || ph === "pump") stHtml = p.locked ? '<span class="tvg-lock">LOCKED IN</span>' : '<span class="tvg-wait">CHOOSING…</span>';
        put(h.querySelector(".st"), stHtml);
      });
      const mid = el.hands.querySelector(".tvg-mid");
      if (v.timer && v.timer.of) {
        const k = Math.max(0, Math.min(1, (v.timer.left || 0) / v.timer.of));
        const C = 2 * Math.PI * 74;
        const col = v.timer.left <= 3 ? "#ff3b5c" : "#ffcc33";
        put(mid, `<div class="tvg-ring"><svg viewBox="0 0 170 170"><circle cx="85" cy="85" r="74" fill="none" stroke="#25252d" stroke-width="12"/><circle cx="85" cy="85" r="74" fill="none" stroke="${col}" stroke-width="12" stroke-linecap="round" stroke-dasharray="${(C * k).toFixed(1)} ${C.toFixed(1)}" style="transition:stroke-dasharray .25s linear"/></svg><b>${esc(v.timer.left)}</b></div><div class="tv-label">Round ${esc(v.round || 1)}</div>`);
      } else {
        put(mid, `<div class="vs">VS</div><div class="tv-label">First to ${v.firstTo}${v.kind === "tour" ? ` · Match ${esc(v.match || 1)}` : ""}</div>`);
      }
      let msg = "";
      if (ph === "vs") msg = "Get ready";
      else if (ph === "bracket") msg = "Next match";
      else if (ph === "pick") msg = "Choose!";
      else if (ph === "pump") msg = "Rock · Paper · Scissors…";
      else if (reveal) msg = v.result === "draw" ? "Draw — again!" : (v.result === "left" ? v.left.name : v.right.name) + " takes the round";
      if (ph === "champ" && v.champion) msg = v.champion.name + " is the champion!";
      put(el.msg, `<span style="color:${reveal && v.result !== "draw" ? esc(v.result === "left" ? v.left.color : v.right.color) : "inherit"}">${esc(msg)}</span>`);
      // bracket / table at the side
      let side = "";
      if (v.bracket && v.bracket.format === "knockout") {
        side = `<div class="tv-label">Bracket</div><div class="tvg-bracket">${v.bracket.rounds.map((rnd, i) => `<div class="rnd"><div class="tv-label">${i === v.bracket.rounds.length - 1 && rnd.length === 1 ? "Final" : "Round " + (i + 1)}</div>${rnd.map((m) => {
          const nm = (p) => (p ? `<span class="${m.winner == null ? "" : m.winner === p.seat ? "w" : "l"}" style="color:${esc(p.color)}">${esc(p.name)}</span>` : "<span>—</span>");
          return `<div class="m">${nm(m.a)}${m.bye ? '<span class="tvg-tag">BYE</span>' : `<span style="color:#6f6d78">vs</span>${nm(m.b)}`}</div>`;
        }).join("")}</div>`).join("")}</div>`;
      } else if (v.bracket && v.bracket.format === "robin") {
        side = `<div class="tv-label">Table</div><div class="tvg-bracket"><table>${v.bracket.table.map((r, i) => `<tr><td>${i + 1}</td><td style="color:${esc(r.color)};font-weight:800">${esc(r.name)}</td><td>${r.wins} W</td><td>${r.diff > 0 ? "+" : ""}${r.diff}</td></tr>`).join("")}</table></div>`;
      } else {
        side = `<div class="tvg-note">${v.kind === "pvp" ? "Two players, first to " + v.firstTo + " rounds." : v.kind === "tour" ? "Tournament" : "Playing the CPU — it may give a tell away."}</div>`;
      }
      put(el.main, side);
    }

    return {
      id: "games",
      match: (app, meta) => GAME_IDS.has(app) || PET_IDS.has(app),
      mount(r, ctx) {
        ensureCss();
        root = r;
        lastFam = null;
        lastFlow = null;
        this.update(ctx);
      },
      update(ctx) {
        const st = ctx.status || {};
        const fam = family(ctx.app, st);
        const layout = fam === "rps" ? "rps" : fam === "quiz" ? "quiz" : "std";
        const cur = lastFam === "rps" ? "rps" : lastFam === "quiz" ? "quiz" : lastFam ? "std" : null;
        if (layout !== cur) build(fam);
        lastFam = fam;
        if (fam === "rps") updateRps(ctx, st);
        else updateGames(ctx, st, fam);
        if (ctx.panel) paintPanel(ctx);
      },
      frame(ctx) {
        paintPanel(ctx);
        // the countdown advances between state messages
        if ((ctx.status || {}).flow === "intro" && el.over) overlay(ctx, ctx.status, seatList(ctx.app, ctx.status, ctx.lobby));
      },
      unmount() {
        root = null;
        el = {};
      },
    };
  }

  if (typeof TV !== "undefined" && TV.registerScene) TV.registerScene(makeScene());
})();

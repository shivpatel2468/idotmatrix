// node --test tests/js/*.test.mjs — the TV game scenes' pure helpers (src/deskdot/tv/tv-games.js), fed with real
// statuses dumped from the Python game apps (tests/js/fixtures/game_statuses.json).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../../src/deskdot/tv/tv-games.js", import.meta.url), "utf8");
const registered = [];
const ctx = { JSON, Object, Math, Number, String, Array, Set, Map, parseInt, parseFloat, TV: { registerScene: (s) => registered.push(s) } };
ctx.globalThis = ctx;
vm.runInNewContext(src, ctx);
const G = ctx.TVGames;
const FX = JSON.parse(readFileSync(new URL("./fixtures/game_statuses.json", import.meta.url), "utf8"));
const plain = (x) => JSON.parse(JSON.stringify(x));

test("registers one games scene that matches every game and pet, not casino or other apps", () => {
  assert.equal(registered.length, 1);
  const s = registered[0];
  for (const app of Object.keys(FX)) assert.ok(s.match(app, FX[app].meta), app);
  for (const app of ["casino_roulette", "clock", "gamedeals", null]) assert.ok(!s.match(app, {}), String(app));
});

test("every fixture status yields a family, seats, flow and controls without throwing", () => {
  for (const [app, d] of Object.entries(FX)) {
    for (const [k, st] of Object.entries(d)) {
      if (k === "meta") continue;
      const fam = G.family(app, st);
      assert.ok(["solo", "coop", "ffa", "versus", "board", "rps", "quiz", "chess", "pet"].includes(fam), `${app}/${k}: ${fam}`);
      const seats = G.seatList(app, st, null);
      G.globalStats(app, st);
      G.outcomeBanner(app, st, seats);
      assert.ok(G.controlsFor(app, st).length > 0, `${app}/${k} controls`);
      for (const s of seats) assert.match(s.color, /^#[0-9a-f]{6}$/i, `${app}/${k} seat colour`);
    }
  }
});

test("families per mode", () => {
  assert.equal(G.family("arcade", FX.arcade.attract), "solo");
  assert.equal(G.family("arcade", FX.arcade.play_battle), "ffa");
  assert.equal(G.family("arcade", FX.arcade.play_teams), "versus");
  assert.equal(G.family("arcade", FX.arcade.play_coop), "coop");
  assert.equal(G.family("pong", FX.pong.play_classic), "versus");
  assert.equal(G.family("tictactoe", FX.tictactoe.play_duel), "board");
  assert.equal(G.family("rps", FX.rps.play_pvp), "rps");
  assert.equal(G.family("trivia", FX.trivia.attract), "quiz");
  assert.equal(G.family("pet", FX.pet.attract), "pet");
  assert.equal(G.modeInfo("digworld", FX.digworld.play_rush).name, "Ore rush"); // its play_mode, not its own "mode"
});

test("seat list: roster seats with names, colours, per-seat headline", () => {
  const seats = G.seatList("neonheat", FX.neonheat.play_rush, null);
  assert.deepEqual(plain(seats.map((s) => s.seat)), [1, 2, 3]);
  assert.equal(seats[0].name, "Player 1");
  assert.equal(seats[1].name, "MAYA");
  assert.equal(seats[1].color, "#ff7419");
  assert.equal(seats[0].headline.k, "cash");
  assert.equal(seats[0].headline.text, "$0");
  assert.equal(seats[0].lives, 3);
  // versus: team colours (tinted for a second teammate), like the panel's colour_of
  const vs = G.seatList("pong", FX.pong.play_doubles, null);
  const a = vs.filter((s) => s.team === 0).map((s) => s.color);
  assert.equal(a[0], "#00c8ff");
  assert.notEqual(a[1], "#00c8ff");
  // CPU seats are named as such
  assert.ok(vs.some((s) => !s.human && s.name.startsWith("CPU")));
});

test("leaders, places lower-is-better, and out seats", () => {
  const st = { flow: "play", mode: "race", roster: { 1: { team: null, human: true }, 2: { team: null, human: true } }, places: { 1: 2, 2: 1 } };
  assert.deepEqual(plain(G.leaders(G.seatList("streetsurge", st, null))), [2]);
  const level = { ...st, places: { 1: 1, 2: 1 } };
  assert.deepEqual(plain(G.leaders(G.seatList("streetsurge", level, null))), []);
  const cyc = { flow: "play", mode: "party", roster: { 1: { team: null, human: true }, 2: { team: null, human: false } }, wins: { 1: 2, 2: 0 }, alive: [1] };
  const seats = G.seatList("cycles", cyc, null);
  assert.equal(seats[1].alive, false);
  assert.equal(seats[0].headline.label, "Rounds");
});

test("team totals add up per-seat numbers", () => {
  const st = { flow: "play", mode: "versus", roster: { 1: { team: 0, human: true }, 2: { team: 1, human: true } }, lines: { 1: 4, 2: 7 } };
  const t = G.teamsOf(G.seatList("tetris", st, null));
  assert.equal(t[0].total, 4);
  assert.equal(t[1].total, 7);
  assert.equal(t[1].label, "Lines");
});

test("results banner", () => {
  const s = (k) => G.outcomeBanner(k[0], FX[k[0]][k[1]], G.seatList(k[0], FX[k[0]][k[1]], null));
  assert.equal(s(["tictactoe", "outro_duel"]).title, "MAYA wins");
  assert.equal(s(["pong", "outro_doubles"]).title, "Team B wins");
  assert.equal(s(["mines", "outro_coop"]).title, "CLEARED");
  assert.equal(s(["arcade", "play_battle"]), null);
  const solo = G.outcomeBanner("dino", { flow: "outro", score: 120, best: 120 }, []);
  assert.match(solo.sub, /New best/);
});

test("flow chip, intro countdown, time chip", () => {
  assert.equal(G.flowLabel({ flow: "attract", player: "ai" }).label, "Demo · AI playing");
  assert.equal(G.flowLabel({ flow: "teams" }).label, "Pick your side");
  assert.deepEqual([0, 0.59, 0.6, 1.3, 1.9].map(G.countdown), ["3", "3", "2", "1", "GO"]);
  const t = G.globalStats("arcade", FX.arcade.play_battle).find((x) => x.k === "time");
  assert.equal(t.value, "1:30");
  const pg = G.globalStats("penguin", FX.penguin.attract);
  assert.equal(pg.find((x) => x.k === "level").value, "1 / 16");
});

test("controls legend follows the flow", () => {
  assert.deepEqual(plain(G.controlsFor("tetris", { flow: "play" }).map((r) => r.label)), ["Rotate", "Soft drop", "Move", "Hard drop", "Rotate back"]);
  assert.equal(G.controlsFor("tetris", { flow: "teams" })[0].label, "Choose a side");
  assert.equal(G.controlsFor("tetris", { flow: "outro" })[0].label, "Rematch");
  assert.equal(G.controlsFor("arcade", { flow: "play" })[0].label, "Steer");
  assert.ok(G.controlsFor("unknown", {}).length >= 1);
});

test("scan to join only while a lobby has free seats", () => {
  const lobby = { code: "K7QX", url: "http://192.168.1.20:8765/p/K7QX", max_players: 4, seats: [{ seat: 2, name: "MAYA", color: "#ff7419" }] };
  assert.equal(G.lobbyOpen({ lobby: true }, lobby), true);
  assert.equal(G.lobbyOpen({ lobby: false }, { ...lobby, seats: [1, 2, 3].map((n) => ({ seat: n + 1 })) }), false);
  assert.equal(G.lobbyOpen({}, null), false);
  // lobby seats show up in attract (seat list from the lobby when there's no roster)
  const seats = G.seatList("arcade", FX.arcade.attract, lobby);
  assert.ok(seats.some((s) => s.seat === 2 && s.name === "MAYA"));
});

test("board duel view: tally and whose move", () => {
  const st = { ...FX.tictactoe.play_duel, wins: { x: 2, o: 1, draws: 3 }, turn: 2 };
  const v = G.boardView("tictactoe", st, G.seatList("tictactoe", st, null));
  assert.equal(v.players[0].symbol, "X");
  assert.equal(v.players[0].wins, 2);
  assert.equal(v.players[1].toMove, true);
  assert.equal(v.draws, 3);
  const f = G.boardView("fourup", { ...FX.fourup.play_duel, wins: { 1: 1, 2: 4, draws: 0 } }, []);
  assert.equal(f.players[1].wins, 4);
});

test("rps view: pick timer, reveal, bracket", () => {
  const v = G.rpsView(FX.rps.play_pvp);
  assert.equal(v.left.name, "P1");
  assert.equal(v.right.name, "MAYA");
  assert.equal(v.timer.of, 8);
  assert.equal(v.result, null);
  const rev = G.rpsView({ rps: { ...FX.rps.play_pvp.rps, phase: "reveal", picks: { 1: "rock", 2: "paper" }, winner: 2, locked: [1, 2] } });
  assert.equal(rev.result, "right");
  assert.equal(rev.left.pick, "rock");
  const tour = G.rpsView(FX.rps.play_tour);
  assert.equal(tour.bracket.format, "knockout");
  assert.equal(tour.bracket.rounds[0][0].bye, true);
  assert.ok(Array.isArray(G.rpsView(FX.rps.attract).art.rock));
  const robin = G.rpsView({ rps: { pair: [1, 2], players: { 1: { name: "A", color: "#00c8ff" } }, tour: { format: "robin", table: [{ seat: 1, wins: 2, played: 2, diff: 3, rounds: 4 }] } } });
  assert.equal(robin.bracket.table[0].name, "A");
});

test("trivia view and chess never expose the solution text", () => {
  const v = G.triviaView({ phase: "board", question: "2+2?", options: ["3", "4"], selected: 1, score: 5 });
  assert.equal(v.options[1].selected, true);
  assert.equal(v.options[0].letter, "A");
  assert.equal(G.triviaView({ phase: "question", options: ["a"], selected: 0 }).options[0].selected, false);
  const html = G.chessHtml("chess", { title: "Mate in 2", to_move: "black", solution: "Qxh7+ Kxh7 Rh3#", manual_ply: 1 });
  assert.ok(!/Qxh7|Kxh7|Rh3/.test(html));
  assert.match(html, /Black to move/);
  assert.match(html, /3-move solution/);
});

test("esc escapes names from phones", () => {
  assert.equal(G.esc('<b a="1">&\''), "&lt;b a=&quot;1&quot;&gt;&amp;&#39;");
  assert.equal(G.ordinal(1), "1st");
  assert.equal(G.ordinal(12), "12th");
  assert.equal(G.ordinal(23), "23rd");
});

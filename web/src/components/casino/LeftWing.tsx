import { Check, Coffee, Crown, Gem, RotateCcw, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../lib/api";
import { lobbySwitch } from "./lobby";
import { appMeta, toast, useStore } from "../../lib/store";
import type { JsonSchemaProp } from "../../lib/types";
import { Slider, Toggle } from "../controls";
import { NumberInput, Section, Tabs } from "./bits";
import { type Guide, type House, casinoApps, casinoOp, fmt, useCasino } from "./state";

// ------------------------------------------------------------------ house
const HOUSE_DEFAULT: House = { base_credits: 1000, min_bet: 1, max_bet: 500, bet_seconds: 20, result_seconds: 7, turn_seconds: 20, auto_next: true };

/** Plain-language hints for game rules (by field name). The schema's own description wins when it has one. */
const RULE_HINTS: Record<string, string> = {
  wheel: "European: one zero, every bet has a 2.70 % house edge. American adds 00: 5.26 % (the top line 7.89 %).",
  la_partage: "European wheel only. Even-money bets (red/black, odd/even, low/high) get half back on zero — their edge halves to 1.35 %.",
  seven_pays: "Lucky 7 at 4:1 gives the house 16.7 %; at 5:1 it is a perfectly fair bet (0 %).",
  decks: "More decks in the shoe slightly raise the house edge and make card counting pointless.",
  soft17: "S17: the dealer stands on soft 17 (better for players). H17: the dealer hits it (+0.2 % to the house).",
  dealer_hits_soft17: "On: the dealer hits soft 17 (+0.2 % to the house). Off: stands (better for players).",
  blackjack_pays: "3:2 is the classic payout. 6:5 adds about 1.4 % to the house edge.",
  bj_pays: "3:2 is the classic payout. 6:5 adds about 1.4 % to the house edge.",
  double: "Which first two cards may double down. Any two is the player-friendly rule.",
  double_after_split: "Lets a player double down on a hand made by splitting (good for players).",
  surrender: "Late surrender: give up half the bet after the dealer checks for blackjack.",
  max_splits: "How many times a hand may be split (3 splits = 4 hands).",
  split_aces_one_card: "Split aces get exactly one card each (standard).",
  dealer_peek: "The dealer checks for blackjack under an ace or ten, so players never lose doubles and splits to it.",
  commission: "Standard: Banker wins pay 0.95:1 (5 % commission). No-commission: Banker wins on 6 pay 1:2.",
  tie_pays: "Tie at 8:1 carries a 14.4 % edge; at 9:1 it drops to 4.8 %.",
  small_blind: "Forced bet left of the button.",
  big_blind: "Forced bet two left of the button; the minimum raise.",
  blind_increase: "Raise the blinds every few hands so the game finishes.",
  rake: "The house's cut of each pot (0 = a friendly game).",
  boot: "Everyone's ante into the pot before cards are dealt.",
  max_blind_rounds: "How long a player may keep playing blind before they must look at their cards.",
  pot_limit: "The pot is shown down when it reaches this size.",
  first_card: "Which side the first card is dealt to after the joker.",
  volatility: "Picks the reel strips: low pays small wins often, high pays big wins rarely. The exact RTP is shown under Odds.",
  bet_per_line: "Credits staked on each payline.",
  lines: "How many of the 5 paylines are played.",
  theme: "The machine's symbols and colours on the panel.",
};

type Preset = { id: string; name: string; blurb: string; icon: React.ReactNode; house: Partial<House>; rules: Record<string, unknown> };
/** Rules are suggestions by field name: each is applied only if the current game has that field and accepts the value. */
const PRESETS: Preset[] = [
  {
    id: "friendly", name: "Friendly night", icon: <Coffee size={16} />,
    blurb: "Small stakes, relaxed timers and the kindest rules on every table.",
    house: { base_credits: 1000, min_bet: 1, max_bet: 100, bet_seconds: 30, result_seconds: 8, turn_seconds: 30, auto_next: true },
    rules: {
      wheel: "european", la_partage: true, seven_pays: 5, decks: 2, soft17: "S17", dealer_hits_soft17: false, blackjack_pays: "3:2", bj_pays: "3:2",
      double_after_split: true, surrender: "late", tie_pays: 9, rake: 0, volatility: "low",
    },
  },
  {
    id: "vegas", name: "Vegas", icon: <Sparkles size={16} />,
    blurb: "Strip-style tables: American wheel, six-deck shoe, standard limits and timers.",
    house: { base_credits: 1000, min_bet: 5, max_bet: 500, bet_seconds: 20, result_seconds: 7, turn_seconds: 20, auto_next: true },
    rules: {
      wheel: "american", la_partage: false, seven_pays: 4, decks: 6, soft17: "H17", dealer_hits_soft17: true, blackjack_pays: "3:2", bj_pays: "3:2",
      double_after_split: true, surrender: "none", tie_pays: 8, rake: 0, volatility: "medium",
    },
  },
  {
    id: "high", name: "High rollers", icon: <Crown size={16} />,
    blurb: "Deep stacks, big limits and quick rounds. European wheel with La Partage.",
    house: { base_credits: 25000, min_bet: 100, max_bet: 25000, bet_seconds: 15, result_seconds: 6, turn_seconds: 15, auto_next: true },
    rules: {
      wheel: "european", la_partage: true, seven_pays: 5, decks: 8, soft17: "S17", dealer_hits_soft17: false, blackjack_pays: "3:2", bj_pays: "3:2",
      double_after_split: true, surrender: "late", tie_pays: 8, rake: 0, volatility: "high",
    },
  },
];

function ruleFields(app: string | null): [string, JsonSchemaProp][] {
  const props = appMeta(app)?.schema?.properties ?? {};
  return Object.entries(props).filter(([k, p]) => k !== "view" && k !== "table_theme" && p.group !== "Preview" && p.group !== "Look");
}

/** Does `p` accept `v`? (enum member, boolean, number in bounds) */
function accepts(p: JsonSchemaProp, v: unknown): boolean {
  if (p.enum) return p.enum.includes(v as string);
  if (p.type === "boolean") return typeof v === "boolean";
  if (p.type === "integer" || p.type === "number") {
    if (typeof v !== "number" || (p.type === "integer" && !Number.isInteger(v))) return false;
    return (p.minimum == null || v >= p.minimum) && (p.maximum == null || v <= p.maximum);
  }
  return typeof v === "string";
}

async function applyPreset(p: Preset, app: string | null) {
  await casinoOp("settings", p.house as Record<string, unknown>);
  const patch: Record<string, unknown> = {};
  for (const [k, prop] of ruleFields(app)) if (k in p.rules && accepts(prop, p.rules[k])) patch[k] = p.rules[k];
  if (app && Object.keys(patch).length) await api.patchSettings(app, patch);
  toast(`${p.name}: house set${Object.keys(patch).length ? ` + ${Object.keys(patch).length} rule${Object.keys(patch).length > 1 ? "s" : ""}` : ""}`, "ok");
}

function Presets({ app, house }: { app: string | null; house: House }) {
  const active = PRESETS.find((p) => Object.entries(p.house).every(([k, v]) => house[k as keyof House] === v))?.id;
  return (
    <div className="grid gap-2">
      {PRESETS.map((p) => (
        <button key={p.id} className="cz-preset" data-on={active === p.id || undefined} onClick={() => applyPreset(p, app).catch(() => undefined)}>
          <span className="cz-preset-ic">{p.icon}</span>
          <span className="min-w-0 flex-1 text-left">
            <b>{p.name}</b>
            <span>{p.blurb}</span>
            <em>{fmt(p.house.base_credits)} credits · {fmt(p.house.min_bet)}–{fmt(p.house.max_bet)} · {p.house.bet_seconds}s</em>
          </span>
          {active === p.id && <Check size={15} className="shrink-0 text-[var(--gold)]" />}
        </button>
      ))}
    </div>
  );
}

function HouseRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="cz-row">
      <div className="min-w-[130px] flex-1">
        <div className="cz-row-label">{label}</div>
        {hint && <div className="cz-row-hint">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

function HouseForm({ house }: { house: House }) {
  const set = (k: keyof House, v: number | boolean) => casinoOp("settings", { [k]: v }).catch(() => undefined);
  const [confirm, setConfirm] = useState(false);
  return (
    <>
      <HouseRow label="Starting credits" hint="Every new player's wallet before their first bet. Reset gives everyone this.">
        <NumberInput value={house.base_credits} min={0} max={1_000_000} onCommit={(v) => set("base_credits", v)} label="Starting credits" />
      </HouseRow>
      <div className="flex flex-wrap gap-1 pb-1 pl-0.5">
        {[500, 1000, 5000, 25000].map((v) => (
          <button key={v} className="cz-pill" data-on={house.base_credits === v || undefined} onClick={() => set("base_credits", v)}>{fmt(v)}</button>
        ))}
      </div>
      <HouseRow label="Minimum bet" hint="Per spot. Nobody can leave less on a spot.">
        <NumberInput value={house.min_bet} min={1} max={100_000} onCommit={(v) => set("min_bet", v)} label="Minimum bet" width={80} />
      </HouseRow>
      <HouseRow label="Maximum bet" hint="Per spot. A bigger chip tops the spot up to this.">
        <NumberInput value={house.max_bet} min={1} max={1_000_000} onCommit={(v) => set("max_bet", v)} label="Maximum bet" width={80} />
      </HouseRow>
      <HouseRow label="Betting timer" hint="Starts with the first chip of the round.">
        <Slider value={house.bet_seconds} min={5} max={180} unit="s" width={120} onCommit={(v) => set("bet_seconds", v)} />
      </HouseRow>
      <HouseRow label="Turn timer" hint="Card games: then the safe move is made (stand, check, fold).">
        <Slider value={house.turn_seconds} min={5} max={120} unit="s" width={120} onCommit={(v) => set("turn_seconds", v)} />
      </HouseRow>
      <HouseRow label="Result shown for" hint="Before the next round opens.">
        <Slider value={house.result_seconds} min={3} max={60} unit="s" width={120} onCommit={(v) => set("result_seconds", v)} />
      </HouseRow>
      <HouseRow label="Auto-next round" hint="Off: the table waits for you to press Start round.">
        <Toggle on={house.auto_next} onChange={(v) => set("auto_next", v)} label="Auto-next round" />
      </HouseRow>
      <div className="mt-2 rounded-[10px] border border-white/[0.06] bg-black/20 p-2.5">
        {confirm ? (
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-2">
            <span className="min-w-0 flex-1">Everyone back to <b className="text-[var(--gold)]">{fmt(house.base_credits)}</b>, stats and history cleared?</span>
            <button className="key !h-8 !border-[#ff3f78]/60 !text-[#ff8aa8]" onClick={() => { setConfirm(false); casinoOp("reset_session").then(() => toast("New session: wallets reset", "ok")).catch(() => undefined); }}>Reset</button>
            <button className="key !h-8" onClick={() => setConfirm(false)}>Keep</button>
          </div>
        ) : (
          <button className="key !h-8 w-full" onClick={() => setConfirm(true)} title="Open bets are refunded first">
            <RotateCcw size={13} /> New session…
          </button>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ table theme
/** The table's look (the `table_theme` setting): the panel chrome, every phone and this studio follow it. */
function ThemePicker({ app }: { app: string | null }) {
  const themes = useCasino((s) => s.themes);
  const live = useCasino((s) => s.status?.table_theme?.id) ?? "classic";
  const stored = useStore((s) => (app ? (s.state?.apps?.[app]?.table_theme as string | undefined) : undefined));
  const cur = stored ?? live;
  const [all, setAll] = useState(false);
  if (!themes.length) return <p className="cz-empty">The themes appear once the table is live.</p>;
  const pick = async (id: string) => {
    try {
      if (all) await Promise.all(casinoApps().map((g) => api.patchSettings(g.id, { table_theme: id })));
      else if (app) await api.patchSettings(app, { table_theme: id });
    } catch {
      /* toasted */
    }
  };
  return (
    <>
      <div className="cz-themes" role="radiogroup" aria-label="Table theme">
        {themes.map((t) => (
          <button key={t.id} role="radio" aria-checked={t.id === cur} className="cz-theme" data-on={t.id === cur || undefined} onClick={() => pick(t.id)}
            style={{ ["--sw-felt" as string]: t.css.felt, ["--sw-felt3" as string]: t.css.felt3, ["--sw-acc" as string]: t.css.accent }}>
            <i aria-hidden />
            <b>{t.name}</b>
          </button>
        ))}
      </div>
      <div className="cz-row !border-0">
        <div className="min-w-[130px] flex-1">
          <div className="cz-row-label">Every table</div>
          <div className="cz-row-hint">Apply the pick to all casino games, not just this one.</div>
        </div>
        <Toggle on={all} onChange={setAll} label="Apply the theme to every table" />
      </div>
    </>
  );
}

// ------------------------------------------------------------------ how to play + rulebook
/** `**bold**` → <b> (the rulebook's only markup; casino/rulebook.py). */
function Md({ text }: { text: string }) {
  return <>{text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))}</>;
}

function GuideView({ guide }: { guide: Guide | null }) {
  const [part, setPart] = useState<"how" | "rules">("how");
  if (!guide) return <p className="cz-empty">The rulebook appears once the table is live.</p>;
  return (
    <>
      <div className="seg mb-2.5 w-full">
        <button className="flex-1" data-active={part === "how"} onClick={() => setPart("how")}>How to play</button>
        <button className="flex-1" data-active={part === "rules"} onClick={() => setPart("rules")}>Rulebook</button>
      </div>
      <p className="cz-guide-tag"><Md text={guide.tagline} /></p>
      {part === "how" ? (
        <ol className="cz-steps">{guide.how.map((s, i) => <li key={i}><Md text={s} /></li>)}</ol>
      ) : (
        <div className="cz-rules">
          {guide.rules.map((r) => (
            <div key={r.h}>
              <h4>{r.h}</h4>
              <ul>{r.items.map((it, i) => <li key={i}><Md text={it} /></li>)}</ul>
            </div>
          ))}
        </div>
      )}
      <p className="cz-foot">The same text every phone shows (the ? button). Payouts and house edges for this table's live rules are under Odds.</p>
    </>
  );
}

// ------------------------------------------------------------------ rules
function RuleField({ name, p, value, live, onChange }: { name: string; p: JsonSchemaProp; value: unknown; live: unknown; onChange: (v: unknown) => void }) {
  const hint = p.description ?? RULE_HINTS[name];
  const pending = live !== undefined && JSON.stringify(live) !== JSON.stringify(value);
  const label = p.title ?? name.replace(/_/g, " ");
  let control: React.ReactNode;
  if (p.enum) {
    const lab = (o: string) => (p.enumLabels?.[o] ?? o).replace(/\s*\(.*\)$/, "");
    control = p.enum.length <= 4 ? (
      <div className="seg">
        {p.enum.map((o) => <button key={o} data-active={value === o} onClick={() => onChange(o)} title={p.enumLabels?.[o]}>{lab(o)}</button>)}
      </div>
    ) : (
      <select className="field !h-8 !w-auto max-w-[200px]" value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {p.enum.map((o) => <option key={o} value={o}>{p.enumLabels?.[o] ?? o}</option>)}
      </select>
    );
  } else if (p.type === "boolean") {
    control = <Toggle on={!!value} onChange={onChange} label={label} />;
  } else if ((p.type === "integer" || p.type === "number") && p.minimum != null && p.maximum != null) {
    const steps = p.maximum - p.minimum;
    control = p.type === "integer" && steps <= 5 ? (
      <div className="seg">
        {Array.from({ length: steps + 1 }, (_, i) => p.minimum! + i).map((n) => (
          <button key={n} data-active={value === n} onClick={() => onChange(n)} className="!px-2.5">{n}</button>
        ))}
      </div>
    ) : (
      <Slider value={Number(value ?? p.default ?? p.minimum)} min={p.minimum} max={p.maximum} step={p.type === "integer" ? 1 : 0.05} width={120} onCommit={onChange} />
    );
  } else if (p.type === "integer" || p.type === "number") {
    control = <NumberInput value={Number(value ?? 0)} onCommit={onChange} label={label} />;
  } else {
    control = <span className="font-mono text-[11px] text-ink-3">{String(value ?? "")}</span>;
  }
  return (
    <div className="cz-row">
      <div className="min-w-[130px] flex-1">
        <div className="cz-row-label">{label}{pending && <span className="cz-tag" title="Bets are on the table: the new rule starts with the next round">next round</span>}</div>
        {hint && <div className="cz-row-hint">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">{control}</div>
    </div>
  );
}

function RulesForm({ app }: { app: string | null }) {
  const stored = useStore((s) => (app ? s.state?.apps?.[app] : undefined));
  const live = useCasino((s) => s.status?.rules);
  useStore((s) => s.meta);
  const fields = ruleFields(app);
  const meta = appMeta(app);
  if (!fields.length) return <p className="cz-empty">{meta?.name ?? "This game"} has no table rules to set.</p>;
  return (
    <>
      {fields.map(([k, p]) => (
        <RuleField key={k} name={k} p={p} value={stored?.[k] ?? live?.[k] ?? p.default} live={live?.[k]}
          onChange={(v) => app && api.patchSettings(app, { [k]: v }).catch(() => undefined)} />
      ))}
      <p className="cz-foot">Rule changes made while chips are down start with the next round. Payouts follow the standard rulebook (docs/CASINO.md §7).</p>
    </>
  );
}

// ------------------------------------------------------------------ odds
const KIND: Record<string, string> = {
  straight: "Straight up (one number)", split: "Split (two numbers)", street: "Street (three numbers)", trio: "Trio (with zero)",
  corner: "Corner (four numbers)", sixline: "Six line", six_line: "Six line", line: "Six line", first_four: "First four (0-1-2-3)",
  firstfour: "First four (0-1-2-3)", ff: "First four (0-1-2-3)", top_line: "Top line (0-00-1-2-3)", topline: "Top line (0-00-1-2-3)",
  dozen: "Dozen", column: "Column", red: "Red", black: "Black", odd: "Odd", even: "Even", low: "Low (1–18)", high: "High (19–36)",
  down: "Under 7", seven: "Lucky 7", up: "Over 7", player: "Player", banker: "Banker", tie: "Tie",
  player_pair: "Player pair", banker_pair: "Banker pair", andar: "Andar", bahar: "Bahar",
};
const kindName = (k: string, sample?: string) => KIND[k] ?? (sample && sample.length < 24 ? `${k.replace(/_/g, " ")} (${sample})` : k.replace(/_/g, " "));

function Odds() {
  const edges = useCasino((s) => s.status?.edges);
  const spots = useCasino((s) => s.spots);
  const rtp = useCasino((s) => s.status?.rtp);
  const rows = useMemo(() => {
    const by: Record<string, { pays: Set<string>; sample: string; n: number }> = {};
    for (const s of spots) {
      const e = (by[s.kind] ??= { pays: new Set(), sample: s.label, n: 0 });
      e.pays.add(s.pays);
      e.n++;
    }
    return Object.entries(edges ?? {})
      .map(([k, e]) => ({ k, e, pays: [...(by[k]?.pays ?? [])].join(" / "), sample: by[k]?.n === 1 ? by[k]?.sample : undefined }))
      .sort((a, b) => a.e - b.e);
  }, [edges, spots]);
  const max = Math.max(0.06, ...rows.map((r) => r.e));
  const rtpPct = typeof rtp === "number" ? (rtp <= 1.5 ? rtp * 100 : rtp) : null;
  return (
    <>
      {rtpPct != null && (
        <div className="cz-rtp">
          <span className="engrave !text-[var(--gold)]/80">Return to player</span>
          <b>{rtpPct.toFixed(2)} %</b>
          <span>Computed from this machine's reel strips and pay table.</span>
        </div>
      )}
      {rows.length ? (
        <div className="cz-odds" role="table" aria-label="House edge per bet">
          <div role="row" className="cz-odds-head"><span>Bet</span><span>Pays</span><span>House edge</span></div>
          {rows.map((r) => (
            <div role="row" key={r.k} className="cz-odds-row">
              <span className="truncate" title={r.k}>{kindName(r.k, r.sample)}</span>
              <span className="font-mono">{r.pays || "—"}</span>
              <span className="cz-edge">
                <i style={{ width: `${Math.max(2, (Math.max(0, r.e) / max) * 100)}%`, background: r.e <= 0.0001 ? "#3ddc97" : r.e < 0.02 ? "#7fd67a" : r.e < 0.06 ? "#ffcc33" : "#ff3f78" }} />
                <b>{r.e <= 0.0001 ? "fair" : `${(r.e * 100).toFixed(2)} %`}</b>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="cz-empty">The odds appear once the table is live.</p>
      )}
      <p className="cz-foot">Each edge is computed exactly from every outcome's probability and the payout — the worst bet in each family is shown. The house never adapts to bets or balances.</p>
    </>
  );
}

// ------------------------------------------------------------------ tables (game picker)
function GamePicker({ app }: { app: string | null }) {
  useStore((s) => s.meta);
  const lobby = useStore((s) => s.lobby);
  const games = casinoApps();
  const pick = async (id: string) => {
    if (id === app) return;
    try {
      if (lobby && appMeta(lobby.app)?.category === "casino") await lobbySwitch(id);
      else await api.activate(id);
    } catch {
      /* toasted */
    }
  };
  return (
    <>
      <div className="cz-games">
        {games.map((g) => (
          <button key={g.id} className="cz-game" data-on={g.id === app || undefined} onClick={() => pick(g.id)} title={g.description}>
            <span className="led-preview relative block aspect-square w-full overflow-hidden rounded-[8px] bg-black">
              <img src={`/api/apps/${g.id}/preview.gif`} alt="" loading="lazy" draggable={false} className="h-full w-full [image-rendering:pixelated]" />
              <span className="led-mask pointer-events-none absolute inset-0" />
            </span>
            <b>{g.name}</b>
            {g.id === app ? <em>On the table</em> : <span>{g.description}</span>}
          </button>
        ))}
      </div>
      <p className="cz-foot"><Gem size={11} className="mr-1 inline text-[var(--gold)]" />Switching tables keeps every wallet{lobby ? " and every phone in its seat" : ""}. Open bets are refunded; a spinning round is paid first.</p>
    </>
  );
}

// ------------------------------------------------------------------ the wing
export function LeftWing() {
  const app = useCasino((s) => s.app);
  const tab = useCasino((s) => s.leftTab);
  const set = useCasino((s) => s.set);
  const house = useCasino((s) => s.status?.house) ?? HOUSE_DEFAULT;
  const guide = useCasino((s) => s.guide);
  const name = appMeta(app)?.name ?? "this game";
  return (
    <div className="cz-wing-body">
      <Tabs label="Casino settings" value={tab} onChange={(t) => set({ leftTab: t })}
        options={[["tables", "Tables"], ["house", "House"], ["rules", "Rules"], ["odds", "Odds"], ["guide", "Guide"]]} />
      <div className="cz-scroll">
        {tab === "tables" && <Section title="Casino games" hint="Pick the table on the panel."><GamePicker app={app} /></Section>}
        {tab === "house" && (
          <>
            <Section title="Presets" hint="Set the house and the table rules in one tap."><Presets app={app} house={house} /></Section>
            <Section title="House" hint="Shared by every casino game."><HouseForm house={house} /></Section>
            <Section title="Table theme" hint="The felt and accent on the panel, every phone and this studio."><ThemePicker app={app} /></Section>
          </>
        )}
        {tab === "guide" && <Section title={guide?.title ?? name} hint="How to play and the rulebook, as the phones show it."><GuideView key={app ?? ""} guide={guide} /></Section>}
        {tab === "rules" && <Section title={`${name} rules`} hint="Standard rulebook options for this table."><RulesForm app={app} /></Section>}
        {tab === "odds" && <Section title="House edge" hint={`What each ${name} bet costs on average.`}><Odds /></Section>}
      </div>
    </div>
  );
}

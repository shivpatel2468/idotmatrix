# Legal review — first research pass (2026-10-05)

> **Not legal advice.** This is a research brief to take to a lawyer (ideally one who does Indian technology / IP /
> gaming law). It lists what applies to DeskDot, how risky each point looks, and what to change. Sources at the end.

## Summary — the five things that matter most

| # | Risk | How serious | What to do |
| --- | --- | --- | --- |
| 1 | **The "iDotMatrix" name and the idotmatrix.com domain** belong to someone else's brand (the panel maker, Shenzhen Heaton Technology) | **High** — the one that can actually take the site away (trademark / passing off, a domain dispute) | Brand everything as **DeskDot**, say "unofficial, works with iDotMatrix panels", consider a DeskDot domain, ask a lawyer to search the trademark registers |
| 2 | **Casino games** if credits ever get real-world value | **High if money is involved; low as built** (play money only) | Never sell credits, never let them be cashed out or traded, no prizes; 18+ notice; keep it a *social game* |
| 3 | **Famous game and brand names** in the app list (Tetris, Pong, Space Invaders, Pokédex, Claude Mascot…) | **Medium** — trademark owners (The Tetris Company especially) enforce names *and* look | Rename to generic titles, avoid their trade dress, use the Pokémon/Anthropic names only with permission |
| 4 | **Privacy** once strangers use the public site (names, IP addresses in the WebRTC handshake, children) | **Medium** | A privacy notice, keep data minimal (it mostly is), 18+ for the casino, India DPDP Act basics |
| 5 | **Ownership / licence of the code** (MIT, AI-written code) | **Low–medium** — decides what you can control later | Decide now whether MIT is what you want before a commercial launch; keep your own creative input documented |

## 1. Casino games — can they legally launch?

**As built, DeskDot's casino is a "social casino": credits are free play money, no purchase, no cash-out, no prizes.**
That design is what keeps it legal; the moment credits gain value, it becomes gambling in most places.

**India — Promotion and Regulation of Online Gaming Act, 2025** (passed 21 Aug 2025, in force **1 May 2026**, with
the Online Gaming Rules 2026):

- It **bans "online money games"**: games where a user *pays money or other stakes expecting monetary or other
  enrichment*, whether skill or chance. Offering or advertising one: up to 3 years and/or ₹1 crore fine.
- It **promotes e-sports and "online social games"** (no stakes). DeskDot's casino fits here *only while* credits can't
  be bought, won as anything of value, traded or redeemed.
- **Ask the lawyer:** whether the 2026 Rules require social games to **register** with the new Online Gaming Authority,
  and whether casino-*themed* social games get any extra conditions (age, warnings).
- Older state laws (Public Gambling Act 1867 and state gaming acts) target wagering money or money's worth — play
  money with no value is outside them, but a few states read "gaming" broadly: another point for the lawyer.

**Elsewhere:** in the USA, social casinos *that sell virtual chips* have been held to be illegal gambling (the
Washington state Big Fish Casino case, *Kater v. Churchill Downs*, 9th Cir. 2018) — the risk is the purchase, which
DeskDot doesn't have. The EU / UK treat free play money with no prizes as not gambling, but regulators push for age
limits and warnings.

**App stores** (relevant for the Android app and any iOS app):

- **Google Play**: simulated gambling ("social casino") apps must say they're for adults, must not target minors, must
  state there's no real-money gambling and no prizes; the content rating marks *simulated gambling*.
- **Apple**: simulated gambling apps are rated **17+/18+** (guideline 5.3 for real money; the age-rating questionnaire
  for simulated).

**Changes to make in DeskDot (cheap, do them anyway):**

1. A clear line on every casino screen and the phone page: *"Play money only — credits have no value and can't be
   bought or cashed out. 18+."* (the phone page already says "play money only").
2. An **18+ confirmation** the first time someone opens the casino (studio and phones).
3. Never add: credit purchases, ads for real betting sites, prizes for leaderboards, credit transfers between players.
4. Housie / Tambola with money is gambling in India; with play money it's a party game — same rules apply.

## 2. The "iDotMatrix" name — the biggest risk

- **iDotMatrix** is the brand of the panels and the official app by **Shenzhen Heaton Technology Co., Ltd.**
  (idotmatrix.net, the Play Store app `com.tech.idotmatrix`).
- DeskDot uses **idotmatrix.com** as its website and an **"idotmatrix" neon logo** as the header brand. To a buyer
  of the panel this looks like the official product → **likely confusion**, which is exactly what trademark law and
  passing-off protect against. The brand owner could also file a **UDRP domain complaint** (the domain contains their
  mark, used for a product in the same field) — they'd have a strong case.
- **Fair "nominative" use is fine**: you may say *"DeskDot — an unofficial studio that works with iDotMatrix panels"*.
  You may not present your product *as* iDotMatrix.

**Recommended:** make **DeskDot** the visible brand (logo, titles, site header), add *"Unofficial — not affiliated
with or endorsed by iDotMatrix / Shenzhen Heaton Technology"* to the site footer, README and studio About, and plan a
move to a DeskDot domain (keep idotmatrix.com redirecting only if the lawyer says that's safe). The neon intro logo
can stay as art only if it reads "DeskDot" or is clearly not their logo.

**Reverse-engineered Bluetooth protocol:** writing your own software that talks to a device you own is generally
allowed for **interoperability** (USA DMCA §1201(f); EU Software Directive art. 6; India Copyright Act s.52(1)(ab)).
Don't redistribute their app, firmware or assets, and don't bypass any security — DeskDot doesn't.

## 3. Copyright — the app itself

- **You own the copyright** in DeskDot's code and art automatically (no registration needed; registering in India or
  the USA helps enforcement).
- The GitHub repo is **MIT-licensed**: anyone may copy, change and even sell it, as long as they keep the notice.
  That's great for an open project; if you want to **sell it or stop clones**, change the licence *before* that
  (versions already published stay MIT) — e.g. a dual licence, or source-available terms. Your **trademark**
  ("DeskDot" name/logo) can be protected even if the code stays MIT — register it in India (Class 9 software,
  Class 41 games).
- **AI-written code:** in the USA the Copyright Office protects only human-authored parts (AI output alone isn't
  copyrightable); India hasn't settled it. Your creative direction, selection and edits count as human authorship —
  keep the design history (issues, this repo's docs) as evidence. In practice, rely on the trademark + licence.
- **Third-party parts:** keep a licence inventory (`uv pip licenses` / `npx license-checker`): Pyodide (MPL-2.0),
  three.js (MIT), FastAPI/Starlette (BSD/MIT) etc. are fine with attribution; avoid GPL code in the shipped app (we
  already declined to copy GPL Vorssaint code).

## 4. Game names, characters and inspirations

Game **mechanics** aren't protected; **names, logos, characters, art, sounds and distinctive look ("trade dress")**
are.

| In DeskDot | Concern | Suggestion |
| --- | --- | --- |
| **Tetris** (app id `tetris`) | The Tetris Company enforces the name **and** the look (*Tetris Holding v. Xio*, 2012) | Rename ("Block Stack"), vary the look (the 7 shapes are fine, the Tetris trade dress isn't) |
| **Pong**, **Space Invaders** / "Invaders", **Asteroids** | Atari / Taito trademarks | Generic names ("Paddle Duel", "Alien Wave", "Rock Field") |
| **Pokédex** app (Pokémon names/sprites from PokéAPI) | The Pokémon Company — aggressive enforcement | Remove from a public launch or make it generic ("Creature Card") without their names/art |
| **Claude Mascot** | Anthropic's name/character | Fine for personal use; for a public product ask permission or rename |
| Coin Gate intro, Penguin Escape (WildTangent-inspired), fly "hornet" skin | Inspired, original art/names — OK as long as nothing is copied | Keep them original; don't use WildTangent / Green Hornet names |
| Chess puzzles, trivia, quotes, headlines, stocks, sports | Third-party **API terms** (some forbid commercial use or scraping, e.g. Yahoo Finance) | Check each provider's ToS before a commercial launch; credit sources |

## 5. A public playground — the other risks

- **Privacy (India DPDP Act 2023 + Rules; GDPR for EU users):** DeskDot keeps almost everything in the user's own
  browser (IndexedDB/localStorage). What leaves it: player names/colours shown to the room, IP addresses inside the
  WebRTC handshake (stored ≤ 60 s in Netlify Blobs), Netlify's own access logs, the relay (TURN) provider. → Publish a
  short **privacy notice** (what, why, how long, who: Netlify, the TURN provider, the data APIs), no analytics without
  consent, keep the short retention.
- **Children:** the DPDP Act needs verifiable parental consent for under-18s' data; with an **18+ casino** and no
  accounts this stays simple — don't add accounts or profiles without revisiting it.
- **Player names on screens:** strangers can type names shown to others → keep the name filter, the host's kick, and
  add a basic profanity filter for the public site.
- **Terms of use:** a short page: play money only, 18+ for the casino, no warranty (the MIT licence already disclaims
  it for the code), no liability for the hardware, acceptable use (no abuse of rooms), governing law India.
- **Abuse of the site's functions:** the CORS proxy is an allowlist (good); the signalling and TURN credentials are
  only handed to live rooms (good) — add rate limits before a big public launch; watch Netlify credits.
- **Selling it later:** GST registration, consumer-protection rules (refunds, honest claims), product-safety claims
  about the hardware — only when money changes hands.

## 6. Checklist before a public launch

- [ ] Lawyer: trademark search for "iDotMatrix" and "DeskDot" (India, USA, EU, China); advice on the idotmatrix.com
      domain; whether social games must register under the 2026 Online Gaming Rules.
- [ ] Rebrand the visible name/logo to **DeskDot**; add the "unofficial, not affiliated" line everywhere.
- [ ] Casino: "play money, no value, 18+" banner + first-run 18+ confirm (studio + phones).
- [ ] Rename the trademarked game titles; review the Pokédex and Claude Mascot apps.
- [ ] Privacy notice + terms of use pages on the site (+ link from the studio and the phone join page).
- [ ] Licence decision (stay MIT, or change before commercial use) and a third-party licence inventory file.
- [ ] Data-API terms check for commercial use.
- [ ] Rate limits on `/app/signal` and `/app/proxy`.

## Sources

- Promotion and Regulation of Online Gaming Act, 2025 —
  [Wikipedia](https://en.wikipedia.org/wiki/Promotion_and_Regulation_of_Online_Gaming_Act,_2025),
  [PRS bill text](https://prsindia.org/files/bills_acts/bills_parliament/2025/Bill_Text-Online_Gaming_Bill_2025.pdf),
  [SCC Online: enforcement notified](https://www.scconline.com/blog/post/2026/04/23/meity-notified-enforcement-of-promotion-regulation-online-gaming-act-2025/),
  [PIB: Online Gaming Rules 2026](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2254606&reg=3&lang=1),
  [Trilegal analysis](https://trilegal.com/knowledge_repository/trilegal-update-the-promotion-and-regulation-of-online-gaming-act-2025-redrawing-indias-online-gaming-landscape/)
- iDotMatrix brand — [idotmatrix.net](https://idotmatrix.net/),
  [Google Play: iDotMatrix app](https://play.google.com/store/apps/details?id=com.tech.idotmatrix&hl=en_AU)
- App stores — [Google Play: real-money gambling, games and contests](https://support.google.com/googleplay/android-developer/answer/9877032?hl=en),
  [Apple age ratings](https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions),
  [Bloomberg on social casinos (2026)](https://www.bloomberg.com/features/2026-social-casino-apps-addiction/)

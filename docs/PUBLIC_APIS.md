# Public APIs — what DeskDot uses and why

Survey of [public-apis/public-apis](https://github.com/public-apis/public-apis) done on 2026-09-24:
1,890 entries across 52 categories, of which **836 are keyless and HTTPS**. DeskDot only adopts APIs that are:

1. **Keyless** (or have a working anonymous tier). A panel app that needs a sign-up is an app nobody turns on.
2. **Alive**. Every adopted endpoint was probed live; many list entries (especially `*.herokuapp.com`) are dead.
3. **Glanceable at 32×32**. Numbers, countdowns, short text, tiny maps and pixel art work; long documents and
   detailed photos don't.
4. **Cheap to poll** within the provider's rate limits (limits are noted below and enforced in the provider).

Location-aware providers use `Hub.location()` (settings lat/lon → geocoded city → IP), never their own lookup.

## Adopted

| Group | App | API (auth: none) | Notes / limits |
| --- | --- | --- | --- |
| Planet | Earthquakes `quakes` | USGS GeoJSON summary feeds | world map + "near me" alerts |
| Planet | Rain Radar `rainradar` | RainViewer weather maps + Open-Meteo Elevation (basemap) | max zoom 7; only the "Universal Blue" colour scheme is served, so tiles are decoded back to dBZ and repainted; elevation API counts each coordinate as a call (sample 16×16, cache) |
| Planet | Air Quality `airquality` | Open-Meteo Air Quality | AQI, PM, O₃, NO₂, UV, pollen (EU only) |
| Planet | Holidays `holidays` | Nager.Date → Google public-holiday ICS → caldays.com | Nager returns **204 for India**; Google calendar ids need legacy names for many countries (`en.indian`, not `en.in`) |
| Space | Space `space` | Launch Library 2, wheretheiss.at, corquaid people-in-space JSON (Open Notify as fallback), Spaceflight News | LL2 = 15 req/h per IP; **Open Notify's astronaut list is years stale** |
| Space | Sun & Moon `sky` | sunrise-sunset.org, Open-Meteo (UTC offset, fallback) | sun and moon also computed locally (Meeus) |
| Daily | Daily Dose `daily` | ZenQuotes, icanhazdadjoke, Useless Facts, Advice Slip, Cat Facts, JokeAPI (safe mode), chucknorris.io, kanye.rest, Wikipedia "On this day" | ZenQuotes ≈ 5 req/30 s |
| Daily | Trivia `trivia` | Open Trivia DB | 1 req / 5 s, session tokens |
| Daily | Headlines `headlines` | Hacker News (Firebase), Spaceflight News, dev.to, Lobsters | Reddit JSON returns 403 |
| Money | Currency `currency` | Frankfurter (`api.frankfurter.dev/v1` — `.app` now redirects), fawazahmed0 currency-api | ECB lacks AED, BTC, … and has no weekend rates → fallback |
| Visuals | Photo Frame `photoframe` | The Met, Cleveland Museum of Art (CC0), Lorem Picsum, dog.ceo, cataas, RandomFox, RandomDuck | **ARTIC images are behind a Cloudflare browser check (403)** — not used; RandomFox is flaky |
| Visuals | Pokédex `pokedex` | PokéAPI | sprites fetched at runtime, never bundled |
| Visuals | Pixel Avatar `avatar` | mc-heads / Crafatar, GitHub identicons, DiceBear pixel-art (CC0) | 8×8 faces ×4 = exactly 32×32 |
| Gaming | Chess Puzzle `chess` | chess.com public API | daily + random puzzle |
| Gaming | Game Deals `gamedeals` | GamerPower, CheapShark | free-game alerts |

Already in use before this survey: Open-Meteo (weather), Binance (crypto), Yahoo Finance (stocks), ESPN (sports),
adsb.lol / airplanes.live / OpenSky / adsbdb (flights), LRCLIB + iTunes Search (music), GitHub (contribution graph).

## Considered and rejected

- **Needs a key or account**: NASA APOD (DEMO_KEY is 30 req/h, shared), OpenWeatherMap, NewsAPI, Spotify Web API, Steam.
- **Not glanceable at 32×32**: xkcd, arXiv/OpenAlex/Semantic Scholar, Bible/Quran/Gutenberg texts, recipe
  databases, Wikipedia articles, meme generators, most "Video" quote APIs.
- **Region-only or niche**: UK Carbon Intensity, Danish Energi, Swiss/Belgian/Berlin transit, Czech/Polish/Russian
  central banks, US-only health and government data. Worth adding as plugins for people in those places.
- **Dead or unreliable when probed**: many `herokuapp.com` services (Excuser, Ocean Facts, Wizard World, …).
- **Duplicates of what we have**: other crypto price APIs (Binance already), OpenF1 / Ergast (ESPN covers F1),
  balldontlie / NHL stats (ESPN), OpenSky (already a flights fallback).
- **Covid trackers**: obsolete.

## Good candidates for later

City Bikes (nearest bike-share dock), Radio Browser (panel as a station display if the engine ever plays audio),
Minecraft Server Status, TETR.IO / Chess.com player stats, Mempool.space (BTC fees), TVMaze schedule
("tonight on TV"), REST Countries (flag of the day), Open Food Facts (barcode → nutrition card).

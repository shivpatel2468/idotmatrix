# Data sources

Every live app gets its data from free, public sources. **None needs a key to get started.** The few that use a token
or a local service only do so for your *own* accounts and devices.

The complete survey (1,890 public APIs reviewed, what was adopted, rate limits, and what was rejected and why) is in
[docs/PUBLIC_APIS.md](docs/PUBLIC_APIS.md).

| Area | Source | Auth | Used by |
| --- | --- | --- | --- |
| Weather, forecast, marine, air quality, elevation, geocoding | [Open-Meteo](https://open-meteo.com/) | none | Weather, What to Wear, Air Quality, Tides & Surf, Rain Radar basemap |
| Rain radar | [RainViewer](https://www.rainviewer.com/api.html) | none | Rain Radar |
| Aircraft | [adsb.lol](https://adsb.lol/), [OpenSky](https://opensky-network.org/) | none | Flight Radar |
| Earthquakes | [USGS](https://earthquake.usgs.gov/earthquakes/feed/) | none | Earthquakes |
| Launches, ISS, people in space, space news | Launch Library 2, wheretheiss.at, Spaceflight News | none | Space |
| Sunrise / sunset | sunrise-sunset.org (+ local astronomy) | none | Sun & Moon, Day & Night, Planets Tonight |
| Holidays | Nager.Date, Google public-holiday calendars, caldays | none | Holidays |
| Crypto | Binance public market data | none | Crypto Ticker |
| Stocks | Yahoo Finance chart API, Stooq | none | Stocks |
| Currency | [Frankfurter](https://frankfurter.dev/) (ECB), fawazahmed0 currency-api | none | Currency |
| Sports | ESPN public scoreboards | none | Live Scores |
| Headlines | Hacker News, Spaceflight News, dev.to, Lobsters | none | Headlines |
| Daily dose, trivia | ZenQuotes, icanhazdadjoke, Useless Facts, Advice Slip, Open Trivia DB… | none | Daily, Trivia |
| Lyrics | [LRCLIB](https://lrclib.net/) (+ `syncedlyrics` fallback) | none | Now Playing |
| Art & animals | The Met, Cleveland Museum of Art (CC0), Lorem Picsum, dog.ceo, cataas… | none | Photo Frame |
| Sprites & avatars | PokéAPI, mc-heads, GitHub identicons, DiceBear (CC0) | none | Pokédex, Pixel Avatar |
| Chess, game deals | chess.com public API, GamerPower, CheapShark | none | Chess Puzzle, Game Deals |
| Location (fallback) | ip-api.com | none | only if you haven't set a city |
| GitHub | GitHub REST API | optional token | GitHub Graph, CI radiator |
| Your services | Home Assistant, OBS, AnkiConnect, OctoPrint / Moonraker, Jellyfin / Plex, ntfy | yours | the matching apps |

**Fair use:** every provider polls within its documented limits; those limits are enforced in `src/dotdeck/providers/`.
Images and sprites are fetched at runtime and never bundled in this repository.

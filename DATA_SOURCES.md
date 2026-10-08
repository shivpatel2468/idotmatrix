# Data sources

Every live app gets its data from free, public sources. **None needs a key to get started.** The few that use a token
or a local service only do so for your *own* accounts and devices.

The complete survey (1,890 public APIs reviewed, what was adopted, rate limits, and what was rejected and why) is in
[docs/PUBLIC_APIS.md](docs/PUBLIC_APIS.md).

| Area | Source | Auth | Used by |
| --- | --- | --- | --- |
| Weather, forecast, marine, air quality, elevation, geocoding | [Open-Meteo](https://open-meteo.com/) | none | Weather, What to Wear, Air Quality, Tides & Surf, Rain Radar basemap |
| Rain radar | [RainViewer](https://www.rainviewer.com/api.html) | none | Rain Radar |
| Aircraft | [adsb.lol](https://adsb.lol/), [adsb.fi](https://adsb.fi/), [OpenSky](https://opensky-network.org/) | none | Flight Radar |
| Earthquakes | [USGS](https://earthquake.usgs.gov/earthquakes/feed/) | none | Earthquakes |
| Launches, ISS, people in space, space news | Launch Library 2, wheretheiss.at, Spaceflight News | none | Space |
| Sunrise / sunset | sunrise-sunset.org (+ local astronomy) | none | Sun & Moon, Day & Night, Planets Tonight |
| Holidays | Nager.Date, Google public-holiday calendars, caldays | none | Holidays |
| Crypto | Binance public market data (+ `data-api.binance.vision` mirror where Binance is geo-blocked) | none | Crypto Ticker |
| Stocks | Yahoo Finance chart API, Nasdaq quote API (fallback) | none | Stocks |
| Currency | [Frankfurter](https://frankfurter.dev/) (ECB), fawazahmed0 currency-api | none | Currency |
| Sports | ESPN public scoreboards | none | Live Scores |
| Headlines | Hacker News, Spaceflight News, dev.to, Lobsters | none | Headlines |
| Daily dose, trivia | ZenQuotes, icanhazdadjoke, Useless Facts, Advice Slip, Open Trivia DB… | none | Daily, Trivia |
| Lyrics | [LRCLIB](https://lrclib.net/) (+ `syncedlyrics` fallback) | none | Now Playing |
| Art & animals | The Met, Cleveland Museum of Art (CC0), Lorem Picsum, dog.ceo, cataas… | none | Photo Frame |
| Sprites & avatars | PokéAPI, mc-heads, GitHub identicons, DiceBear (CC0) | none | Pokédex, Pixel Avatar |
| Chess, game deals | chess.com public API, GamerPower, CheapShark | none | Chess Puzzle, Game Deals |
| Space weather | [NOAA SWPC](https://www.swpc.noaa.gov/) Kp index, Kp forecast, OVATION aurora nowcast | none | Aurora Watch |
| Bitcoin network | [mempool.space](https://mempool.space/docs/api/rest) | none | Bitcoin Network |
| Crypto market | [CoinGecko](https://www.coingecko.com/en/api) public API, [alternative.me](https://alternative.me/crypto/fear-and-greed-index/) Fear & Greed | none | Crypto Market |
| Grand Prix calendar | [Jolpica](https://github.com/jolpica/jolpica-f1) (Ergast-compatible) | none | Race Countdown |
| Long weekends | Nager.Date `LongWeekend` | none | Long Weekend |
| Bike share | [CityBikes](https://api.citybik.es/v2/) | none | Bike Share |
| Natural events | [NASA EONET](https://eonet.gsfc.nasa.gov/) | none | Earth Events |
| Flags | [flagcdn.com](https://flagcdn.com/) (Flagpedia) | none | World Flags |
| Hourly rain & wind | Open-Meteo | none | Rain Chance, Wind Compass |
| Most-read articles, picture of the day | [Wikimedia feed API](https://api.wikimedia.org/wiki/Feed_API) | none | Wiki Trending, Photo Frame |
| Asteroid close approaches | [NASA/JPL SBDB CAD API](https://ssd-api.jpl.nasa.gov/doc/cad.html) | none | Asteroid Flyby |
| Game server status | [mcsrvstat.us](https://api.mcsrvstat.us/) | none | Game Server |
| TV schedule | [TVMaze](https://www.tvmaze.com/api) | none | TV Tonight |
| Location (fallback) | ip-api.com | none | only if you haven't set a city |
| GitHub | GitHub REST API | optional token | GitHub Graph, CI radiator |
| Your services | Home Assistant, OBS, AnkiConnect, OctoPrint / Moonraker, Jellyfin / Plex, ntfy | yours | the matching apps |

**Health:** `uv run python scripts/api_health.py` probes every endpoint above and writes [docs/API_HEALTH.md](docs/API_HEALTH.md).

**Fair use:** every provider polls within its documented limits; those limits are enforced in `src/deskdot/providers/`.
Images and sprites are fetched at runtime and never bundled in this repository.

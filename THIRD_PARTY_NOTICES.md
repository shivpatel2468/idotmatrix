# Third-party notices

DotDeck's own code, pixel art, characters and bitmap fonts are original and released under the [MIT License](LICENSE).

## Trademarks

- **iDotMatrix** is a product name of its respective owner. DotDeck is an independent project, not affiliated with or
  endorsed by them; the name is used only to identify compatible hardware.
- **Claude** and **Anthropic** are trademarks of Anthropic. The "Agent" mascot is an original pixel drawing inspired by
  Claude Code's mascot; it's used to show your own agent's activity.
- **Pokémon** and all related names are trademarks of Nintendo / Creatures / GAME FREAK. The Pokédex app fetches
  sprites at runtime from the community [PokéAPI](https://pokeapi.co/); none are included here.
- Other names (GitHub, Home Assistant, OBS, Spotify, Xbox, PlayStation, Nintendo Switch…) belong to their owners and
  are mentioned only to describe compatibility.

## Major dependencies

| Component | License |
| --- | --- |
| [FastAPI](https://fastapi.tiangolo.com/), [Starlette](https://www.starlette.io/), [Uvicorn](https://www.uvicorn.org/) | MIT / BSD-3-Clause |
| [Pydantic](https://docs.pydantic.dev/) | MIT |
| [NumPy](https://numpy.org/) | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | MIT-CMU (HPND) |
| [bleak](https://github.com/hbldh/bleak) | MIT |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT |
| [React](https://react.dev/), [Vite](https://vite.dev/), [Tailwind CSS](https://tailwindcss.com/), [lucide](https://lucide.dev/) | MIT / ISC |
| [Chaquopy](https://chaquo.com/chaquopy/) (Android app) | MIT |

The Android app vendors a cross-compiled wheel of [pydantic-core](https://github.com/pydantic/pydantic-core) (MIT),
built from the unmodified upstream source (`android/tools/build-pydantic-core.sh`).

## Data

Live data comes from public APIs under their own terms; see [DATA_SOURCES.md](DATA_SOURCES.md).

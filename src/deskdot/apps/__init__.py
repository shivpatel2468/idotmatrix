"""Built-in apps. Importing this package registers them; `load_plugins()` adds user apps."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from . import (
    activeapp,
    agent,
    airquality,
    ambient,
    anki,
    arcade,
    avatar,
    boids,
    brain,
    calendar,
    canvas,
    cards,
    chess,
    ci,
    clock,
    composer,
    currency,
    custom,
    daily,
    daynight,
    emotes,
    extras,
    eyebreak,
    fiveoclock,
    flybrain,
    focuspet,
    fontlab,
    gallery,
    gamedeals,
    games,
    habits,
    hassentity,
    headlines,
    holidays,
    live,
    loops,
    markets,
    mediaserver,
    native,
    nowplaying,
    obs,
    onair,
    pets,
    petworld,
    photoframe,
    pixabots,
    planets,
    pokedex,
    printer,
    progress,
    qr,
    quakes,
    radar,
    rainradar,
    raycaster,
    sand,
    scores,
    sky,
    space,
    stocks,
    synthwave,
    sysmon,
    text,
    tides,
    timer,
    trivia,
    uptime,
    wear,
    weather,
    wireframe,
)

log = logging.getLogger("deskdot.plugins")

BUILTIN = (
    calendar,
    daynight,
    fiveoclock,
    habits,
    loops,
    planets,
    progress,
    qr,
    tides,
    wear,
    anki,
    ci,
    mediaserver,
    obs,
    printer,
    uptime,
    pokedex,
    avatar,
    chess,
    gamedeals,
    photoframe,
    pixabots,
    daily,
    currency,
    headlines,
    trivia,
    rainradar,
    quakes,
    holidays,
    airquality,
    space,
    sky,
    clock,
    weather,
    sysmon,
    markets,
    scores,
    nowplaying,
    gallery,
    canvas,
    cards,
    text,
    agent,
    ambient,
    timer,
    native,
    activeapp,
    live,
    arcade,
    extras,
    fontlab,
    composer,
    emotes,
    radar,
    stocks,
    games,
    pets,
    petworld,
    onair,
    eyebreak,
    custom,
    hassentity,
    sand,
    raycaster,
    brain,
    focuspet,
    boids,
    synthwave,
    wireframe,
    flybrain,
)


def load_plugins(directory: Path) -> list[str]:
    """Import every *.py in `directory`; each registers apps with @register. Errors are logged, not fatal."""
    loaded: list[str] = []
    if not directory.is_dir():
        return loaded
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = f"deskdot_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            loaded.append(path.stem)
        except Exception:
            log.exception("plugin %s failed to load", path.name)
    return loaded

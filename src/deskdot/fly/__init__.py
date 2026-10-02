"""A fruit-fly brain for DeskDot: a real-time model of the fly's motion-vision pathway that sees the panel and
presses keys. See `brain.py`, `config.py` and docs/FLY_BRAIN.md."""

from .brain import FlyBrain, FlyState, Lure
from .config import PRESETS, FlyConfig

__all__ = ["PRESETS", "FlyBrain", "FlyConfig", "FlyState", "Lure"]

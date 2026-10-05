"""Games — a collection of self-playing arcade games (see games_core.py for the shared machinery).

Each game plays itself with a demo AI; press keys in the studio (arrows, A, B) to take over. After
10 s without input the AI resumes.
"""

from __future__ import annotations

from . import (
    arcade,
    games_action,
    games_board,
    games_bonus,
    games_city,
    games_classic,
    games_connect,
    games_party,
    games_penguin,
    games_platform,
    games_puzzle,
    games_road,
    games_rps,
    games_world,
)

GAME_IDS: tuple[str, ...] = (
    games_classic.Pong.id,
    games_classic.Breakout.id,
    games_classic.Flappy.id,
    games_classic.Dino.id,
    games_classic.Racer.id,
    games_puzzle.Tetris.id,
    games_puzzle.G2048.id,
    games_action.Invaders.id,
    games_action.Maze.id,
    games_action.Asteroids.id,
    games_action.Infinity.id,
    games_bonus.Mines.id,
    games_bonus.Starship.id,
    games_board.TicTacToe.id,
    games_party.LightCycles.id,
    games_world.DigWorld.id,
    games_city.NeonHeat.id,
    games_road.StreetSurge.id,
    games_platform.LeafLeap.id,
    games_connect.FourUp.id,
    games_rps.RockPaperScissors.id,
    games_penguin.PenguinEscape.id,
    arcade.Arcade.id,
)

__all__ = ["GAME_IDS"]

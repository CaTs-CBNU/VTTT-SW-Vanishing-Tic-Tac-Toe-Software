"""Play difficulty levels against each other in every mode and print the score table.

python tools/difficulty_match.py [--games 40] [--modes vanishing gravity ...]
Score = (wins + draws / 2) / games for the stronger level; colours alternate each game.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vttt.ai import GameAI
from vttt.config import runtime_config
from vttt.rules import Game, MODES

PAIRS = (("normal", "easy"), ("hard", "normal"))


def match(job):
    mode, strong, weak, games, seed = job
    rng = random.Random(seed)
    ai = GameAI(runtime_config(), rng)
    wins = draws = 0
    for g in range(games):
        game = Game(mode, max_moves=80)
        strong_mark = 1 if g % 2 == 0 else -1
        for _ in range(2):  # random opening so repeated games differ
            game.play(rng.choice(game.legal_actions()))
        while not game.done:
            level = strong if game.turn == strong_mark else weak
            game.play(ai.select_action(game, level))
        wins += game.winner == strong_mark
        draws += game.winner == 0
    return mode, strong, weak, wins, draws, games


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=40)
    parser.add_argument("--modes", nargs="+", default=[m for m in MODES if m != "original"])
    args = parser.parse_args()
    jobs = [(m, s, w, args.games, i) for i, (m, (s, w)) in
            enumerate((m, p) for m in args.modes for p in PAIRS)]
    with ProcessPoolExecutor() as pool:
        for mode, strong, weak, wins, draws, games in pool.map(match, jobs):
            score = (wins + draws / 2) / games
            print(f"{mode:12s} {strong:>6s} vs {weak:<6s} W/D/L={wins}/{draws}/{games - wins - draws}  score={score:.0%}")


if __name__ == "__main__":
    main()

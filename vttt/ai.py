"""Budgeted tactical search with the trained CNN guiding vanishing-mode moves."""

import logging
import math
import random
import time
from pathlib import Path

from .rules import LINES

LOG = logging.getLogger(__name__)
LIMITS = {"easy": (1, 0.12, 0.30), "normal": (4, 0.45, 0.0), "hard": (8, 1.20, 0.0)}


class SearchStopped(Exception):
    pass


def board_score(game, root):
    if game.done:
        return 0.0 if game.winner == 0 else (10000.0 if game.winner == root else -10000.0)
    score = 0.0
    for line in LINES:
        mine = sum(game.board[a] == root for a in line)
        other = sum(game.board[a] == -root for a in line)
        if not other:
            score += (0, 1, 12, 500)[mine]
        if not mine:
            score -= (0, 1, 14, 500)[other]
    lives = game.lifetimes()
    for a, player in enumerate(game.board):
        if player:
            positional = 1.2 if a == 4 else 0.7 if a in (0, 2, 6, 8) else 0.3
            score += (1 if player == root else -1) * positional * lives.get(a, 1)
    return score


class GameAI:
    def __init__(self, config=None, rng=None):
        self.rng = rng or random.Random()
        self.network = None
        self.status = "탐색 AI"
        if config:
            for key, name in (("model_npz", "NumpyQNet"), ("model_pt", "TorchQNet")):
                if Path(config[key]).is_file():
                    try:
                        from . import network
                        self.network = getattr(network, name)(config[key])
                        self.status = "학습 CNN + 탐색 AI"
                        break
                    except Exception as exc:
                        LOG.warning("Cannot load %s: %s", config[key], exc)
        if self.network is None and config:
            LOG.warning("학습 모델을 불러오지 못해 규칙 탐색 AI로 동작합니다.")

    def select_action(self, game, difficulty="normal", cancel=None):
        valid = game.legal_actions()
        if not valid:
            raise ValueError("No move in a finished game")
        max_depth, seconds, random_ratio = LIMITS[difficulty]
        root = game.turn
        self.nodes = 0
        deadline = time.monotonic() + seconds

        def check_budget():
            if (cancel and cancel.is_set()) or time.monotonic() >= deadline:
                raise SearchStopped()

        # Simulate own move AND every opponent reply, including vanishing/rotation.
        safe = []
        for action in valid:
            child = game.clone()
            child.play(action)
            if child.done and child.winner == root:
                return action
            loses_next = False
            for reply in child.legal_actions():
                grandchild = child.clone()
                grandchild.play(reply)
                if grandchild.done and grandchild.winner == -root:
                    loses_next = True
                    break
            if not loses_next:
                safe.append(action)
        candidates = safe or valid
        if random_ratio and self.rng.random() < random_ratio:
            return self.rng.choice(candidates)

        prior = {a: 0.0 for a in valid}
        if game.mode_key == "vanishing" and self.network is not None:
            values = self.network(game.observation())
            prior = {a: float(values[a]) if math.isfinite(float(values[a])) else 0.0 for a in valid}
        candidates.sort(key=lambda a: (prior[a], a == 4, a in (0, 2, 6, 8)), reverse=True)
        # Guarantee a legal completed fallback even when model inference consumed the budget.
        best = candidates[0]
        table = {}

        def search(state, depth, alpha, beta):
            self.nodes += 1
            check_budget()
            if state.done:
                value = board_score(state, root)
                return value + (depth if value > 0 else -depth if value < 0 else 0)
            if depth == 0:
                return board_score(state, root)
            key = (state.key(), depth)
            if key in table:
                return table[key]
            alpha_original, beta_original = alpha, beta
            maximizing = state.turn == root
            value = -math.inf if maximizing else math.inf
            complete = True
            actions = sorted(state.legal_actions(), key=lambda a: (a == 4, a in (0, 2, 6, 8)), reverse=True)
            for action in actions:
                child = state.clone()
                child.play(action)
                score = search(child, depth - 1, alpha, beta)
                if maximizing:
                    value, alpha = max(value, score), max(alpha, score)
                else:
                    value, beta = min(value, score), min(beta, score)
                if alpha >= beta:
                    complete = False
                    break
            # Cutoff bounds are never stored as exact values.
            if complete and alpha_original < value < beta_original:
                table[key] = value
            return value

        for depth in range(1, max_depth + 1):
            iteration_best, iteration_score = best, -math.inf
            try:
                for action in candidates:
                    child = game.clone()
                    child.play(action)
                    score = search(child, depth - 1, -math.inf, math.inf)
                    # Neural preference orders equal-score actions, never overrides wins/losses.
                    if score > iteration_score:
                        iteration_best, iteration_score = action, score
                best = iteration_best
                if iteration_score >= 10000:
                    break
            except SearchStopped:
                break
        return best

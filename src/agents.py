"""Agents and tactical helper functions for Vanishing Tic-Tac-Toe."""

from __future__ import annotations

import random
from typing import List

import numpy as np
import torch
import torch.nn as nn

from .data_loader import VanishingTicTacToeEnv


class RandomAgent:
    def select_action(self, env: VanishingTicTacToeEnv, epsilon: float = 0.0) -> int:
        valid = env.get_valid_actions()
        return int(np.random.choice(valid))


class DQNAgent:
    def __init__(self, model: nn.Module, device: torch.device):
        self.model = model
        self.device = device

    @torch.no_grad()
    def select_action(self, env: VanishingTicTacToeEnv, epsilon: float = 0.0) -> int:
        valid_actions = env.get_valid_actions()
        if len(valid_actions) == 0:
            return 0

        if random.random() < epsilon:
            return int(np.random.choice(valid_actions))

        state = torch.tensor(
            env.get_observation(), dtype=torch.float32, device=self.device
        ).unsqueeze(0)
        q_values = self.model(state).squeeze(0)
        invalid_actions = np.where(env.board.reshape(-1) != 0)[0]
        q_values[torch.tensor(invalid_actions, device=self.device)] = -1e9
        return int(torch.argmax(q_values).item())


class SearchAgent:
    """
    Hybrid inference/play agent.

    1. immediate win
    2. immediate block
    3. avoid moves that allow opponent immediate win
    4. alpha-beta search with neural leaf evaluation
    """

    def __init__(self, model: nn.Module, device: torch.device, search_depth: int = 6):
        self.model = model
        self.device = device
        self.search_depth = search_depth
        self.tt = {}

    def select_action(self, env: VanishingTicTacToeEnv, epsilon: float = 0.0) -> int:
        valid = env.get_valid_actions().tolist()
        if len(valid) == 1:
            return valid[0]

        wins = immediate_winning_cells(env, env.current_player)
        if wins:
            return int(wins[0])

        opp_wins = immediate_winning_cells(env, -env.current_player)
        if opp_wins:
            return int(opp_wins[0])

        safe_actions = []
        for action in valid:
            temp = env.clone()
            temp.step(int(action))
            if not immediate_winning_cells(temp, temp.current_player):
                safe_actions.append(int(action))
        candidate_actions = safe_actions if safe_actions else valid

        best_action = candidate_actions[0]
        best_score = -1e9
        alpha, beta = -1e9, 1e9
        root_player = env.current_player

        for action in self._order_actions(env, candidate_actions):
            temp = env.clone()
            _, _, done, _ = temp.step(int(action))
            if done:
                score = (
                    1e6
                    if temp.winner == root_player
                    else (-1e6 if temp.winner == -root_player else 0.0)
                )
            else:
                score = self._alphabeta(temp, self.search_depth - 1, alpha, beta, root_player)

            if score > best_score:
                best_score = score
                best_action = int(action)
            alpha = max(alpha, best_score)

        return int(best_action)

    def _encode_env_key(self, env: VanishingTicTacToeEnv):
        return (
            tuple(env.board.reshape(-1).tolist()),
            tuple(env.pieces[1]),
            tuple(env.pieces[-1]),
            env.current_player,
            env.step_count,
        )

    def _alphabeta(
        self,
        env: VanishingTicTacToeEnv,
        depth: int,
        alpha: float,
        beta: float,
        root_player: int,
    ) -> float:
        key = (self._encode_env_key(env), depth, alpha > -1e8, beta < 1e8)
        if key in self.tt:
            return self.tt[key]

        if env.done:
            if env.winner == root_player:
                return 1e6
            if env.winner == -root_player:
                return -1e6
            return 0.0

        if depth <= 0:
            score = self._evaluate_leaf(env, root_player)
            self.tt[key] = score
            return score

        valid = env.get_valid_actions().tolist()
        maximizing = env.current_player == root_player

        if maximizing:
            value = -1e9
            for action in self._order_actions(env, valid):
                temp = env.clone()
                temp.step(int(action))
                value = max(value, self._alphabeta(temp, depth - 1, alpha, beta, root_player))
                alpha = max(alpha, value)
                if beta <= alpha:
                    break
        else:
            value = 1e9
            for action in self._order_actions(env, valid):
                temp = env.clone()
                temp.step(int(action))
                value = min(value, self._alphabeta(temp, depth - 1, alpha, beta, root_player))
                beta = min(beta, value)
                if beta <= alpha:
                    break

        self.tt[key] = value
        return value

    @torch.no_grad()
    def _evaluate_leaf(self, env: VanishingTicTacToeEnv, root_player: int) -> float:
        if env.current_player == root_player:
            obs = env.get_observation()
            sign = 1.0
        else:
            obs = np.stack([env.get_observation()[1], env.get_observation()[0]], axis=0)
            sign = -1.0

        state = torch.tensor(obs, dtype=torch.float32, device=self.device).unsqueeze(0)
        q_values = self.model(state).squeeze(0)
        valid = env.get_valid_actions()
        if len(valid) == 0:
            return 0.0
        masked_q = q_values.clone()
        invalid = np.setdiff1d(np.arange(9), valid)
        if len(invalid) > 0:
            masked_q[torch.tensor(invalid, device=self.device)] = -1e9
        val = float(masked_q.max().item())

        tactical = heuristic_score(env, root_player)
        return sign * val + tactical

    def _order_actions(self, env: VanishingTicTacToeEnv, actions: List[int]) -> List[int]:
        center = [4] if 4 in actions else []
        corners = [action for action in [0, 2, 6, 8] if action in actions]
        edges = [action for action in actions if action not in center and action not in corners]

        win_now = immediate_winning_cells(env, env.current_player)
        block_now = immediate_winning_cells(env, -env.current_player)
        ordered = []
        for group in [win_now, block_now, center, corners, edges]:
            for action in group:
                if action in actions and action not in ordered:
                    ordered.append(action)
        for action in actions:
            if action not in ordered:
                ordered.append(action)
        return ordered


def line_triplets():
    return [
        [0, 1, 2],
        [3, 4, 5],
        [6, 7, 8],
        [0, 3, 6],
        [1, 4, 7],
        [2, 5, 8],
        [0, 4, 8],
        [2, 4, 6],
    ]


def heuristic_score(env: VanishingTicTacToeEnv, root_player: int) -> float:
    flat = env.board.reshape(-1)
    score = 0.0
    for line in line_triplets():
        vals = flat[line]
        mine = np.sum(vals == root_player)
        opp = np.sum(vals == -root_player)
        empty = np.sum(vals == 0)
        if mine == 2 and empty == 1:
            score += 0.20
        if opp == 2 and empty == 1:
            score -= 0.24
        if mine == 1 and empty == 2:
            score += 0.03
        if opp == 1 and empty == 2:
            score -= 0.04

    for mark, sign in [(root_player, 1.0), (-root_player, -1.0)]:
        queue = env.pieces[mark]
        for idx, (r, c) in enumerate(queue):
            lifespan = env.max_pieces - (len(queue) - 1 - idx)
            action = r * 3 + c
            if action == 4:
                score += sign * (0.06 * lifespan)
            elif action in [0, 2, 6, 8]:
                score += sign * (0.04 * lifespan)
            else:
                score += sign * (0.02 * lifespan)
    return float(score)


def made_two_in_row(prev_env: VanishingTicTacToeEnv, player: int, action: int) -> bool:
    temp_env = prev_env.clone()
    temp_env.step(action)
    board = temp_env.board == player

    lines = []
    for i in range(3):
        lines.append(board[i, :])
        lines.append(board[:, i])
    lines.append(np.array([board[0, 0], board[1, 1], board[2, 2]]))
    lines.append(np.array([board[0, 2], board[1, 1], board[2, 0]]))

    raw_board = temp_env.board
    for idx, line in enumerate(lines):
        if line.sum() == 2:
            if idx < 6:
                i = idx // 2
                vals = raw_board[i, :] if idx % 2 == 0 else raw_board[:, i]
            elif idx == 6:
                vals = np.array([raw_board[0, 0], raw_board[1, 1], raw_board[2, 2]])
            else:
                vals = np.array([raw_board[0, 2], raw_board[1, 1], raw_board[2, 0]])
            if np.sum(vals == 0) == 1:
                return True
    return False


def blocked_opponent_threat(prev_env: VanishingTicTacToeEnv, player: int, action: int) -> bool:
    opponent = -player
    threat_cells = immediate_winning_cells(prev_env, opponent)
    return action in threat_cells


def immediate_winning_cells(env: VanishingTicTacToeEnv, player: int) -> List[int]:
    wins = []
    valid = env.get_valid_actions()
    for action in valid:
        temp = env.clone()
        temp.current_player = player
        _, _, done, _ = temp.step(int(action))
        if done and temp.winner == player:
            wins.append(int(action))
    return wins

"""Game environment and replay-buffer utilities for Vanishing Tic-Tac-Toe."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import torch


class VanishingTicTacToeEnv:
    """
    3x3 Vanishing Tic-Tac-Toe environment.

    - board: 0 empty, 1 player1, -1 player2
    - each player can keep at most 3 pieces on board
    - when placing the 4th piece, the oldest piece vanishes

    Observation:
        (2, 3, 3) float32
        channel 0 = current player's pieces with lifespan [1, 2, 3]
        channel 1 = opponent player's pieces with lifespan [1, 2, 3]
    """

    def __init__(self, board_size: int = 3, max_pieces: int = 3, max_steps: int = 200):
        self.board_size = board_size
        self.max_pieces = max_pieces
        self.max_steps = max_steps
        self.reset()

    def reset(self):
        self.board = np.zeros((self.board_size, self.board_size), dtype=np.int8)
        self.pieces = {1: [], -1: []}
        self.current_player = 1
        self.done = False
        self.winner = 0
        self.step_count = 0
        return self.get_observation()

    def clone(self):
        env = VanishingTicTacToeEnv(
            board_size=self.board_size,
            max_pieces=self.max_pieces,
            max_steps=self.max_steps,
        )
        env.board = self.board.copy()
        env.pieces = {
            1: list(self.pieces[1]),
            -1: list(self.pieces[-1]),
        }
        env.current_player = self.current_player
        env.done = self.done
        env.winner = self.winner
        env.step_count = self.step_count
        return env

    def get_observation(self):
        obs = np.zeros((2, self.board_size, self.board_size), dtype=np.float32)
        players = [self.current_player, -self.current_player]
        for channel_idx, player_mark in enumerate(players):
            queue = self.pieces[player_mark]
            for q_idx, (r, c) in enumerate(queue):
                lifespan = self.max_pieces - (len(queue) - 1 - q_idx)
                obs[channel_idx, r, c] = float(lifespan)
        return obs

    def get_valid_actions(self) -> np.ndarray:
        return np.where(self.board.reshape(-1) == 0)[0]

    def action_mask(self) -> np.ndarray:
        mask = np.zeros(self.board_size * self.board_size, dtype=np.float32)
        mask[self.get_valid_actions()] = 1.0
        return mask

    def step(self, action: int):
        if self.done:
            return self.get_observation(), 0.0, True, {"info": "already_done"}

        self.step_count += 1
        r, c = divmod(int(action), self.board_size)

        if self.board[r, c] != 0:
            self.done = True
            self.winner = -self.current_player
            return self.get_observation(), -10.0, True, {"info": "invalid_move"}

        self.pieces[self.current_player].append((r, c))
        self.board[r, c] = self.current_player

        if len(self.pieces[self.current_player]) > self.max_pieces:
            old_r, old_c = self.pieces[self.current_player].pop(0)
            self.board[old_r, old_c] = 0

        if self.check_win(self.current_player):
            self.done = True
            self.winner = self.current_player
            return self.get_observation(), 1.0, True, {"info": "win"}

        if self.step_count >= self.max_steps:
            self.done = True
            self.winner = 0
            return self.get_observation(), 0.0, True, {"info": "max_steps_draw"}

        self.current_player *= -1
        return self.get_observation(), 0.0, False, {}

    def check_win(self, player: int) -> bool:
        board = self.board == player
        for i in range(self.board_size):
            if np.all(board[i, :]) or np.all(board[:, i]):
                return True
        if board[0, 0] and board[1, 1] and board[2, 2]:
            return True
        if board[0, 2] and board[1, 1] and board[2, 0]:
            return True
        return False

    def render(self):
        chars = {0: ".", 1: "X", -1: "O"}
        print("\nBoard")
        for r in range(self.board_size):
            print(" ".join(chars[int(v)] for v in self.board[r]))
        print(f"current_player: {'X(1)' if self.current_player == 1 else 'O(-1)'}")
        print(f"pieces[1]: {self.pieces[1]}")
        print(f"pieces[-1]: {self.pieces[-1]}")
        print()


def action_to_coord(action: int, board_size: int = 3) -> Tuple[int, int]:
    return divmod(action, board_size)


def coord_to_action(r: int, c: int, board_size: int = 3) -> int:
    return r * board_size + c


def transform_coord(r: int, c: int, transform_id: int, board_size: int = 3) -> Tuple[int, int]:
    """Apply one of the 8 square symmetries to a board coordinate."""
    if transform_id >= 4:
        c = board_size - 1 - c
        transform_id -= 4

    if transform_id == 0:
        return r, c
    if transform_id == 1:
        return c, board_size - 1 - r
    if transform_id == 2:
        return board_size - 1 - r, board_size - 1 - c
    if transform_id == 3:
        return board_size - 1 - c, r
    raise ValueError("invalid transform_id")


def apply_transform_obs(obs: np.ndarray, transform_id: int) -> np.ndarray:
    """Apply one of the 8 square symmetries to an observation."""
    transformed = obs.copy()
    if transform_id >= 4:
        transformed = np.flip(transformed, axis=2)
        transform_id -= 4
    if transform_id > 0:
        transformed = np.rot90(transformed, k=transform_id, axes=(1, 2))
    return transformed.copy()


def apply_transform_action(action: int, transform_id: int, board_size: int = 3) -> int:
    r, c = action_to_coord(action, board_size)
    next_r, next_c = transform_coord(r, c, transform_id, board_size)
    return coord_to_action(next_r, next_c, board_size)


@dataclass
class Transition:
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: float
    next_valid_mask: np.ndarray


class ReplayBuffer:
    def __init__(self, capacity: int = 50000):
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)

    def __len__(self):
        return len(self.buffer)

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
        next_valid_mask: np.ndarray,
        augment: bool = False,
    ):
        if augment:
            for transform_id in range(8):
                transformed_state = apply_transform_obs(state, transform_id)
                transformed_next_state = apply_transform_obs(next_state, transform_id)
                transformed_action = apply_transform_action(action, transform_id, board_size=3)

                transformed_mask = np.zeros_like(next_valid_mask)
                valid_indices = np.where(next_valid_mask > 0)[0]
                for idx in valid_indices:
                    transformed_mask[apply_transform_action(int(idx), transform_id, 3)] = 1.0

                self.buffer.append(
                    Transition(
                        transformed_state,
                        transformed_action,
                        reward,
                        transformed_next_state,
                        float(done),
                        transformed_mask,
                    )
                )
        else:
            self.buffer.append(
                Transition(state, action, reward, next_state, float(done), next_valid_mask)
            )

    def sample(self, batch_size: int, device: torch.device):
        batch = random.sample(self.buffer, batch_size)
        states = torch.tensor(np.stack([t.state for t in batch]), dtype=torch.float32, device=device)
        actions = torch.tensor([t.action for t in batch], dtype=torch.long, device=device)
        rewards = torch.tensor([t.reward for t in batch], dtype=torch.float32, device=device)
        next_states = torch.tensor(np.stack([t.next_state for t in batch]), dtype=torch.float32, device=device)
        dones = torch.tensor([t.done for t in batch], dtype=torch.float32, device=device)
        next_masks = torch.tensor(np.stack([t.next_valid_mask for t in batch]), dtype=torch.float32, device=device)
        return states, actions, rewards, next_states, dones, next_masks

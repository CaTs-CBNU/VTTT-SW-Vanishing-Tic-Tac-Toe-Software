import os
import math
import time
import copy
import json
import random
import logging
import argparse
from dataclasses import dataclass
from collections import deque
from datetime import datetime
from typing import List, Tuple, Optional, Dict

import numpy as np

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.tensorboard import SummaryWriter


# ============================================================
# Utility
# ============================================================

def set_seed(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# ============================================================
# Environment
# ============================================================

class VanishingTicTacToeEnv:
    """
    3x3 Vanishing Tic-Tac-Toe
    - board: 0 empty, 1 player1, -1 player2
    - each player can keep at most 3 pieces on board
    - when placing the 4th piece, the oldest piece vanishes

    Observation:
        (2, 3, 3) float32
        channel 0 = current player's pieces with lifespan [1,2,3]
        channel 1 = opponent player's pieces with lifespan [1,2,3]
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

        # Place piece
        self.pieces[self.current_player].append((r, c))
        self.board[r, c] = self.current_player

        # Vanish oldest if exceeding limit
        if len(self.pieces[self.current_player]) > self.max_pieces:
            old_r, old_c = self.pieces[self.current_player].pop(0)
            self.board[old_r, old_c] = 0

        # Win check
        if self.check_win(self.current_player):
            self.done = True
            self.winner = self.current_player
            return self.get_observation(), 1.0, True, {"info": "win"}

        # Optional hard stop to avoid pathological endless games
        if self.step_count >= self.max_steps:
            self.done = True
            self.winner = 0
            return self.get_observation(), 0.0, True, {"info": "max_steps_draw"}

        # Continue
        self.current_player *= -1
        return self.get_observation(), 0.0, False, {}

    def check_win(self, player: int) -> bool:
        b = (self.board == player)
        for i in range(self.board_size):
            if np.all(b[i, :]) or np.all(b[:, i]):
                return True
        if b[0, 0] and b[1, 1] and b[2, 2]:
            return True
        if b[0, 2] and b[1, 1] and b[2, 0]:
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


# ============================================================
# Symmetry Augmentation
# ============================================================

def action_to_coord(action: int, board_size: int = 3) -> Tuple[int, int]:
    return divmod(action, board_size)


def coord_to_action(r: int, c: int, board_size: int = 3) -> int:
    return r * board_size + c


def transform_coord(r: int, c: int, transform_id: int, board_size: int = 3) -> Tuple[int, int]:
    # 8 symmetries of square: 4 rotations, each optionally flipped left-right after rotation
    if transform_id >= 4:
        # horizontal flip first
        c = board_size - 1 - c
        transform_id -= 4

    if transform_id == 0:
        return r, c
    elif transform_id == 1:  # rot90
        return c, board_size - 1 - r
    elif transform_id == 2:  # rot180
        return board_size - 1 - r, board_size - 1 - c
    elif transform_id == 3:  # rot270
        return board_size - 1 - c, r
    else:
        raise ValueError("invalid transform_id")


def apply_transform_obs(obs: np.ndarray, transform_id: int) -> np.ndarray:
    # obs shape: (2,3,3)
    x = obs.copy()
    if transform_id >= 4:
        x = np.flip(x, axis=2)
        transform_id -= 4
    if transform_id > 0:
        x = np.rot90(x, k=transform_id, axes=(1, 2))
    return x.copy()


def apply_transform_action(action: int, transform_id: int, board_size: int = 3) -> int:
    r, c = action_to_coord(action, board_size)
    nr, nc = transform_coord(r, c, transform_id, board_size)
    return coord_to_action(nr, nc, board_size)


# ============================================================
# Replay Buffer
# ============================================================

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
            for t in range(8):
                s_t = apply_transform_obs(state, t)
                ns_t = apply_transform_obs(next_state, t)
                a_t = apply_transform_action(action, t, board_size=3)

                # transform next valid mask
                transformed_mask = np.zeros_like(next_valid_mask)
                valid_idx = np.where(next_valid_mask > 0)[0]
                for idx in valid_idx:
                    transformed_mask[apply_transform_action(int(idx), t, 3)] = 1.0

                self.buffer.append(
                    Transition(s_t, a_t, reward, ns_t, float(done), transformed_mask)
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


# ============================================================
# Model
# ============================================================

class ResidualBlock(nn.Module):
    def __init__(self, channels: int):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x):
        residual = x
        x = F.relu(self.bn1(self.conv1(x)), inplace=True)
        x = self.bn2(self.conv2(x))
        x = F.relu(x + residual, inplace=True)
        return x


class VanishQNet(nn.Module):
    """
    Input: (B,2,3,3)
    Output: (B,9) Q-values
    """
    def __init__(self, in_channels: int = 2, channels: int = 128, num_blocks: int = 5, board_size: int = 3):
        super().__init__()
        self.board_size = board_size
        self.stem = nn.Sequential(
            nn.Conv2d(in_channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
        )
        self.blocks = nn.Sequential(*[ResidualBlock(channels) for _ in range(num_blocks)])
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(channels * board_size * board_size, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.1),
            nn.Linear(256, board_size * board_size),
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.blocks(x)
        return self.head(x)


# ============================================================
# Agents
# ============================================================

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

        state = torch.tensor(env.get_observation(), dtype=torch.float32, device=self.device).unsqueeze(0)
        q_values = self.model(state).squeeze(0)
        invalid_actions = np.where(env.board.reshape(-1) != 0)[0]
        q_values[torch.tensor(invalid_actions, device=self.device)] = -1e9
        return int(torch.argmax(q_values).item())


class SearchAgent:
    """
    Hybrid agent for inference/play:
    1) immediate win
    2) immediate block
    3) avoid moves that allow opponent immediate win
    4) alpha-beta search with neural leaf evaluation

    This is much stronger than plain greedy Q inference and is the recommended
    way to use a trained model for actual gameplay.
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

        # 1. immediate win
        wins = immediate_winning_cells(env, env.current_player)
        if wins:
            return int(wins[0])

        # 2. immediate block
        opp_wins = immediate_winning_cells(env, -env.current_player)
        if opp_wins:
            return int(opp_wins[0])

        # 3. avoid blunders that give opponent an immediate win
        safe_actions = []
        for a in valid:
            temp = env.clone()
            temp.step(int(a))
            if not immediate_winning_cells(temp, temp.current_player):
                safe_actions.append(int(a))
        candidate_actions = safe_actions if safe_actions else valid

        # 4. alpha-beta search with NN leaf evaluation
        best_action = candidate_actions[0]
        best_score = -1e9
        alpha, beta = -1e9, 1e9
        root_player = env.current_player

        for a in self._order_actions(env, candidate_actions):
            temp = env.clone()
            _, reward, done, _ = temp.step(int(a))
            if done:
                score = 1e6 if temp.winner == root_player else (-1e6 if temp.winner == -root_player else 0.0)
            else:
                score = self._alphabeta(temp, self.search_depth - 1, alpha, beta, root_player)

            if score > best_score:
                best_score = score
                best_action = int(a)
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

    def _alphabeta(self, env: VanishingTicTacToeEnv, depth: int, alpha: float, beta: float, root_player: int) -> float:
        key = (self._encode_env_key(env), depth, alpha > -1e8, beta < 1e8)
        if key in self.tt:
            return self.tt[key]

        if env.done:
            if env.winner == root_player:
                return 1e6
            elif env.winner == -root_player:
                return -1e6
            else:
                return 0.0

        if depth <= 0:
            score = self._evaluate_leaf(env, root_player)
            self.tt[key] = score
            return score

        valid = env.get_valid_actions().tolist()
        maximizing = (env.current_player == root_player)

        if maximizing:
            value = -1e9
            for a in self._order_actions(env, valid):
                temp = env.clone()
                temp.step(int(a))
                value = max(value, self._alphabeta(temp, depth - 1, alpha, beta, root_player))
                alpha = max(alpha, value)
                if beta <= alpha:
                    break
        else:
            value = 1e9
            for a in self._order_actions(env, valid):
                temp = env.clone()
                temp.step(int(a))
                value = min(value, self._alphabeta(temp, depth - 1, alpha, beta, root_player))
                beta = min(beta, value)
                if beta <= alpha:
                    break

        self.tt[key] = value
        return value

    @torch.no_grad()
    def _evaluate_leaf(self, env: VanishingTicTacToeEnv, root_player: int) -> float:
        # Convert env to root player's perspective for stable evaluation
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

        # Extra handcrafted tactical score to better reflect vanishing threats
        tactical = heuristic_score(env, root_player)
        return sign * val + tactical

    def _order_actions(self, env: VanishingTicTacToeEnv, actions: List[int]) -> List[int]:
        center = [4] if 4 in actions else []
        corners = [a for a in [0, 2, 6, 8] if a in actions]
        edges = [a for a in actions if a not in center and a not in corners]

        # prioritize immediate tactical cells first
        win_now = immediate_winning_cells(env, env.current_player)
        block_now = immediate_winning_cells(env, -env.current_player)
        ordered = []
        for group in [win_now, block_now, center, corners, edges]:
            for a in group:
                if a in actions and a not in ordered:
                    ordered.append(a)
        for a in actions:
            if a not in ordered:
                ordered.append(a)
        return ordered


def line_triplets():
    return [
        [0, 1, 2], [3, 4, 5], [6, 7, 8],
        [0, 3, 6], [1, 4, 7], [2, 5, 8],
        [0, 4, 8], [2, 4, 6],
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

    # lifespan-aware bonus/penalty: pieces that vanish soon are less trustworthy
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


# ============================================================
# Checkpoint / Logging
# ============================================================

def setup_logger(log_dir: str) -> logging.Logger:
    ensure_dir(log_dir)
    logger = logging.getLogger("vanish_train")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(os.path.join(log_dir, f"train_{timestamp}.log"), encoding="utf-8")
    fh.setFormatter(formatter)
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def save_checkpoint(
    save_path: str,
    model: nn.Module,
    target_model: nn.Module,
    optimizer: optim.Optimizer,
    episode: int,
    epsilon: float,
    best_win_rate: float,
    config: Dict,
):
    ensure_dir(os.path.dirname(save_path))
    torch.save(
        {
            "episode": episode,
            "model_state_dict": model.state_dict(),
            "target_model_state_dict": target_model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "epsilon": epsilon,
            "best_win_rate": best_win_rate,
            "config": config,
        },
        save_path,
    )


def load_checkpoint(
    load_path: str,
    model: nn.Module,
    target_model: Optional[nn.Module],
    optimizer: Optional[optim.Optimizer],
    device: torch.device,
):
    ckpt = torch.load(load_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    if target_model is not None and "target_model_state_dict" in ckpt:
        target_model.load_state_dict(ckpt["target_model_state_dict"])
    if optimizer is not None and "optimizer_state_dict" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return ckpt


# ============================================================
# Training helpers
# ============================================================

def masked_max_q(target_q: torch.Tensor, next_masks: torch.Tensor) -> torch.Tensor:
    # target_q shape: (B,9), next_masks shape: (B,9)
    masked_q = target_q.masked_fill(next_masks <= 0, -1e9)
    max_q = masked_q.max(dim=1).values
    # if no valid action exists, treat max q as 0
    max_q = torch.where(torch.isfinite(max_q), max_q, torch.zeros_like(max_q))
    return max_q


def compute_dqn_loss(
    model: nn.Module,
    target_model: nn.Module,
    batch,
    gamma: float,
):
    states, actions, rewards, next_states, dones, next_masks = batch

    q_values = model(states)
    current_q = q_values.gather(1, actions.unsqueeze(1)).squeeze(1)

    with torch.no_grad():
        next_q_target = target_model(next_states)
        next_max_q = masked_max_q(next_q_target, next_masks)
        target = rewards + gamma * (1.0 - dones) * next_max_q

    loss = F.smooth_l1_loss(current_q, target)
    return loss, current_q.mean().item(), target.mean().item()


def select_training_action(
    policy_agent: DQNAgent,
    env: VanishingTicTacToeEnv,
    epsilon: float,
    force_random_prob: float = 0.0,
) -> int:
    if random.random() < force_random_prob:
        return int(np.random.choice(env.get_valid_actions()))
    return policy_agent.select_action(env, epsilon=epsilon)


# ============================================================
# Self-play episode generation
# ============================================================

def run_self_play_episode(
    env: VanishingTicTacToeEnv,
    agent_x: DQNAgent,
    agent_o,
    replay_buffer: ReplayBuffer,
    epsilon_x: float,
    epsilon_o: float,
    gamma: float,
    augment: bool,
    reward_step_penalty: float = -0.01,
    reward_block_bonus: float = 0.05,
    reward_two_in_row_bonus: float = 0.03,
):
    """
    X(1) uses agent_x, O(-1) uses agent_o.
    Stores transitions from both players' viewpoints.
    Each transition uses the reward returned immediately after the acting player's move.

    Reward shaping:
    - small step penalty: encourage short wins
    - small bonus for creating immediate threat (two in a line with empty third)
    - small bonus for blocking opponent immediate threat
    """

    state = env.reset()
    done = False

    # store per-player last transition to apply terminal negative reward to loser
    pending = {1: None, -1: None}
    episode_info = {
        "winner": 0,
        "invalid": False,
        "num_steps": 0,
        "x_moves": 0,
        "o_moves": 0,
    }

    while not done:
        player = env.current_player
        acting_agent = agent_x if player == 1 else agent_o
        epsilon = epsilon_x if player == 1 else epsilon_o

        prev_env = env.clone()
        prev_state = state.copy()

        action = acting_agent.select_action(env, epsilon=epsilon)
        next_state, reward, done, info = env.step(action)
        episode_info["num_steps"] += 1
        if player == 1:
            episode_info["x_moves"] += 1
        else:
            episode_info["o_moves"] += 1

        # reward shaping
        shaped_reward = reward
        if not done:
            shaped_reward += reward_step_penalty
        if made_two_in_row(prev_env, player, action):
            shaped_reward += reward_two_in_row_bonus
        if blocked_opponent_threat(prev_env, player, action):
            shaped_reward += reward_block_bonus

        next_mask = np.zeros(9, dtype=np.float32) if done else env.action_mask()

        replay_buffer.push(
            state=prev_state,
            action=action,
            reward=shaped_reward,
            next_state=next_state.copy(),
            done=done,
            next_valid_mask=next_mask,
            augment=augment,
        )

        pending[player] = (prev_state.copy(), action, shaped_reward, next_state.copy(), done, next_mask.copy())

        if done:
            if info.get("info") == "invalid_move":
                episode_info["invalid"] = True
                episode_info["winner"] = -player
            else:
                episode_info["winner"] = env.winner

            # loser terminal penalty on latest own state if exists
            loser = -player if env.winner == player else player if env.winner == -player else 0
            if loser in pending and pending[loser] is not None and env.winner != 0:
                s, a, _, ns, _, _ = pending[loser]
                replay_buffer.push(
                    state=s,
                    action=a,
                    reward=-1.0,
                    next_state=ns,
                    done=True,
                    next_valid_mask=np.zeros(9, dtype=np.float32),
                    augment=augment,
                )
            break

        state = next_state

    return episode_info


def made_two_in_row(prev_env: VanishingTicTacToeEnv, player: int, action: int) -> bool:
    temp_env = prev_env.clone()
    obs, reward, done, info = temp_env.step(action)
    board = (temp_env.board == player)

    lines = []
    for i in range(3):
        lines.append(board[i, :])
        lines.append(board[:, i])
    lines.append(np.array([board[0, 0], board[1, 1], board[2, 2]]))
    lines.append(np.array([board[0, 2], board[1, 1], board[2, 0]]))

    raw_board = temp_env.board
    for idx, line in enumerate(lines):
        if line.sum() == 2:
            # find corresponding empty in real board for that line
            if idx < 6:
                i = idx // 2
                if idx % 2 == 0:  # row
                    vals = raw_board[i, :]
                else:             # col
                    vals = raw_board[:, i]
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
    for a in valid:
        temp = env.clone()
        temp.current_player = player
        _, reward, done, _ = temp.step(int(a))
        if done and temp.winner == player:
            wins.append(int(a))
    return wins


# ============================================================
# Evaluation
# ============================================================

def evaluate_against_random(
    model: nn.Module,
    device: torch.device,
    num_games: int = 200,
    model_first_ratio: float = 0.5,
):
    model.eval()
    stats = {
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "invalids": 0,
    }
    agent = DQNAgent(model, device)
    rand_agent = RandomAgent()

    with torch.no_grad():
        for _ in range(num_games):
            env = VanishingTicTacToeEnv()
            env.reset()
            model_mark = 1 if random.random() < model_first_ratio else -1

            while not env.done:
                if env.current_player == model_mark:
                    action = agent.select_action(env, epsilon=0.0)
                else:
                    action = rand_agent.select_action(env)
                _, _, done, info = env.step(action)
                if done:
                    break

            if info.get("info") == "invalid_move":
                stats["invalids"] += 1

            if env.winner == model_mark:
                stats["wins"] += 1
            elif env.winner == -model_mark:
                stats["losses"] += 1
            else:
                stats["draws"] += 1

    win_rate = stats["wins"] / num_games
    model.train()
    return win_rate, stats


def evaluate_against_checkpoint(
    model: nn.Module,
    opponent_model: nn.Module,
    device: torch.device,
    num_games: int = 200,
):
    model.eval()
    opponent_model.eval()
    agent_a = DQNAgent(model, device)
    agent_b = DQNAgent(opponent_model, device)

    stats = {"wins": 0, "losses": 0, "draws": 0, "invalids": 0}

    with torch.no_grad():
        for g in range(num_games):
            env = VanishingTicTacToeEnv()
            env.reset()
            model_mark = 1 if (g % 2 == 0) else -1

            while not env.done:
                if env.current_player == model_mark:
                    action = agent_a.select_action(env, epsilon=0.0)
                else:
                    action = agent_b.select_action(env, epsilon=0.0)
                _, _, done, info = env.step(action)
                if done:
                    break

            if info.get("info") == "invalid_move":
                stats["invalids"] += 1

            if env.winner == model_mark:
                stats["wins"] += 1
            elif env.winner == -model_mark:
                stats["losses"] += 1
            else:
                stats["draws"] += 1

    win_rate = stats["wins"] / num_games
    model.train()
    opponent_model.train()
    return win_rate, stats


# ============================================================
# Play
# ============================================================

def play_human_vs_ai(model: nn.Module, device: torch.device, human_first: bool = True, search_depth: int = 6):
    env = VanishingTicTacToeEnv()
    env.reset()
    ai_agent = SearchAgent(model, device, search_depth=search_depth)
    human_mark = 1 if human_first else -1

    print("=== Vanishing Tic-Tac-Toe ===")
    print("Cell index mapping:")
    print(f"0 1 2\n3 4 5\n6 7 8")

    while not env.done:
        env.render()
        if env.current_player == human_mark:
            valid = env.get_valid_actions().tolist()
            print(f"valid actions: {valid}")
            while True:
                try:
                    action = int(input("Your move (0-8): ").strip())
                    if action in valid:
                        break
                    print("Invalid action. choose from valid actions.")
                except Exception:
                    print("Please enter an integer 0-8.")
        else:
            action = ai_agent.select_action(env, epsilon=0.0)
            print(f"AI move: {action}")

        _, reward, done, info = env.step(action)

    env.render()
    if env.winner == human_mark:
        print("You win!")
    elif env.winner == -human_mark:
        print("AI wins!")
    else:
        print("Draw!")


# ============================================================
# Main Training
# ============================================================

def train(args):
    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    ensure_dir(args.output_dir)
    ensure_dir(os.path.join(args.output_dir, "checkpoints"))
    ensure_dir(os.path.join(args.output_dir, "tb"))
    ensure_dir(os.path.join(args.output_dir, "logs"))

    logger = setup_logger(os.path.join(args.output_dir, "logs"))
    writer = SummaryWriter(log_dir=os.path.join(args.output_dir, "tb"))

    model = VanishQNet(channels=args.channels, num_blocks=args.num_blocks).to(device)
    target_model = VanishQNet(channels=args.channels, num_blocks=args.num_blocks).to(device)
    target_model.load_state_dict(model.state_dict())
    target_model.eval()

    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=max(1, args.eval_every // max(1, args.log_every)),
        min_lr=1e-6,
    )

    replay_buffer = ReplayBuffer(capacity=args.buffer_size)

    start_episode = 1
    best_win_rate = -1.0
    epsilon = args.eps_start

    if args.resume and os.path.exists(args.resume):
        ckpt = load_checkpoint(args.resume, model, target_model, optimizer, device)
        start_episode = int(ckpt.get("episode", 0)) + 1
        epsilon = float(ckpt.get("epsilon", args.eps_start))
        best_win_rate = float(ckpt.get("best_win_rate", -1.0))
        logger.info(f"Resumed from {args.resume} at episode={start_episode}, epsilon={epsilon:.4f}")

    self_opponent_model = copy.deepcopy(model).to(device)
    self_opponent_model.eval()

    recent_rewards = deque(maxlen=100)
    recent_lengths = deque(maxlen=100)
    recent_losses = deque(maxlen=100)

    logger.info("=" * 80)
    logger.info("Start training")
    logger.info(json.dumps(vars(args), indent=2, ensure_ascii=False))
    logger.info(f"device = {device}")
    logger.info("=" * 80)

    global_step = 0

    for episode in range(start_episode, args.episodes + 1):
        env = VanishingTicTacToeEnv(max_steps=args.max_steps)
        train_agent_x = DQNAgent(model, device)

        if args.self_play_mode == "latest":
            opponent_agent = DQNAgent(model, device)
            epsilon_o = epsilon
        elif args.self_play_mode == "frozen":
            opponent_agent = DQNAgent(self_opponent_model, device)
            epsilon_o = max(args.min_opponent_epsilon, epsilon * 0.5)
        elif args.self_play_mode == "random_mix":
            if random.random() < args.random_opponent_ratio:
                opponent_agent = RandomAgent()
                epsilon_o = 0.0
            else:
                opponent_agent = DQNAgent(self_opponent_model, device)
                epsilon_o = max(args.min_opponent_epsilon, epsilon * 0.5)
        else:
            raise ValueError(f"Unknown self_play_mode: {args.self_play_mode}")

        episode_info = run_self_play_episode(
            env=env,
            agent_x=train_agent_x,
            agent_o=opponent_agent,
            replay_buffer=replay_buffer,
            epsilon_x=epsilon,
            epsilon_o=epsilon_o,
            gamma=args.gamma,
            augment=args.use_symmetry,
            reward_step_penalty=args.step_penalty,
            reward_block_bonus=args.block_bonus,
            reward_two_in_row_bonus=args.two_in_row_bonus,
        )

        # gradient updates after each episode
        episode_loss_sum = 0.0
        num_updates = 0
        if len(replay_buffer) >= args.warmup_size:
            for _ in range(args.updates_per_episode):
                batch = replay_buffer.sample(args.batch_size, device)
                loss, q_mean, target_mean = compute_dqn_loss(model, target_model, batch, args.gamma)

                optimizer.zero_grad()
                loss.backward()
                if args.grad_clip > 0:
                    torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
                optimizer.step()

                episode_loss_sum += float(loss.item())
                num_updates += 1
                global_step += 1

                if global_step % args.target_update_steps == 0:
                    target_model.load_state_dict(model.state_dict())

        episode_loss = episode_loss_sum / max(1, num_updates)
        recent_losses.append(episode_loss)

        # update frozen self-play opponent periodically
        if episode % args.self_play_update_every == 0:
            self_opponent_model.load_state_dict(model.state_dict())
            self_opponent_model.eval()

        # epsilon decay
        epsilon = max(args.eps_end, epsilon * args.eps_decay)

        # simple reward proxy
        outcome_reward = 1.0 if episode_info["winner"] == 1 else (-1.0 if episode_info["winner"] == -1 else 0.0)
        recent_rewards.append(outcome_reward)
        recent_lengths.append(episode_info["num_steps"])

        writer.add_scalar("train/episode_loss", episode_loss, episode)
        writer.add_scalar("train/epsilon", epsilon, episode)
        writer.add_scalar("train/buffer_size", len(replay_buffer), episode)
        writer.add_scalar("train/outcome_reward", outcome_reward, episode)
        writer.add_scalar("train/episode_length", episode_info["num_steps"], episode)
        writer.add_scalar("train/lr", optimizer.param_groups[0]["lr"], episode)

        if episode % args.log_every == 0:
            logger.info(
                f"Episode {episode:6d} | "
                f"loss={np.mean(recent_losses):.4f} | "
                f"eps={epsilon:.4f} | "
                f"buffer={len(replay_buffer):6d} | "
                f"avg_len={np.mean(recent_lengths):.2f} | "
                f"avg_reward={np.mean(recent_rewards):.3f} | "
                f"winner={episode_info['winner']:2d} | "
                f"invalid={episode_info['invalid']}"
            )

        if episode % args.eval_every == 0:
            win_rate_rand, stats_rand = evaluate_against_random(
                model=model,
                device=device,
                num_games=args.eval_games,
                model_first_ratio=0.5,
            )
            writer.add_scalar("eval_random/win_rate", win_rate_rand, episode)
            writer.add_scalar("eval_random/wins", stats_rand["wins"], episode)
            writer.add_scalar("eval_random/losses", stats_rand["losses"], episode)
            writer.add_scalar("eval_random/draws", stats_rand["draws"], episode)

            win_rate_self, stats_self = evaluate_against_checkpoint(
                model=model,
                opponent_model=self_opponent_model,
                device=device,
                num_games=args.eval_games,
            )
            writer.add_scalar("eval_self/win_rate", win_rate_self, episode)

            scheduler.step(win_rate_rand)

            logger.info(
                f"[Eval] ep={episode} | vs_random win_rate={win_rate_rand:.4f} "
                f"(W/L/D={stats_rand['wins']}/{stats_rand['losses']}/{stats_rand['draws']}) | "
                f"vs_frozen win_rate={win_rate_self:.4f} "
                f"(W/L/D={stats_self['wins']}/{stats_self['losses']}/{stats_self['draws']})"
            )

            latest_path = os.path.join(args.output_dir, "checkpoints", "latest.pt")
            save_checkpoint(
                save_path=latest_path,
                model=model,
                target_model=target_model,
                optimizer=optimizer,
                episode=episode,
                epsilon=epsilon,
                best_win_rate=best_win_rate,
                config=vars(args),
            )

            if win_rate_rand > best_win_rate:
                best_win_rate = win_rate_rand
                best_path = os.path.join(args.output_dir, "checkpoints", "best.pt")
                save_checkpoint(
                    save_path=best_path,
                    model=model,
                    target_model=target_model,
                    optimizer=optimizer,
                    episode=episode,
                    epsilon=epsilon,
                    best_win_rate=best_win_rate,
                    config=vars(args),
                )
                logger.info(f"New best checkpoint saved. best_win_rate={best_win_rate:.4f}")

        if episode % args.save_every == 0:
            periodic_path = os.path.join(args.output_dir, "checkpoints", f"episode_{episode}.pt")
            save_checkpoint(
                save_path=periodic_path,
                model=model,
                target_model=target_model,
                optimizer=optimizer,
                episode=episode,
                epsilon=epsilon,
                best_win_rate=best_win_rate,
                config=vars(args),
            )

    writer.close()
    logger.info("Training finished.")


# ============================================================
# CLI helpers
# ============================================================

def load_model_for_inference(checkpoint_path: str, device: torch.device, channels: int = 128, num_blocks: int = 5):
    model = VanishQNet(channels=channels, num_blocks=num_blocks).to(device)
    ckpt = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model, ckpt


def parse_args():
    parser = argparse.ArgumentParser(description="Vanishing Tic-Tac-Toe RL Full Code")

    subparsers = parser.add_subparsers(dest="mode", required=True)

    # train
    train_p = subparsers.add_parser("train")
    train_p.add_argument("--output_dir", type=str, default="./results/saved_models/vanish_runs")
    train_p.add_argument("--episodes", type=int, default=30000)
    train_p.add_argument("--batch_size", type=int, default=128)
    train_p.add_argument("--buffer_size", type=int, default=50000)
    train_p.add_argument("--warmup_size", type=int, default=1000)
    train_p.add_argument("--updates_per_episode", type=int, default=4)
    train_p.add_argument("--target_update_steps", type=int, default=200)
    train_p.add_argument("--self_play_update_every", type=int, default=500)
    train_p.add_argument("--eval_every", type=int, default=500)
    train_p.add_argument("--save_every", type=int, default=2000)
    train_p.add_argument("--log_every", type=int, default=50)
    train_p.add_argument("--eval_games", type=int, default=200)
    train_p.add_argument("--max_steps", type=int, default=200)

    train_p.add_argument("--lr", type=float, default=1e-3)
    train_p.add_argument("--weight_decay", type=float, default=1e-5)
    train_p.add_argument("--gamma", type=float, default=0.99)
    train_p.add_argument("--grad_clip", type=float, default=1.0)

    train_p.add_argument("--eps_start", type=float, default=1.0)
    train_p.add_argument("--eps_end", type=float, default=0.05)
    train_p.add_argument("--eps_decay", type=float, default=0.9995)

    train_p.add_argument("--channels", type=int, default=128)
    train_p.add_argument("--num_blocks", type=int, default=5)

    train_p.add_argument("--self_play_mode", type=str, default="random_mix", choices=["latest", "frozen", "random_mix"])
    train_p.add_argument("--random_opponent_ratio", type=float, default=0.3)
    train_p.add_argument("--min_opponent_epsilon", type=float, default=0.02)
    train_p.add_argument("--use_symmetry", action="store_true")

    train_p.add_argument("--step_penalty", type=float, default=-0.01)
    train_p.add_argument("--block_bonus", type=float, default=0.05)
    train_p.add_argument("--two_in_row_bonus", type=float, default=0.03)

    train_p.add_argument("--resume", type=str, default="")
    train_p.add_argument("--seed", type=int, default=42)
    train_p.add_argument("--cpu", action="store_true")

    # eval
    eval_p = subparsers.add_parser("eval")
    eval_p.add_argument("--checkpoint", type=str, required=True)
    eval_p.add_argument("--games", type=int, default=200)
    eval_p.add_argument("--channels", type=int, default=128)
    eval_p.add_argument("--num_blocks", type=int, default=5)
    eval_p.add_argument("--cpu", action="store_true")

    # play
    play_p = subparsers.add_parser("play")
    play_p.add_argument("--checkpoint", type=str, required=True)
    play_p.add_argument("--human_first", action="store_true")
    play_p.add_argument("--channels", type=int, default=128)
    play_p.add_argument("--num_blocks", type=int, default=5)
    play_p.add_argument("--cpu", action="store_true")
    play_p.add_argument("--search_depth", type=int, default=6)

    return parser.parse_args()


def main():
    args = parse_args()

    if args.mode == "train":
        train(args)

    elif args.mode == "eval":
        device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
        model, ckpt = load_model_for_inference(args.checkpoint, device, args.channels, args.num_blocks)
        win_rate, stats = evaluate_against_random(model, device, num_games=args.games)
        print("=" * 70)
        print(f"checkpoint : {args.checkpoint}")
        print(f"episode    : {ckpt.get('episode', 'N/A')}")
        print(f"win_rate   : {win_rate:.4f}")
        print(f"wins       : {stats['wins']}")
        print(f"losses     : {stats['losses']}")
        print(f"draws      : {stats['draws']}")
        print(f"invalids   : {stats['invalids']}")
        print("=" * 70)

    elif args.mode == "play":
        device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
        model, ckpt = load_model_for_inference(args.checkpoint, device, args.channels, args.num_blocks)
        print(f"Loaded checkpoint from episode {ckpt.get('episode', 'N/A')}")
        play_human_vs_ai(model, device, human_first=args.human_first, search_depth=args.search_depth)


if __name__ == "__main__":
    main()

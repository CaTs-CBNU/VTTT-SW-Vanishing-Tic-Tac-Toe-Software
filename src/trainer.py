"""Training and evaluation loop for Vanishing Tic-Tac-Toe DQN."""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
from collections import deque
from types import SimpleNamespace

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
try:
    from torch.utils.tensorboard import SummaryWriter
except ModuleNotFoundError:
    class SummaryWriter:  # fallback for environments without tensorboard installed
        def __init__(self, *args, **kwargs):
            pass

        def add_scalar(self, *args, **kwargs):
            pass

        def close(self):
            pass

from .agents import (
    DQNAgent,
    RandomAgent,
    blocked_opponent_threat,
    made_two_in_row,
)
from .data_loader import ReplayBuffer, VanishingTicTacToeEnv
from .models import VanishQNet
from .utils import ensure_dir, load_checkpoint, save_checkpoint, set_seed, setup_logger


def masked_max_q(target_q: torch.Tensor, next_masks: torch.Tensor) -> torch.Tensor:
    masked_q = target_q.masked_fill(next_masks <= 0, -1e9)
    max_q = masked_q.max(dim=1).values
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
    state = env.reset()
    done = False

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

        pending[player] = (
            prev_state.copy(),
            action,
            shaped_reward,
            next_state.copy(),
            done,
            next_mask.copy(),
        )

        if done:
            if info.get("info") == "invalid_move":
                episode_info["invalid"] = True
                episode_info["winner"] = -player
            else:
                episode_info["winner"] = env.winner

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


def evaluate_against_random(
    model: nn.Module,
    device: torch.device,
    num_games: int = 200,
    model_first_ratio: float = 0.5,
):
    model.eval()
    stats = {"wins": 0, "losses": 0, "draws": 0, "invalids": 0}
    agent = DQNAgent(model, device)
    rand_agent = RandomAgent()

    with torch.no_grad():
        for _ in range(num_games):
            env = VanishingTicTacToeEnv()
            env.reset()
            model_mark = 1 if random.random() < model_first_ratio else -1

            info = {}
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
        for game_idx in range(num_games):
            env = VanishingTicTacToeEnv()
            env.reset()
            model_mark = 1 if game_idx % 2 == 0 else -1

            info = {}
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

        if episode % args.self_play_update_every == 0:
            self_opponent_model.load_state_dict(model.state_dict())
            self_opponent_model.eval()

        epsilon = max(args.eps_end, epsilon * args.eps_decay)

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


def default_args_dict():
    return {
        "output_dir": "./results/saved_models/vanish_runs",
        "episodes": 30000,
        "batch_size": 128,
        "buffer_size": 50000,
        "warmup_size": 1000,
        "updates_per_episode": 4,
        "target_update_steps": 200,
        "self_play_update_every": 500,
        "eval_every": 500,
        "save_every": 2000,
        "log_every": 50,
        "eval_games": 200,
        "max_steps": 200,
        "lr": 1e-3,
        "weight_decay": 1e-5,
        "gamma": 0.99,
        "grad_clip": 1.0,
        "eps_start": 1.0,
        "eps_end": 0.05,
        "eps_decay": 0.9995,
        "channels": 128,
        "num_blocks": 5,
        "self_play_mode": "random_mix",
        "random_opponent_ratio": 0.3,
        "min_opponent_epsilon": 0.02,
        "use_symmetry": False,
        "step_penalty": -0.01,
        "block_bonus": 0.05,
        "two_in_row_bonus": 0.03,
        "resume": "",
        "seed": 42,
        "cpu": False,
    }


def load_args_from_config(config_path: str):
    args = default_args_dict()
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            args.update(json.load(f))
    return SimpleNamespace(**args)


def parse_args():
    parser = argparse.ArgumentParser(description="Train Vanishing Tic-Tac-Toe DQN")
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--output_dir", type=str, default=None)
    parser.add_argument("--episodes", type=int, default=None)
    parser.add_argument("--batch_size", type=int, default=None)
    parser.add_argument("--buffer_size", type=int, default=None)
    parser.add_argument("--warmup_size", type=int, default=None)
    parser.add_argument("--updates_per_episode", type=int, default=None)
    parser.add_argument("--target_update_steps", type=int, default=None)
    parser.add_argument("--self_play_update_every", type=int, default=None)
    parser.add_argument("--eval_every", type=int, default=None)
    parser.add_argument("--save_every", type=int, default=None)
    parser.add_argument("--log_every", type=int, default=None)
    parser.add_argument("--eval_games", type=int, default=None)
    parser.add_argument("--max_steps", type=int, default=None)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--weight_decay", type=float, default=None)
    parser.add_argument("--gamma", type=float, default=None)
    parser.add_argument("--grad_clip", type=float, default=None)
    parser.add_argument("--eps_start", type=float, default=None)
    parser.add_argument("--eps_end", type=float, default=None)
    parser.add_argument("--eps_decay", type=float, default=None)
    parser.add_argument("--channels", type=int, default=None)
    parser.add_argument("--num_blocks", type=int, default=None)
    parser.add_argument("--self_play_mode", type=str, default=None, choices=["latest", "frozen", "random_mix"])
    parser.add_argument("--random_opponent_ratio", type=float, default=None)
    parser.add_argument("--min_opponent_epsilon", type=float, default=None)
    parser.add_argument("--use_symmetry", action="store_true")
    parser.add_argument("--step_penalty", type=float, default=None)
    parser.add_argument("--block_bonus", type=float, default=None)
    parser.add_argument("--two_in_row_bonus", type=float, default=None)
    parser.add_argument("--resume", type=str, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--cpu", action="store_true")

    cli_args = parser.parse_args()
    args = vars(load_args_from_config(cli_args.config))
    for key, value in vars(cli_args).items():
        if key == "config":
            continue
        if value is not None:
            if key in ["use_symmetry", "cpu"]:
                if value:
                    args[key] = value
            else:
                args[key] = value
    return SimpleNamespace(**args)


def main():
    args = parse_args()
    train(args)


if __name__ == "__main__":
    main()

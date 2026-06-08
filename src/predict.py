"""Evaluation and human-vs-AI play utilities for trained models."""

from __future__ import annotations

import argparse

import torch

from .agents import SearchAgent
from .data_loader import VanishingTicTacToeEnv
from .models import VanishQNet
from .trainer import evaluate_against_random


def load_model_for_inference(
    checkpoint_path: str,
    device: torch.device,
    channels: int = 128,
    num_blocks: int = 5,
):
    model = VanishQNet(channels=channels, num_blocks=num_blocks).to(device)
    ckpt = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model, ckpt


def play_human_vs_ai(
    model: torch.nn.Module,
    device: torch.device,
    human_first: bool = True,
    search_depth: int = 6,
):
    env = VanishingTicTacToeEnv()
    env.reset()
    ai_agent = SearchAgent(model, device, search_depth=search_depth)
    human_mark = 1 if human_first else -1

    print("=== Vanishing Tic-Tac-Toe ===")
    print("Cell index mapping:")
    print("0 1 2\n3 4 5\n6 7 8")

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

        env.step(action)

    env.render()
    if env.winner == human_mark:
        print("You win!")
    elif env.winner == -human_mark:
        print("AI wins!")
    else:
        print("Draw!")


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate or play Vanishing Tic-Tac-Toe")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    eval_p = subparsers.add_parser("eval")
    eval_p.add_argument("--checkpoint", type=str, required=True)
    eval_p.add_argument("--games", type=int, default=200)
    eval_p.add_argument("--channels", type=int, default=128)
    eval_p.add_argument("--num_blocks", type=int, default=5)
    eval_p.add_argument("--cpu", action="store_true")

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
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model, ckpt = load_model_for_inference(args.checkpoint, device, args.channels, args.num_blocks)

    if args.mode == "eval":
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
        print(f"Loaded checkpoint from episode {ckpt.get('episode', 'N/A')}")
        play_human_vs_ai(model, device, human_first=args.human_first, search_depth=args.search_depth)


if __name__ == "__main__":
    main()

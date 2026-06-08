import torch
import numpy as np
import copy
from env import VanishingTicTacToeEnv
from model import DQN

def print_board(env):
    print("\n[현재 보드 상태]")
    print(" 0 | 1 | 2 ")
    print("---+---+---")
    print(" 3 | 4 | 5 ")
    print("---+---+---")
    print(" 6 | 7 | 8 \n")
    
    symbols = {0: ' ', 1: 'O', -1: 'X'}
    board_str = ""
    for r in range(3):
        for c in range(3):
            board_str += f" {symbols[env.board[r, c]]} "
            if c < 2: board_str += "|"
        if r < 2: board_str += "\n---+---+---\n"
    print(board_str)
    print("\n" + "="*20)
# ========================================== #
# 💡 알파-베타 가지치기가 적용된 미니맥스
# ========================================== #
def minimax(env, model, depth, alpha, beta, is_maximizing):
    valid_actions = env.get_valid_actions()

    # 1. 탐색 깊이 제한 도달 시 DQN 평가
    if depth == 0:
        state_tensor = torch.FloatTensor(env.get_observation()).unsqueeze(0)
        with torch.no_grad():
            q_values = model(state_tensor).squeeze(0).numpy()
        max_q = max([q_values[a] for a in valid_actions])
        return max_q if is_maximizing else -max_q

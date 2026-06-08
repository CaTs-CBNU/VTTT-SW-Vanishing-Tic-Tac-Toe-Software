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
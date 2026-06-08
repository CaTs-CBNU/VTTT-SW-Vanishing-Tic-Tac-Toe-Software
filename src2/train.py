import torch
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import random
import csv
import copy
from collections import deque
from env import VanishingTicTacToeEnv
from model import DQN

class ReplayBuffer:
    def __init__(self, capacity=50000):
        self.buffer = deque(maxlen=capacity)
    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))
    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return np.array(states), np.array(actions), np.array(rewards), np.array(next_states), np.array(dones)
    def __len__(self):
        return len(self.buffer)
    
def train():
    BATCH_SIZE = 128
    GAMMA = 0.99
    LR = 1e-4
    NUM_EPISODES = 50000
    TARGET_UPDATE = 500
    PRINT_INTERVAL = 500
    CHECKPOINT_INTERVAL = 10000

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"🔥 DDQN 기반 새로운 학습 시작! (사용 장치: {device.type.upper()}) 🔥")
    
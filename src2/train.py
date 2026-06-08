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
    
    env = VanishingTicTacToeEnv()
    
    policy_net = DQN().to(device)
    target_net = DQN().to(device)
    target_net.load_state_dict(policy_net.state_dict())
    target_net.eval()
    
    past_net = DQN().to(device)
    historical_models = []
    
    optimizer = optim.Adam(policy_net.parameters(), lr=LR)
    memory = ReplayBuffer(capacity=50000)
    
    epsilon = 1.0
    epsilon_decay = 0.9999 
    epsilon_min = 0.1
    
    csv_filename = "training_log_ddqn.csv"
    with open(csv_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Episode', 'Epsilon', 'Loss', 'Avg_Reward', 'P1_Win_Rate', 'P2_Win_Rate', 'Invalid_Rate'])

    recent_losses, recent_rewards = [], []
    p1_wins, p2_wins, invalid_moves = 0, 0, 0
    
    for episode in range(1, NUM_EPISODES + 1):
        if episode % 2000 == 0:
            historical_models.append(copy.deepcopy(policy_net.state_dict()))
            if len(historical_models) > 20: 
                historical_models.pop(0)

        if len(historical_models) > 0 and random.random() < 0.5:
            past_net.load_state_dict(random.choice(historical_models))
            past_net.eval()
            if random.random() < 0.5:
                p1_model, p2_model = policy_net, past_net
            else:
                p1_model, p2_model = past_net, policy_net
        else:
            p1_model, p2_model = policy_net, policy_net

        state = env.reset()
        done = False
        episode_reward = 0.0
        
        # ========================================== #
        # 💡 무한 루프 방지용 변수 초기화
        # ========================================== #
        step_count = 0  
        MAX_STEPS = 50  

        while not done:
            step_count += 1 # 턴 수 증가
            
            valid_actions = env.get_valid_actions()
            current_model = p1_model if env.current_player == 1 else p2_model
            current_eps = epsilon if current_model == policy_net else 0.05
            
            if random.random() < current_eps:
                action = random.choice(valid_actions)
            else:
                state_tensor = torch.FloatTensor(state).unsqueeze(0).to(device)
                with torch.no_grad():
                    q_values = current_model(state_tensor).squeeze(0).cpu().numpy()
                masked_q_values = np.full(9, -np.inf)
                for a in valid_actions:
                    masked_q_values[a] = q_values[a]
                action = int(np.argmax(masked_q_values))

            next_state, reward, done = env.step(action)
            
            # ========================================== #
            # 💡 무한 루프 강제 종료 및 무승부 페널티 로직
            # ========================================== #
            if not done and step_count >= MAX_STEPS:
                done = True
                reward = -0.5 # 무승부(질질 끈 것에 대한) 페널티 부여

            episode_reward += reward
            
            memory.push(state, action, reward, next_state, done)
            state = next_state

            if len(memory) > BATCH_SIZE:
                s, a, r, s_prime, d = memory.sample(BATCH_SIZE)
                
                s = torch.FloatTensor(s).to(device)
                a = torch.LongTensor(a).unsqueeze(1).to(device)
                r = torch.FloatTensor(r).unsqueeze(1).to(device)
                s_prime = torch.FloatTensor(s_prime).to(device)
                d = torch.FloatTensor(d).unsqueeze(1).to(device)

                # 현재 상태 Q값
                q_vals = policy_net(s).gather(1, a)
                
                # Double DQN (DDQN) 로직
                with torch.no_grad():
                    next_actions = policy_net(s_prime).argmax(1).unsqueeze(1)
                    next_q_values = target_net(s_prime).gather(1, next_actions)
                    target_q = r + (GAMMA * (-next_q_values) * (1 - d))

                loss = F.mse_loss(q_vals, target_q)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
                recent_losses.append(loss.item())

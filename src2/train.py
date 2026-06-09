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

# 💡 이슈 반영: 8방향 대칭(회전 및 반전) 데이터 증강 함수
def get_symmetries(state, action, next_state):
    symmetries = []
    action_mat = np.zeros((3, 3), dtype=int)
    action_mat[action // 3, action % 3] = 1

    for k in range(4):
        # 90도씩 회전
        s_rot = np.rot90(state, k=k, axes=(1, 2))
        sp_rot = np.rot90(next_state, k=k, axes=(1, 2))
        a_rot_mat = np.rot90(action_mat, k=k)
        symmetries.append((s_rot.copy(), int(np.argmax(a_rot_mat)), sp_rot.copy()))

        # 좌우 반전
        s_flip = np.flip(s_rot, axis=2)
        sp_flip = np.flip(sp_rot, axis=2)
        a_flip_mat = np.flip(a_rot_mat, axis=1)
        symmetries.append((s_flip.copy(), int(np.argmax(a_flip_mat)), sp_flip.copy()))

    return symmetries
    
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
        
        while not done:
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
            episode_reward += reward
            
            # 💡 이슈 반영: 1턴의 경험을 8개로 뻥튀기하여 버퍼에 삽입
            for sym_state, sym_action, sym_next_state in get_symmetries(state, action, next_state):
                memory.push(sym_state, sym_action, reward, sym_next_state, done)
                
            state = next_state

            if len(memory) > BATCH_SIZE:
                s, a, r, s_prime, d = memory.sample(BATCH_SIZE)
                
                s = torch.FloatTensor(s).to(device)
                a = torch.LongTensor(a).unsqueeze(1).to(device)
                r = torch.FloatTensor(r).unsqueeze(1).to(device)
                s_prime = torch.FloatTensor(s_prime).to(device)
                d = torch.FloatTensor(d).unsqueeze(1).to(device)

                q_vals = policy_net(s).gather(1, a)
                
                with torch.no_grad():
                    next_actions = policy_net(s_prime).argmax(1).unsqueeze(1)
                    next_q_values = target_net(s_prime).gather(1, next_actions)
                    target_q = r + (GAMMA * (-next_q_values) * (1 - d))

                loss = F.mse_loss(q_vals, target_q)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
                recent_losses.append(loss.item())
        
        recent_rewards.append(episode_reward)
        if reward > 0: 
            if env.current_player == 1: p1_wins += 1
            else: p2_wins += 1
        elif reward <= -10: 
            invalid_moves += 1

        epsilon = max(epsilon_min, epsilon * epsilon_decay)
        
        if episode % TARGET_UPDATE == 0:
            target_net.load_state_dict(policy_net.state_dict())

        if episode % PRINT_INTERVAL == 0:
            avg_loss = np.mean(recent_losses) if recent_losses else 0.0
            avg_reward = np.mean(recent_rewards) if recent_rewards else 0.0
            p1_win_rate = (p1_wins / PRINT_INTERVAL) * 100
            p2_win_rate = (p2_wins / PRINT_INTERVAL) * 100
            invalid_rate = (invalid_moves / PRINT_INTERVAL) * 100
            
            print(f"[{episode}/{NUM_EPISODES}] Eps: {epsilon:.3f} | Loss: {avg_loss:.4f} | Avg Reward: {avg_reward:.2f}")
            print(f" └─ P1 Win: {p1_win_rate:.1f}% | P2 Win: {p2_win_rate:.1f}% | Invalid: {invalid_rate:.1f}%")
            
            with open(csv_filename, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([episode, round(epsilon, 3), round(avg_loss, 4), round(avg_reward, 2), 
                                 round(p1_win_rate, 1), round(p2_win_rate, 1), round(invalid_rate, 1)])
            
            recent_losses.clear()
            recent_rewards.clear()
            p1_wins, p2_wins, invalid_moves = 0, 0, 0
        
        if episode % CHECKPOINT_INTERVAL == 0:
            checkpoint_name = f"ddqn_vanishing_ttt_{episode}.pth"
            torch.save(policy_net.state_dict(), checkpoint_name)
            print(f"💾 [체크포인트] {episode} 에피소드 DDQN 모델 저장 완료: {checkpoint_name}")

    print("학습 완료! 최종 DDQN 모델을 저장합니다...")
    torch.save(policy_net.state_dict(), "ddqn_vanishing_ttt_final.pth")
    print("저장 완료: ddqn_vanishing_ttt_final.pth")

if __name__ == "__main__":
    train()
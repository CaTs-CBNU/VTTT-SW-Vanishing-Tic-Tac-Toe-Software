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

    # 2. 내 턴 (최대 이익 탐색)
    if is_maximizing:
        max_eval = -float('inf')
        for action in valid_actions:
            sim_env = copy.deepcopy(env)
            _, reward, done = sim_env.step(action)
            
            if done and reward > 0: return 1000 # 필승 수
            
            eval_score = minimax(sim_env, model, depth - 1, alpha, beta, False)
            max_eval = max(max_eval, eval_score)
            
            # 가지치기 로직
            alpha = max(alpha, eval_score)
            if beta <= alpha:
                break # 더 탐색할 필요 없음 (Cut-off)
        return max_eval
    
    # 3. 상대방 턴 (나에게 최악의 상황 탐색)
    else:
        min_eval = float('inf')
        for action in valid_actions:
            sim_env = copy.deepcopy(env)
            _, reward, done = sim_env.step(action)
            
            if done and reward > 0: return -1000 # 필패 수
            
            eval_score = minimax(sim_env, model, depth - 1, alpha, beta, True)
            min_eval = min(min_eval, eval_score)
            
            # 가지치기 로직
            beta = min(beta, eval_score)
            if beta <= alpha:
                break # 더 탐색할 필요 없음 (Cut-off)
        return min_eval
    
# ========================================== #
# 💡 AI 최종 선택 (Depth 조절 가능)
# ========================================== #
def get_best_action(env, model, valid_actions, depth=7): # 👈 여기서 깊이를 5나 7로 조절하세요!
    best_action = valid_actions[0]
    best_score = -float('inf')
    
    alpha = -float('inf')
    beta = float('inf')

    for action in valid_actions:
        sim_env = copy.deepcopy(env)
        _, reward, done = sim_env.step(action)

        if done and reward > 0:
            return action

        score = minimax(sim_env, model, depth - 1, alpha, beta, False)

        if score > best_score:
            best_score = score
            best_action = action
            
        alpha = max(alpha, best_score)

    return best_action    

def play():
    env = VanishingTicTacToeEnv()
    model = DQN()
    
    # 학습된 5만 번짜리 최종 모델 불러오기
    try:
        model.load_state_dict(torch.load("vanishing_ttt_model_final.pth"))
        print("모델을 성공적으로 불러왔습니다!")
    except FileNotFoundError:
        print("모델 파일을 찾을 수 없습니다.")
        return
        
    model.eval()
    
    user_turn = input("선공(O)을 하시겠습니까? (y/n): ").strip().lower()
    human_player = 1 if user_turn == 'y' else -1
    
    state = env.reset()
    done = False
    
    print_board(env)
    
    while not done:
        valid_actions = env.get_valid_actions()
        
        # 인간의 턴
        if env.current_player == human_player:
            action = -1
            while action not in valid_actions:
                try:
                    action = int(input(f"어디에 두시겠습니까? (가능한 칸: {valid_actions}): "))
                    if action not in valid_actions:
                        print("잘못된 입력이거나 이미 돌이 있는 칸입니다. 다시 입력하세요.")
                except ValueError:
                    print("숫자를 입력해주세요.")
            
            state, reward, done = env.step(action)
        
        # AI의 턴
        else:
            print("AI가 3수 앞을 내다보며 생각 중입니다...")
            # depth=3 이면: 나의 수 -> 상대의 대응 -> 나의 다음 수 까지 시뮬레이션
            action = get_best_action(env, model, valid_actions, depth=3)
            print(f"AI가 {action}번 칸을 선택했습니다.")
            
            state, reward, done = env.step(action)

        print_board(env)

    if reward > 0:
        if env.current_player == human_player:
            print("🎉 축하합니다! 당신의 승리입니다!")
        else:
            print("💀 AI의 승리입니다! (수읽기에 당하셨군요)")
    else:
        print("게임 종료!")

if __name__ == "__main__":
    play()
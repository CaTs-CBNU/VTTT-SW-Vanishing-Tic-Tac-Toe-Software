import numpy as np

class VanishingTicTacToeEnv:
    def __init__(self):
        self.board_size = 3
        self.max_pieces = 3
        self.max_steps = 50  # 💡 이슈 반영: 최대 턴 수 제한
        self.reset()

    def reset(self):
        self.board = np.zeros((self.board_size, self.board_size), dtype=int)
        self.pieces = {1: [], -1: []}
        self.current_player = 1
        self.done = False
        self.step_count = 0  # 💡 턴 수 초기화
        return self.get_observation()
    
    def get_observation(self):
        obs = np.zeros((2, self.board_size, self.board_size), dtype=np.float32)
        players = [self.current_player, -self.current_player]
        
        for channel_idx, p in enumerate(players):
            queue = self.pieces[p]
            for q_idx, (r, c) in enumerate(queue):
                lifespan = 3 - (len(queue) - 1 - q_idx)
                obs[channel_idx, r, c] = lifespan
        return obs

    def get_valid_actions(self):
        return [i for i in range(9) if self.board[i//3, i%3] == 0]
    
    def step(self, action):
        if self.done: return self.get_observation(), 0, True

        self.step_count += 1  # 턴 수 증가

        r, c = divmod(action, self.board_size)

        if self.board[r, c] != 0:
            self.done = True
            return self.get_observation(), -1.0, True

        self.pieces[self.current_player].append((r, c))
        self.board[r, c] = self.current_player

        if len(self.pieces[self.current_player]) > self.max_pieces:
            old_r, old_c = self.pieces[self.current_player].pop(0)
            self.board[old_r, old_c] = 0

        if self.check_win(self.current_player):
            self.done = True
            reward = 1.0  # 승리 보상
        else:
            self.done = False
            reward = -0.01  # 턴 진행 페널티
            self.current_player *= -1

        # 💡 이슈 반영: 환경 내부에서 무한 루프 강제 종료 및 무승부 페널티 처리
        if not self.done and self.step_count >= self.max_steps:
            self.done = True
            reward = -0.5

        return self.get_observation(), reward, self.done
    
    def check_win(self, player):
        b = (self.board == player)
        for i in range(self.board_size):
            if np.all(b[i, :]) or np.all(b[:, i]): return True
        if b[0, 0] and b[1, 1] and b[2, 2]: return True
        if b[0, 2] and b[1, 1] and b[2, 0]: return True
        return False
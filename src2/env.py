import numpy as np

class VanishingTicTacToeEnv:
    def __init__(self):
        self.board_size = 3
        self.max_pieces = 3
        self.reset()

    def reset(self):
        self.board = np.zeros((self.board_size, self.board_size), dtype=int)
        self.pieces = {1: [], -1: []}
        self.current_player = 1
        self.done = False
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

        r, c = divmod(action, self.board_size)

        if self.board[r, c] != 0:
            self.done = True
            return self.get_observation(), -1.0, True

        self.pieces[self.current_player].append((r, c))
        self.board[r, c] = self.current_player

        if len(self.pieces[self.current_player]) > self.max_pieces:
            old_r, old_c = self.pieces[self.current_player].pop(0)
            self.board[old_r, old_c] = 0

        # env.py 의 step() 함수 내부 승패 판정 부분
        if self.check_win(self.current_player):
            self.done = True
            reward = 1.0  # 승리 보상
        else:
            self.done = False
            reward = -0.01  # 💡 턴 진행 페널티! (기존 0.0에서 변경)
            self.current_player *= -1
        return self.get_observation(), reward, self.done
    
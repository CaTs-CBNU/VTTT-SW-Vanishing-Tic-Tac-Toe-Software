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
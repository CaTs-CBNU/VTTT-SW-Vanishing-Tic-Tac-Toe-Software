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

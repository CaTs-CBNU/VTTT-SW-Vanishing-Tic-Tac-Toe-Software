"""Single source of truth for gameplay, simulations and temporary variant rules."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7),
         (2, 5, 8), (0, 4, 8), (2, 4, 6))


@dataclass(frozen=True)
class Mode:
    key: str
    title: str
    description: Tuple[str, ...]
    vanishing: bool = False
    gravity: bool = False
    blind: bool = False
    rotate_every: int = 0
    provisional: bool = False


MODES = {
    "vanishing": Mode("vanishing", "배니싱", (
        "한 사람당 말은 3개", "네 번째 착수 때", "가장 오래된 말 제거", "제거 후 세 칸이면 승리"), vanishing=True),
    "original": Mode("original", "오리지널", (
        "빈 칸에 번갈아 착수", "가로·세로·대각선", "세 칸을 이으면 승리", "판이 가득 차면 무승부")),
    "blind": Mode("blind", "블라인드", (
        "임시 규칙 · 기본 틱택토", "착수 후 전체 말을", "잠깐 공개한 뒤 숨김", "말의 위치를 기억하세요"), blind=True, provisional=True),
    "gravity": Mode("gravity", "그래비티", (
        "임시 규칙 · 기본 틱택토", "누른 칸의 세로줄에서", "가장 아래 빈 칸에 착수", "세 칸을 이으면 승리"), gravity=True, provisional=True),
    "switch_one": Mode("switch_one", "원스위칭", (
        "임시 규칙 · 배니싱 기반", "매 착수 후 판 전체를", "시계 방향으로 90도 회전", "말의 수명도 함께 이동"), vanishing=True, rotate_every=1, provisional=True),
    "switch_nine": Mode("switch_nine", "나인스위칭", (
        "임시 규칙 · 배니싱 기반", "두 사람 합계 9회마다", "판을 시계 방향 90도 회전", "말의 수명도 함께 이동"), vanishing=True, rotate_every=9, provisional=True),
}


def rotate_action(action: int) -> int:
    """Map one cell through a clockwise quarter turn."""
    row, col = divmod(action, 3)
    return col * 3 + (2 - row)


@dataclass
class Game:
    mode_key: str = "vanishing"
    max_moves: int = 200
    board: List[int] = field(default_factory=lambda: [0] * 9)
    queues: Dict[int, List[int]] = field(default_factory=lambda: {1: [], -1: []})
    turn: int = 1
    moves: int = 0
    winner: int = 0
    done: bool = False
    last_action: int = -1
    reason: str = ""
    winning_cells: Tuple[int, ...] = ()

    def __post_init__(self):
        if self.mode_key not in MODES:
            raise ValueError("Unknown game mode: " + self.mode_key)
        if self.max_moves < 9:
            raise ValueError("max_moves must be at least 9")

    @property
    def mode(self) -> Mode:
        return MODES[self.mode_key]

    def clone(self):
        return Game(self.mode_key, self.max_moves, self.board.copy(),
                    {p: q.copy() for p, q in self.queues.items()}, self.turn,
                    self.moves, self.winner, self.done, self.last_action,
                    self.reason, self.winning_cells)

    def landing(self, action: int) -> int:
        if not isinstance(action, int) or not 0 <= action < 9 or self.done:
            raise ValueError("진행 중인 게임에서 1~9번 칸을 선택하세요")
        if self.mode.gravity:
            for row in (2, 1, 0):
                cell = row * 3 + action % 3
                if self.board[cell] == 0:
                    return cell
            raise ValueError("이 세로줄은 가득 찼습니다")
        if self.board[action] != 0:
            raise ValueError("이미 말이 있는 칸입니다")
        return action

    def legal_actions(self) -> List[int]:
        if self.done:
            return []
        if self.mode.gravity:
            result = []
            for col in range(3):
                try:
                    result.append(self.landing(col))
                except ValueError:
                    pass
            return result
        return [a for a, p in enumerate(self.board) if p == 0]

    def play(self, action: int) -> int:
        """Apply one legal move atomically; invalid input never loses a turn."""
        cell = self.landing(action)
        player = self.turn
        self.board[cell] = player
        self.queues[player].append(cell)
        if self.mode.vanishing and len(self.queues[player]) > 3:
            self.board[self.queues[player].pop(0)] = 0
        self.moves += 1
        if self.mode.rotate_every and self.moves % self.mode.rotate_every == 0:
            moved = [0] * 9
            for old, mark in enumerate(self.board):
                moved[rotate_action(old)] = mark
            self.board = moved
            self.queues = {p: [rotate_action(a) for a in q] for p, q in self.queues.items()}
            cell = rotate_action(cell)
        self.last_action = cell
        for line in LINES:
            if all(self.board[a] == player for a in line):
                self.done, self.winner = True, player
                self.reason, self.winning_cells = "win", line
                break
        if not self.done and all(self.board):
            self.done, self.reason = True, "full"
        if not self.done and self.moves >= self.max_moves:
            self.done, self.reason = True, "limit"
        self.turn = -player
        return cell

    def lifetimes(self) -> Dict[int, int]:
        if not self.mode.vanishing:
            return {}
        return {a: 3 - (len(q) - 1 - i) for q in self.queues.values() for i, a in enumerate(q)}

    def observation(self):
        """Return the same current/opponent lifespan encoding as the supplied CNN."""
        import numpy as np
        obs = np.zeros((2, 3, 3), dtype=np.float32)
        for channel, player in enumerate((self.turn, -self.turn)):
            q = self.queues[player]
            for i, a in enumerate(q):
                obs[channel, a // 3, a % 3] = 3 - (len(q) - 1 - i)
        return obs

    def key(self):
        return (self.mode_key, tuple(self.board), tuple(self.queues[1]),
                tuple(self.queues[-1]), self.turn, self.moves, self.max_moves)

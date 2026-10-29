"""Single source of truth for gameplay, simulations and variant rules."""

from dataclasses import dataclass, field
import random
from typing import Dict, List, Tuple

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7),
         (2, 5, 8), (0, 4, 8), (2, 4, 6))
SWITCH_GAP = (4, 8)  # moves between random switching turns; the first lands after both own 2+ pieces


@dataclass(frozen=True)
class Mode:
    key: str
    title: str
    description: Tuple[str, ...]
    vanishing: bool = False
    gravity: bool = False
    blind: bool = False
    switch: str = ""  # "one": oldest pieces trade places, "nine": every piece changes owner
    clear_every: int = 0  # gravity: delete the bottom row after this many moves
    provisional: bool = False


MODES = {
    "vanishing": Mode("vanishing", "배니싱", (
        "한 사람당 말은 3개", "네 번째 착수 때", "가장 오래된 말 제거", "제거 후 세 칸이면 승리"), vanishing=True),
    "original": Mode("original", "오리지널", (
        "빈 칸에 번갈아 착수", "가로·세로·대각선", "세 칸을 이으면 승리", "판이 가득 차면 무승부")),
    "blind": Mode("blind", "블라인드", (
        "배니싱 기반 · 말 3개", "방금 둔 말만 3초 공개", "나머지 말은 계속 숨김", "말의 위치를 기억하세요"), vanishing=True, blind=True),
    "gravity": Mode("gravity", "그래비티", (
        "배니싱 기반 · 말 3개", "말이 세로줄 아래로 낙하", "말이 사라지면 위 말도 낙하", "6수마다 맨 아래줄 삭제"), vanishing=True, gravity=True, clear_every=6),
    "switch_one": Mode("switch_one", "원스위칭", (
        "배니싱 기반 · 말 3개", "무작위 턴이 오면", "수명이 같은 내 말과", "상대 말의 위치 교환"), vanishing=True, switch="one"),
    "switch_nine": Mode("switch_nine", "나인스위칭", (
        "배니싱 기반 · 말 3개", "무작위 턴이 오면", "판 위 모든 말의", "소유권이 한 번에 반전"), vanishing=True, switch="nine"),
}


def switch_schedule(max_moves: int, rng=random) -> Tuple[int, ...]:
    """Pre-draw the random switching turns so clones and AI search stay deterministic."""
    turns, at = [], 0
    while True:
        at += rng.randint(*SWITCH_GAP)
        if at > max_moves:
            return tuple(turns)
        turns.append(at)


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
    switch_turns: Tuple[int, ...] = None
    last_event: str = ""  # "switch" or "clear" when the latest move triggered one
    vanished: Tuple[int, ...] = ()  # (cell, mark) the latest move's vanishing rule removed
    fell: Tuple[Tuple[int, int], ...] = ()  # (from, to) cells of pieces that dropped after it
    drops: Tuple[Tuple[int, int], ...] = ()  # (from, to): row-clear shift and the new piece's drop

    def __post_init__(self):
        if self.mode_key not in MODES:
            raise ValueError("Unknown game mode: " + self.mode_key)
        if self.max_moves < 9:
            raise ValueError("max_moves must be at least 9")
        if self.switch_turns is None:
            self.switch_turns = switch_schedule(self.max_moves) if self.mode.switch else ()

    @property
    def mode(self) -> Mode:
        return MODES[self.mode_key]

    def clone(self):
        return Game(self.mode_key, self.max_moves, self.board.copy(),
                    {p: q.copy() for p, q in self.queues.items()}, self.turn,
                    self.moves, self.winner, self.done, self.last_action,
                    self.reason, self.winning_cells, self.switch_turns, self.last_event, self.vanished, self.fell, self.drops)

    def clear_due(self) -> bool:
        """Gravity deletes the bottom row right before every Nth move, so that move's piece survives."""
        return bool(self.mode.clear_every) and (self.moves + 1) % self.mode.clear_every == 0

    def nine_switch_due(self) -> bool:
        """Warn throughout the turn before all pieces change owner."""
        return not self.done and self.mode.switch == "nine" and self.moves + 1 in self.switch_turns

    def landing(self, action: int) -> int:
        if not isinstance(action, int) or not 0 <= action < 9 or self.done:
            raise ValueError("진행 중인 게임에서 1~9번 칸을 선택하세요")
        if self.mode.gravity:
            # Lands on the board as it will be once a due bottom-row clear has happened.
            board = [0, 0, 0] + self.board[:6] if self.clear_due() else self.board
            for row in (2, 1, 0):
                cell = row * 3 + action % 3
                if board[cell] == 0:
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

    def switch_pair(self):
        """Cells the coming move's one-switch will trade, known before that move is made.

        Only pieces showing the same lifetime when announced trade, shortest lifetime first.
        The mover's oldest piece is left out when it will vanish on the move itself.
        A pair that would leave the mover lost whatever they play is skipped; if every pair
        is like that, this turn has no switch.
        """
        if self.done or self.mode.switch != "one" or self.moves + 1 not in self.switch_turns:
            return None
        lives = self.lifetimes()
        mine, theirs = self.queues[self.turn], self.queues[-self.turn]
        if len(mine) == 3:
            mine = mine[1:]
        for a in mine:  # oldest first = shortest lifetime first
            for b in theirs:
                if lives[a] == lives[b] and self.switch_is_fair((a, b)):
                    return a, b
        return None

    def switch_is_fair(self, pair) -> bool:
        """True if some move keeps the mover from losing at the switch or on the next reply.

        ponytail: one-reply lookahead; deeper forced wins are ordinary tactics, not the switch's doing.
        """
        mover = self.turn
        for action in self.legal_actions():
            after = self.clone()
            after._play(action, pair)
            if after.done:
                if after.winner != -mover:
                    return True
                continue
            for reply in after.legal_actions():
                answer = after.clone()
                answer.play(reply)
                if answer.winner == -mover:
                    break
            else:
                return True
        return False

    def play(self, action: int) -> int:
        """Apply one legal move atomically; invalid input never loses a turn."""
        return self._play(action, self.switch_pair())

    def _play(self, action, pair):
        cell = self.landing(action)
        player = self.turn
        cleared = self.clear_due()
        drops = []
        if cleared:
            drops = [(a, a + 3) for a in range(6) if self.board[a]]
            self.clear_bottom_row()
        if self.mode.gravity and cell >= 3:
            drops.append((cell % 3, cell))  # enters at the top of its column
        self.drops = tuple(drops)
        self.board[cell] = player
        self.queues[player].append(cell)
        self.vanished, self.fell = (), ()
        if self.mode.vanishing and len(self.queues[player]) > 3:
            old = self.queues[player].pop(0)
            self.board[old] = 0
            self.vanished = (old, player)
        self.moves += 1
        self.last_action, self.last_event = cell, "clear" if cleared else ""
        if self.mode.gravity:
            self.settle()
        # A line made by the move itself wins before any switch;
        # a vanished piece letting a column fall can also complete the opponent's line.
        self.check_win(player, -player)
        if not self.done and self.moves in self.switch_turns:
            self.switch(player, pair)
            self.check_win(player, -player)
        if not self.done and all(self.board):
            self.done, self.reason = True, "full"
        if not self.done and self.moves >= self.max_moves:
            self.done, self.reason = True, "limit"
        self.turn = -player
        return cell

    def check_win(self, *players):
        for player in players:
            for line in LINES:
                if all(self.board[a] == player for a in line):
                    self.done, self.winner = True, player
                    self.reason, self.winning_cells = "win", line
                    return

    def switch(self, player, pair=None):
        """Lifetimes follow pieces because each queue keeps its order."""
        if self.mode.switch == "nine":
            self.board = [-mark for mark in self.board]
            self.queues = {1: self.queues[-1], -1: self.queues[1]}
        else:
            if pair is None:
                return
            a, b = pair
            mine, theirs = self.queues[player], self.queues[-player]
            i, j = mine.index(a), theirs.index(b)
            self.board[a], self.board[b] = self.board[b], self.board[a]
            mine[i], theirs[j] = b, a
        self.last_event = "switch"

    def settle(self):
        """Let pieces above an emptied cell fall, keeping each piece's queue slot."""
        moved = {}
        for col in range(3):
            stack = [r * 3 + col for r in (2, 1, 0) if self.board[r * 3 + col]]
            for row, old in zip((2, 1, 0), stack):
                moved[old] = row * 3 + col
        board = [0] * 9
        for old, new in moved.items():
            board[new] = self.board[old]
        self.board = board
        self.queues = {p: [moved[a] for a in q] for p, q in self.queues.items()}
        self.last_action = moved[self.last_action]
        self.fell = tuple((old, new) for old, new in moved.items() if old != new)

    def before_fall(self):
        """Board and lifetimes as they were before the latest drop, so the screen can show
        the vanishing piece fade out first and only then let the pieces above it fall."""
        board, lives = self.board.copy(), self.lifetimes()
        moved = [(old, self.board[new], lives.pop(new, None)) for old, new in self.fell]
        for _, new in self.fell:
            board[new] = 0
        for old, mark, life in moved:
            board[old] = mark
            if life is not None:
                lives[old] = life
        return board, lives

    def clear_bottom_row(self):
        """Drop every stack by one row; row 0 empties, so no new line can appear."""
        self.board = [0, 0, 0] + self.board[:6]
        self.queues = {p: [a + 3 for a in q if a < 6] for p, q in self.queues.items()}
        self.last_action = self.last_action + 3 if self.last_action < 6 else -1
        if self.vanished:
            cell, mark = self.vanished
            self.vanished = (cell + 3, mark) if cell < 6 else ()
        self.last_event = "clear"

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

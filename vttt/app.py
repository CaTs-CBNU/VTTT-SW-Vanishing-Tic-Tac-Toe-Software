"""State machine joining buttons, game rules, inference, screens and records."""

from concurrent.futures import ThreadPoolExecutor
import logging
import math
import random
import threading
import time

from .connectivity_ui import ConnectivityUI
from .lan import LanController
from .ai import GameAI
from .profile import Profile, THEMES
from .rules import Game, MODES
from .ui_render import SHOP_THEMES

LOG = logging.getLogger(__name__)
FLASH_SECONDS = 0.15  # pressed-button highlight
DROP_SECONDS = 0.35  # gravity pieces sliding down a row (distinct from the vanish fade)
FADE_SECONDS = 1.0
SWITCH_HOLD_SECONDS = 1.0  # begins after the placed-piece frame reaches the displays
SWITCH_FLIP_SECONDS = 0.5
GRAVITY_WARNING_SECONDS = 2.5
DUEL_STEP = 1.0  # 2-player RPS: "3", "2", "1", then a one-second "눌러!" window
DUEL_TOP = {3: 0, 2: 1, 1: 2}  # top player sees the row upside down: their left is button 3
DUEL_BOTTOM = {7: 0, 8: 1, 9: 2}  # scissors, rock, paper
FIXED_DIFFICULTY = {"original": "normal"}  # modes without a difficulty screen
MODE_BUTTONS = {4: "blind", 5: "vanishing", 6: "gravity", 7: "switch_nine", 8: "switch_one", 9: "original"}


class Application:
    def __init__(self, config, backend, renderer, ai=None, clock=time.monotonic):
        self.config, self.backend, self.renderer, self.clock = config, backend, renderer, clock
        self.profile = Profile(config["profile"], config)
        self.settings = self.profile.data["settings"]
        self.ai = ai if ai is not None else GameAI(config)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vttt-ai")
        self.future, self.cancel_event = None, None
        self.generation = 0
        self.screen, self.mode_key = "start", config["default_mode"]
        self.game, self.human_mark = None, 1
        self.running, self.closed = True, False
        self.revision, self.rendered_revision = 0, -1
        self.content_revision, self.presented_content = 0, -1
        self.ai_ready_at = 0.0
        self.fade, self.fade_step = None, 0
        self.motion, self.motion_frame = None, -1  # (start, drop_end, fade_end, fall_end)
        self.nine_switch = None
        self.gravity_warning = None
        self.accept_after = float("-inf")
        self.notice, self.notice_until = self.profile.warning, None
        self.return_screen, self.help_index = "menu", 0
        self.diagnostic_button = None
        self.last_coins, self.recorded = 0, False
        self.blind_visible, self.reveal_pending, self.result_pending = True, False, False
        self.reveal_until, self.result_at = None, None
        self.ai_after = 0
        self.lan = LanController(self)
        self.connectivity = ConnectivityUI(self)
        self.pending_difficulty = self.settings["difficulty"]
        self.rps_choice, self.rps_spin, self.rps_until = None, 0, 0.0
        self.rps_human_first = True
        self.flash, self.flash_until = (), 0.0
        self.duel_start, self.duel_phase = 0.0, -1
        self.duel_picks, self.duel_reason = {"top": None, "bottom": None}, ""
        self.shop_page, self.shop_selected = 0, None
        self.score_network = False
        self.input_epoch, self.presented_epoch = 0, -1

    def touch(self):
        self.revision += 1
        self.content_revision = self.revision

    def animate(self):
        """Redraw an animation frame without discarding clicks made while it was showing."""
        self.revision += 1

    def go(self, screen):
        self.input_epoch += 1
        self.screen, self.notice, self.notice_until = screen, "", None
        self.touch()

    def message(self, text):
        self.notice, self.notice_until = text, self.clock() + 2.0
        self.touch()

    def save_settings(self):
        try:
            self.profile.save()
        except OSError:
            LOG.exception("Cannot save local profile")
            self.message("설정을 저장하지 못했습니다")

    def toggle(self, key):
        if key == "human_first" and self.settings["opponent"] == "local":
            return
        if key in ("show_lifetime", "human_first"):
            self.settings[key] = not self.settings[key]
        elif key == "opponent":
            self.settings[key] = "local" if self.settings[key] == "ai" else "ai"
        self.save_settings()
        self.touch()

    def cancel_ai(self):
        self.generation += 1
        if self.cancel_event:
            self.cancel_event.set()
        if self.future:
            self.future.cancel()
        self.future = None

    def start_game(self):
        self.cancel_ai()
        self.game = Game(self.mode_key, self.config["max_moves"])
        forced = self.settings["human_first"] and self.settings["opponent"] == "ai"
        self.human_mark = 1 if forced or self.rps_human_first else -1
        self.local_first_mark = self.human_mark
        self.recorded, self.last_coins = False, 0
        self.blind_visible = True
        self.reveal_until = self.result_at = None
        self.reveal_pending = self.result_pending = False
        self.fade = self.motion = None
        self.nine_switch = None
        self.gravity_warning = None
        self.ai_after = self.clock() + 0.3
        self.go("game")

    def picks_difficulty(self):
        """Difficulty screen only against the AI, and not for modes with a fixed level."""
        return self.settings["opponent"] == "ai" and self.mode_key not in FIXED_DIFFICULTY

    def begin_match(self):
        """Two players always play RPS; against the AI the 선공 setting can skip it."""
        self.cancel_ai()
        if self.settings["opponent"] == "local":
            self.start_duel(self.clock())
            self.go("duel")
        elif self.settings["human_first"]:
            self.start_game()
        else:
            self.rps_choice = None
            self.go("rps")

    def start_duel(self, at):
        self.duel_start, self.duel_phase = at, -1
        self.duel_picks, self.duel_reason = {"top": None, "bottom": None}, ""

    def duel_window_open(self):
        return self.screen == "duel" and self.duel_phase == 3

    def resolve_duel(self):
        top, bottom = self.duel_picks["top"], self.duel_picks["bottom"]
        if top == bottom:  # same hand, or nobody pressed
            self.message("둘 다 안 눌렀어요 · 다시!" if top is None else "비겼어요 · 다시!")
            self.start_duel(self.clock() + 1.2)  # keep both hands visible a moment
            self.touch()
            return
        if top is None or bottom is None:
            bottom_wins = top is None
            self.duel_reason = ("위쪽" if top is None else "아래쪽") + "이 늦었어요"
        else:
            bottom_wins = (bottom - top) % 3 == 1
        self.rps_human_first = bottom_wins
        self.rps_until = self.clock() + 1.5
        self.go("duel_result")

    def is_ai_turn(self):
        return bool(not self.lan.active and self.game and not self.game.done and self.settings["opponent"] == "ai"
                    and self.game.turn != self.human_mark)

    def result_title(self):
        if self.game.winner == 0:
            return "무승부"
        if self.lan.active:
            return "내 승리!" if self.game.winner == self.human_mark else "상대 승리!"
        if self.settings["opponent"] == "ai":
            return "이겼어요!" if self.game.winner == self.human_mark else "AI가 이겼어요"
        return "승리!"

    def gravity_warning_waiting(self):
        warning = self.gravity_warning
        return warning is not None and (warning["shown_at"] is None or
                self.clock() - warning["shown_at"] < GRAVITY_WARNING_SECONDS)

    def make_move(self, action):
        if self.nine_switch is not None:
            return False
        if self.gravity_warning_waiting():
            if self.gravity_warning["action"] is not None:
                return False
            try:
                self.game.landing(action)
            except ValueError as exc:
                self.message(str(exc))
                return False
            # Remember the first click without erasing the warning early.
            self.gravity_warning["action"] = action
            return True
        if self.gravity_warning is not None and self.gravity_warning["action"] is not None:
            action = self.gravity_warning["action"]
        try:
            self.game.play(action)
        except ValueError as exc:
            self.message(str(exc))
            return False
        self.notice, self.notice_until = "", None
        self.gravity_warning = ({"shown_at": None, "action": None}
                                if not self.game.done and self.game.clear_due() else None)
        event = self.game.last_event
        if event == "switch" and self.game.mode.switch == "nine":
            # Rules and AI retain an atomic move; presentation first shows the
            # completed placement before ownership was inverted.
            self.nine_switch = {"board": [-mark for mark in self.game.board],
                                "phase": "placed", "shown_at": None, "progress": 0.0}
        elif event and not self.game.done:
            self.message({"clear": "아래줄 삭제!", "switch": "소유권 반전!" if self.game.mode.switch == "nine" else "위치 교환!"}[event])
        elif self.game.switch_pair():
            self.message("다음 수 후 위치 교환!")
        self.blind_visible = True
        self.reveal_pending = self.game.mode.blind and not self.game.done
        self.reveal_until = None
        self.ai_after = self.clock() + 0.3
        self.ai_ready_at = self.clock() + self.config["ai_move_seconds"]
        now, game = self.clock(), self.game
        drop_end = now + (DROP_SECONDS if game.drops else 0)
        fade_end = drop_end + (FADE_SECONDS if game.vanished else 0)
        fall_end = fade_end + (DROP_SECONDS if game.fell else 0)
        self.motion = (now, drop_end, fade_end, fall_end) if fall_end > now else None
        self.motion_frame = -1
        self.fade, self.fade_step = ((*game.vanished, drop_end) if game.vanished else None), 0
        self.touch()
        if self.game.done:
            self.result_pending = True
            if not self.recorded and not self.lan.active:
                self.recorded = True
                try:
                    difficulty = FIXED_DIFFICULTY.get(self.game.mode_key, self.settings["difficulty"])
                    self.last_coins = self.profile.record(self.game, self.settings["opponent"], self.human_mark, difficulty)
                except OSError:
                    LOG.exception("Cannot save match result")
                    self.message("결과 저장 실패")
        return True

    def open_help(self, return_screen, current_mode=False):
        self.return_screen = return_screen
        self.help_index = list(MODES).index(self.mode_key) + 1 if current_mode else 0
        self.go("help")

    def handle(self, event):
        if event.kind == "quit":
            self.running = False
            return
        if event.timestamp and event.timestamp <= self.accept_after:
            return
        if self.lan.handle(event):
            return
        if self.screen == "game" and self.nine_switch is not None:
            return
        button = event.button
        if 1 <= button <= 9:
            cells = (button,)
            if self.duel_window_open():  # light the whole row so the hand chosen stays secret
                cells = (1, 2, 3) if button <= 3 else (7, 8, 9) if button >= 7 else cells
            self.flash, self.flash_until = cells, self.clock() + FLASH_SECONDS
            self.animate()
        if self.connectivity.handle(event):
            return
        if event.kind == "long" and button == 5:
            if self.screen == "game" and not self.game.done:
                self.cancel_ai()
                self.go("pause")
            elif self.screen == "pause":
                self.resume()
            elif self.screen == "diagnostic":
                self.go("settings")
            elif self.screen == "start":
                self.running = False
            return
        if event.kind != "short":
            return
        if self.screen == "start":
            if button == 8:
                self.go("menu")
        elif self.screen == "menu":
            pages = {2: "shop", 4: "scores", 5: "mode", 6: "settings", 8: "communication"}
            if button in pages:
                self.return_screen = "menu"
                self.go(pages[button])
        elif self.screen == "mode":
            if button == 1:
                self.go("menu")
            elif button == 3:
                self.return_screen = "mode"
                self.go("themes")
            elif button in MODE_BUTTONS:
                self.mode_key = MODE_BUTTONS[button]
                self.pending_difficulty = self.settings["difficulty"]
                if not self.picks_difficulty():
                    self.begin_match()
                else:
                    self.go("setup")
        elif self.screen == "setup":
            if button == 1:
                self.go("mode")
            elif button in (4, 5, 6):
                self.pending_difficulty = {4: "easy", 5: "normal", 6: "hard"}[button]
                self.touch()
            elif button == 7:
                self.pending_difficulty = None
                self.touch()
            elif button == 8:
                if self.pending_difficulty is None:
                    self.message("난이도를 선택해주세요")
                else:
                    self.settings["difficulty"] = self.pending_difficulty
                    self.save_settings()
                    self.begin_match()
        elif self.screen == "rps":
            if button == 1:
                self.go("setup" if self.picks_difficulty() else "mode")
            elif button in (7, 8, 9):
                human = button - 7  # scissors, rock, paper
                other = random.randrange(3)
                self.rps_choice = other
                if human == other:
                    self.rps_until = self.clock() + 1.2  # hold the AI's hand, then spin again
                    self.message("무승부 · 다시 선택해주세요")
                else:
                    self.rps_human_first = (human - other) % 3 == 1
                    self.rps_until = self.clock() + 1.2
                    self.go("rps_result")
        elif self.screen == "duel":
            if button == 4:
                self.go("setup" if self.picks_difficulty() else "mode")
            elif self.duel_window_open():
                for row, hands in (("top", DUEL_TOP), ("bottom", DUEL_BOTTOM)):
                    if button in hands and self.duel_picks[row] is None:
                        self.duel_picks[row] = hands[button]
                if None not in self.duel_picks.values():
                    self.resolve_duel()
        elif self.screen in ("rps_result", "duel_result"):
            pass
        elif self.screen == "game":
            if not self.game.done and not self.is_ai_turn():
                if not (self.game.mode.blind and self.reveal_until is not None):
                    self.make_move(button - 1)
        elif self.screen == "pause":
            if button == 4:
                self.cancel_ai()
                self.go("menu")
            elif button == 5:
                self.resume()
            elif button == 6:
                self.begin_match()
            elif button == 8:
                self.running = False
        elif self.screen == "result":
            if button == 4:
                self.begin_match()
            elif button == 6:
                self.go("mode")
            elif button == 7:
                self.go("final_board")
            elif button == 8:
                self.go("menu")
        elif self.screen == "final_board":
            self.go("result")
        elif self.screen in ("shop", "themes"):
            if button == 1:
                self.go(self.return_screen)
            elif button in (7, 9):
                pages = len(SHOP_THEMES)
                self.shop_page = (self.shop_page + (-1 if button == 7 else 1)) % pages
                self.shop_selected = None
                self.touch()
            elif button in (4, 5, 6):
                index = (self.shop_page + button - 4) % len(SHOP_THEMES)
                if index < len(SHOP_THEMES):
                    self.shop_selected = SHOP_THEMES[index]
                    self.touch()
            elif button == 8 and self.shop_selected:
                try:
                    self.message(self.profile.buy_or_select(self.shop_selected))
                except OSError:
                    LOG.exception("Cannot save theme")
                    self.message("테마 저장 실패")
        elif self.screen == "settings":
            if button == 1:
                self.go("menu")
            elif button in (4, 6, 7):
                self.toggle({4: "opponent", 6: "show_lifetime", 7: "human_first"}[button])
            elif button == 8:
                self.open_help("settings")
            elif button == 9:
                self.go("diagnostic")
        elif self.screen == "diagnostic":
            self.diagnostic_button = button
            LOG.info("Button %s received", button)
            self.touch()
        elif self.screen == "scores":
            if button == 1:
                self.go("menu")
            elif button == 9:
                self.score_network = not self.score_network
                self.touch()
        elif self.screen == "help":
            if button == 1:
                self.go(self.return_screen)
            elif button in (7, 9):
                self.help_index = (self.help_index + (1 if button == 9 else -1)) % 7
                self.touch()

    def resume(self):
        if self.gravity_warning is not None:
            self.gravity_warning["shown_at"] = None
        if self.game.mode.blind:
            # Pausing must not grant a fresh reveal of the hidden board.
            self.blind_visible = False
            self.reveal_until = None
            self.reveal_pending = False
        self.ai_after = self.clock() + 0.3
        self.go("game")

    def tick(self):
        now = self.clock()
        self.connectivity.tick()
        self.lan.tick()
        if self.lan.reconnecting:
            return
        if self.flash and now >= self.flash_until:
            self.flash = ()
            self.animate()
        if self.screen in ("rps_result", "duel_result") and now >= self.rps_until:
            self.start_game()
        if self.screen == "duel":
            phase = min(4, math.floor((now - self.duel_start) / DUEL_STEP))
            if phase != self.duel_phase:
                if phase == 0:
                    self.duel_picks = {"top": None, "bottom": None}
                self.duel_phase = phase
                self.animate()
                if phase == 4:
                    self.resolve_duel()
        if self.screen == "rps":
            if self.rps_choice is not None and now >= self.rps_until:
                self.rps_choice = None
                self.touch()
            step = int(now * 5) % 3  # scissors -> rock -> paper every 0.2 s
            if self.rps_choice is None and step != self.rps_spin:
                self.rps_spin = step
                self.animate()
        if self.notice_until is not None and now >= self.notice_until:
            self.notice, self.notice_until = "", None
            self.touch()
        if self.screen != "game":
            return
        if self.nine_switch is not None:
            animation = self.nine_switch
            shown_at = animation["shown_at"]
            if shown_at is not None:
                elapsed = now - shown_at
                if animation["phase"] == "placed" and elapsed >= SWITCH_HOLD_SECONDS:
                    animation.update(phase="switching", shown_at=None)
                    self.touch()
                elif animation["phase"] == "switching":
                    if elapsed >= SWITCH_FLIP_SECONDS / 4:
                        if animation["progress"] >= 0.75:
                            self.nine_switch = None
                            self.message("소유권 반전!")
                        else:
                            animation["progress"] += 0.25
                            animation["shown_at"] = None
                            self.touch()
            # Do not place another move, start AI work or advance a result
            # until the completed switch frame has been presented.
            if self.fade:
                self.fade_step = min(5, max(0, int((now - self.fade[2]) / 0.2)))
                if self.fade_step == 5:
                    self.fade = None
                self.animate()
            return
        if self.motion:
            if now >= self.motion[3]:
                self.motion = None
                self.animate()
            else:
                frame = int((now - self.motion[0]) / 0.05)
                if frame != self.motion_frame:
                    self.motion_frame = frame
                    self.animate()
        if self.fade:
            step = min(5, max(0, int((now - self.fade[2]) / 0.2)))  # five frames over one second
            if step != self.fade_step:
                self.fade_step = step
                if step == 5:
                    self.fade = None
                self.animate()
        if self.game.done:
            if self.result_at is not None and now >= self.result_at:
                self.go("result")
            return
        if self.gravity_warning_waiting():
            return
        if self.gravity_warning is not None and self.gravity_warning["action"] is not None:
            self.make_move(self.gravity_warning["action"])
            return
        if self.reveal_until is not None and now >= self.reveal_until:
            self.reveal_until = None
            self.blind_visible = False
            self.touch()
        # The AI may think during the pause, but its move lands only after it.
        waiting = self.reveal_pending or self.reveal_until is not None or now < self.ai_ready_at
        if self.is_ai_turn():
            if self.future is not None and self.future.done():
                if waiting:
                    return
                task, self.future = self.future, None
                try:
                    generation, action = task.result()
                    if generation == self.generation:
                        self.make_move(action)
                except Exception:
                    LOG.exception("AI inference failed; retrying with rule search")
                    self.ai.network, self.ai.status = None, "탐색 AI"
                    self.message("AI 재시도 중")
                    self.ai_after = now + 0.5
            elif self.future is None and now >= self.ai_after:
                snapshot, generation = self.game.clone(), self.generation
                cancel = self.cancel_event = threading.Event()
                difficulty = FIXED_DIFFICULTY.get(self.game.mode_key, self.settings["difficulty"])

                def compute():
                    return generation, self.ai.select_action(snapshot, difficulty, cancel)

                self.future = self.executor.submit(compute)

    def present(self):
        if self.rendered_revision == self.revision:
            return
        if hasattr(self.backend, "set_input_context"):
            self.backend.set_input_context(self.screen)
        self.backend.show(self.renderer.draw(self))
        self.lan.presented()
        now = self.clock()
        # Ignore stale clicks collected during the previous screen's SPI transfer.
        if self.presented_epoch != self.input_epoch or (
                self.screen not in ("wifi_scan", "wifi_password") and self.content_revision != self.presented_content):
            self.accept_after = now
            self.presented_epoch = self.input_epoch
        self.presented_content = self.content_revision
        self.rendered_revision = self.revision
        if self.screen == "game":
            if self.gravity_warning is not None and self.gravity_warning["shown_at"] is None:
                self.gravity_warning["shown_at"] = now
            if self.nine_switch is not None:
                if self.nine_switch["shown_at"] is None:
                    self.nine_switch["shown_at"] = now
                return
            if self.reveal_pending:
                self.reveal_pending = False
                self.reveal_until = now + self.config["blind_reveal_seconds"]
            if self.result_pending:
                self.result_pending = False
                self.result_at = now + 2.0

    def run(self):
        try:
            while self.running:
                for event in self.backend.poll():
                    old_revision = self.content_revision
                    self.handle(event)
                    if self.content_revision != old_revision or not self.running:
                        break
                if not self.running:
                    break
                self.tick()
                if self.running:
                    self.present()
                time.sleep(0.01)
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_ai()
        self.connectivity.forget()
        self.connectivity.close()
        self.lan.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.backend.close()

"""State machine joining buttons, game rules, inference, screens and records."""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time

from .connectivity_ui import ConnectivityUI
from .ai import GameAI
from .profile import Profile, THEMES
from .rules import Game, MODES
from .ui_render import SHOP_THEMES

LOG = logging.getLogger(__name__)
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
        self.accept_after = float("-inf")
        self.notice, self.notice_until = self.profile.warning, None
        self.return_screen, self.help_index = "menu", 0
        self.diagnostic_button = None
        self.last_coins, self.recorded = 0, False
        self.blind_visible, self.reveal_pending, self.result_pending = True, False, False
        self.reveal_until, self.result_at = None, None
        self.ai_after = 0
        self.connectivity = ConnectivityUI(self)
        self.pending_difficulty = self.settings["difficulty"]
        self.rps_choice = None
        self.shop_page, self.shop_selected = 0, None
        self.input_epoch, self.presented_epoch = 0, -1

    def touch(self):
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
        if key in ("show_lifetime", "human_first"):
            self.settings[key] = not self.settings[key]
        elif key == "opponent":
            self.settings[key] = "local" if self.settings[key] == "ai" else "ai"
        elif key == "difficulty":
            choices = ("easy", "normal", "hard")
            self.settings[key] = choices[(choices.index(self.settings[key]) + 1) % 3]
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
        self.human_mark = 1 if self.settings["human_first"] else -1
        self.local_first_mark = self.human_mark
        self.recorded, self.last_coins = False, 0
        self.blind_visible = True
        self.reveal_until = self.result_at = None
        self.reveal_pending = self.result_pending = False
        self.ai_after = self.clock() + 0.3
        self.go("game")

    def is_ai_turn(self):
        return bool(self.game and not self.game.done and self.settings["opponent"] == "ai"
                    and self.game.turn != self.human_mark)

    def result_title(self):
        if self.game.winner == 0:
            return "무승부"
        if self.settings["opponent"] == "ai":
            return "사람 승리!" if self.game.winner == self.human_mark else "AI 승리!"
        return ("1P" if self.game.winner == self.local_first_mark else "2P") + (" O 승리!" if self.game.winner == 1 else " X 승리!")

    def make_move(self, action):
        try:
            self.game.play(action)
        except ValueError as exc:
            self.message(str(exc))
            return False
        self.notice, self.notice_until = "", None
        self.blind_visible = True
        self.reveal_pending = self.game.mode.blind and not self.game.done
        self.reveal_until = None
        self.ai_after = self.clock() + 0.3
        self.touch()
        if self.game.done:
            self.result_pending = True
            if not self.recorded:
                self.recorded = True
                try:
                    self.last_coins = self.profile.record(self.game, self.settings["opponent"], self.human_mark)
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
        button = event.button
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
                    self.rps_choice = None
                    self.go("rps")
        elif self.screen == "rps":
            if button == 1:
                self.go("setup")
            elif button in (7, 8, 9):
                import random
                human = button - 7  # scissors, rock, paper
                other = random.randrange(3)
                self.rps_choice = other
                if human == other:
                    self.message("무승부 · 다시 선택해주세요")
                else:
                    self.settings["human_first"] = (human - other) % 3 == 1
                    self.save_settings()
                    self.rps_until = self.clock() + 1.2
                    self.go("rps_result")
        elif self.screen == "rps_result":
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
                self.start_game()
            elif button == 8:
                self.running = False
        elif self.screen == "result":
            if button == 4:
                self.start_game()
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
            elif button in (4, 5, 6, 7):
                self.toggle({4: "opponent", 5: "difficulty", 6: "show_lifetime", 7: "human_first"}[button])
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
        elif self.screen == "help":
            if button == 1:
                self.go(self.return_screen)
            elif button in (7, 9):
                self.help_index = (self.help_index + (1 if button == 9 else -1)) % 7
                self.touch()

    def resume(self):
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
        if self.screen == "rps_result" and now >= self.rps_until:
            self.start_game()
        if self.notice_until is not None and now >= self.notice_until:
            self.notice, self.notice_until = "", None
            self.touch()
        if self.screen != "game":
            return
        if self.game.done:
            if self.result_at is not None and now >= self.result_at:
                self.go("result")
            return
        if self.reveal_until is not None:
            if now < self.reveal_until:
                return
            self.reveal_until = None
            self.blind_visible = False
            self.touch()
        if self.is_ai_turn() and not self.reveal_pending:
            if self.future is not None and self.future.done():
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
                difficulty = self.settings["difficulty"]

                def compute():
                    return generation, self.ai.select_action(snapshot, difficulty, cancel)

                self.future = self.executor.submit(compute)

    def present(self):
        if self.rendered_revision == self.revision:
            return
        if hasattr(self.backend, "set_input_context"):
            self.backend.set_input_context(self.screen)
        self.backend.show(self.renderer.draw(self))
        now = self.clock()
        # Ignore stale clicks collected during the previous screen's SPI transfer.
        if self.presented_epoch != self.input_epoch or self.screen not in ("wifi_scan", "wifi_password"):
            self.accept_after = now
            self.presented_epoch = self.input_epoch
        self.rendered_revision = self.revision
        if self.screen == "game":
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
                    old_revision = self.revision
                    self.handle(event)
                    if self.revision != old_revision or not self.running:
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
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.backend.close()

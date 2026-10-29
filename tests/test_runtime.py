"""Behavior checks for the physical game's rules, controls, AI and persistence."""

import json
from pathlib import Path
import random
import tempfile
import time
import unittest

from vttt.ai import GameAI
from vttt.app import Application, MODE_BUTTONS
from vttt.backends import HeadlessBackend, split_frame
from vttt.buttons import ButtonEvent, ButtonFilter
from vttt.config import hardware_config, runtime_config
from vttt.profile import Profile
from vttt.rules import Game, MODES


class RuleTests(unittest.TestCase):
    def test_vanishing_removes_oldest_before_win(self):
        game = Game()
        for action in (0, 3, 1, 4, 8, 6, 2):
            game.play(action)
        self.assertEqual(game.board, [0, 1, 1, -1, -1, 0, -1, 0, 1])
        self.assertFalse(game.done)
        self.assertEqual(game.queues[1], [1, 8, 2])
        self.assertEqual({a: game.lifetimes()[a] for a in (1, 8, 2)}, {1: 1, 8: 2, 2: 3})

    def test_invalid_input_does_not_change_turn_or_state(self):
        game = Game()
        game.play(0)
        before = game.key()
        for invalid in (0, -1, 9, 100):
            with self.assertRaises(ValueError):
                game.play(invalid)
            self.assertEqual(game.key(), before)

    def test_original_win_and_draw(self):
        game = Game("original")
        for a in (0, 3, 1, 4, 2):
            game.play(a)
        self.assertEqual(game.winner, 1)
        self.assertEqual(game.winning_cells, (0, 1, 2))
        self.assertEqual(game.legal_actions(), [])
        draw = Game("original")
        for a in (0, 1, 2, 4, 3, 5, 7, 6, 8):
            draw.play(a)
        self.assertTrue(draw.done)
        self.assertEqual((draw.winner, draw.reason), (0, "full"))

    def test_all_eight_straight_lines_win_and_bent_lines_do_not(self):
        for cells in ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)):
            game=Game("original")
            game.board=[1 if i in cells else 0 for i in range(9)]
            last=cells[-1];game.board[last]=0;game.queues[1]=list(cells[:-1])
            game.play(last)
            self.assertEqual(game.winner,1,cells)
        for cells in ((0,5,6),(2,3,8)):
            game=Game("original")
            game.board=[1 if i in cells[:-1] else 0 for i in range(9)]
            game.queues[1]=list(cells[:-1]);game.play(cells[-1])
            self.assertFalse(game.done,cells)

    def test_gravity_clicks_drop_in_column(self):
        game = Game("gravity")
        self.assertEqual(game.play(0), 6)
        self.assertEqual(game.play(6), 3)
        self.assertEqual(game.play(3), 0)
        before = game.key()
        with self.assertRaises(ValueError):
            game.play(6)
        self.assertEqual(game.key(), before)

    def test_variant_modes_all_use_vanishing(self):
        for mode in ("blind", "gravity", "switch_one", "switch_nine"):
            game = Game(mode, switch_turns=())
            for a in (0, 1, 2, 3, 4, 5, 6):
                game.play(game.legal_actions()[0] if mode == "gravity" else a)
            self.assertEqual(len(game.queues[1]), 3, mode)
            self.assertEqual(game.board.count(1), 3, mode)

    def test_gravity_vanished_piece_lets_column_fall(self):
        game = Game("gravity")
        game.board = [0, 0, 1, -1, 0, -1, 1, 1, -1]
        game.queues = {1: [6, 7, 2], -1: [3, 8, 5]}
        game.moves = 6
        game.play(0)  # O lands on top of column 0, its oldest piece (6) vanishes underneath
        self.assertEqual(game.board, [0, 0, 1, 1, 0, -1, -1, 1, -1])
        self.assertEqual(game.queues, {1: [7, 2, 3], -1: [6, 8, 5]})
        self.assertEqual(game.last_action, 3)
        self.assertFalse(game.done)

    def test_vanished_piece_is_reported_for_the_fade(self):
        game = Game()
        for a in (0, 3, 1, 4, 8, 6):
            game.play(a)
            self.assertEqual(game.vanished, ())
        game.play(2)
        self.assertEqual(game.vanished, (0, 1))
        self.assertEqual(game.clone().vanished, (0, 1))
        game.play(5)
        self.assertEqual(game.vanished, (3, -1))

    def test_gravity_clear_never_deletes_the_piece_just_placed(self):
        rng = random.Random(1)
        clears = 0
        for _ in range(300):
            game = Game("gravity", max_moves=60)
            while not game.done:
                mover = game.turn
                game.play(rng.choice(game.legal_actions()))
                clears += game.last_event == "clear"
                self.assertEqual(game.board[game.last_action], mover)
        self.assertGreater(clears, 300)

    def test_gravity_shows_the_vanish_before_the_fall(self):
        # Reported game: 1P/2P alternate on buttons 5 5 4 4 1 2 9 6.
        game = Game("gravity")
        for button in (5, 5, 4, 4, 1, 2, 9):
            game.play(button - 1)
        game.play(6 - 1)
        self.assertEqual(game.vanished, (7, -1))  # X's oldest, on button 8
        self.assertEqual(game.fell, ((4, 7),))  # the X on button 5 dropped into its place
        board, lives = game.before_fall()
        self.assertEqual((board[4], board[7]), (-1, 0))
        self.assertEqual(lives[4], game.lifetimes()[7])
        self.assertNotIn(7, lives)
        for _ in range(100):  # every drop can be undone for display
            game = Game("gravity", max_moves=40)
            rng = random.Random(len(_ * "x"))
            while not game.done:
                game.play(rng.choice(game.legal_actions()))
                board, _lives = game.before_fall()
                self.assertEqual(sorted(board), sorted(game.board))

    def test_gravity_countdown_colour_turns_red(self):
        from vttt.render import countdown_color
        self.assertEqual(countdown_color(6, 6), (0x76, 0x71, 0x6D))
        self.assertEqual(countdown_color(1, 6), (0xE5, 0x38, 0x3B))
        reds = [countdown_color(left, 6)[0] for left in range(6, 0, -1)]
        self.assertEqual(reds, sorted(reds))

    def test_gravity_clears_bottom_row_every_six_moves(self):
        game = Game("gravity")
        for a in (0, 1, 2, 0, 1):
            game.play(a)
        self.assertEqual(game.board, [0, 0, 0, -1, 1, 0, 1, -1, 1])
        self.assertTrue(game.clear_due())
        game.play(2)  # bottom row is deleted first, then the sixth piece drops onto the cleared board
        self.assertEqual(game.last_event, "clear")
        self.assertEqual(game.board, [0, 0, 0, 0, 0, 0, -1, 1, -1])
        self.assertEqual(game.queues, {1: [7], -1: [6, 8]})
        self.assertEqual(game.last_action, 8)
        self.assertFalse(game.done)

    def test_one_switching_pairs_pieces_showing_the_same_lifetime(self):
        # O plays buttons 5, 4, 7 and X plays 1, 6, 9: lifetimes 5=1 4=2 7=3 / 1=1 6=2 9=3.
        game = Game("switch_one", switch_turns=(7,))
        for a in (4, 0, 3, 5, 6, 8):
            game.play(a)
        # O's 5 vanishes on O's own move, so 4<->6 is the shortest pair that can trade.
        self.assertEqual(game.switch_pair(), (3, 5))
        game.play(2)
        self.assertEqual(game.last_event, "switch")
        self.assertEqual(game.queues, {1: [5, 6, 2], -1: [0, 3, 8]})
        self.assertEqual((game.board[3], game.board[5]), (-1, 1))

    def test_one_switching_without_vanishing_can_trade_the_oldest_pair(self):
        game = Game("switch_one", switch_turns=(4,))
        for a in (0, 8, 1):  # O 0(2) 1(3) ; X 8(3)  -> X moves next, no vanish
            game.play(a)
        self.assertEqual(game.switch_pair(), (8, 1))
        game.play(7)
        self.assertEqual(game.queues, {1: [0, 8], -1: [1, 7]})

    def test_one_switching_preview_matches_the_actual_swap(self):
        rng = random.Random(7)
        switches = 0
        for _ in range(200):
            game = Game("switch_one", max_moves=60)
            while not game.done:
                pair = game.switch_pair()
                before, lives_before = game.board.copy(), game.lifetimes()
                game.play(rng.choice(game.legal_actions()))
                if game.last_event == "switch":
                    switches += 1
                    a, b = pair
                    self.assertEqual((game.board[a], game.board[b]), (before[b], before[a]))
                    self.assertEqual(before[a], -before[b])
                    self.assertEqual(lives_before[a], lives_before[b])
                elif not game.done:
                    self.assertIsNone(pair)
        self.assertGreater(switches, 100)

    def test_one_switching_never_forces_the_mover_to_lose(self):
        game = Game("switch_one", switch_turns=(6,))
        for a in (8, 0, 1, 4, 2):
            game.play(a)
        # Swapping X's 0 with O's 8 would hand O the line 0-1-2 whatever X plays.
        self.assertFalse(game.switch_is_fair((0, 8)))
        a, b = game.switch_pair()
        self.assertEqual(game.lifetimes()[a], game.lifetimes()[b])
        for action in game.legal_actions():
            after = game.clone()
            after.play(action)
            self.assertNotEqual(after.winner, 1, action)

    def test_one_switching_is_skipped_when_every_pair_is_unfair(self):
        game = Game("switch_one", switch_turns=(6,))
        game.board = [-1, 1, 1, 0, 0, -1, 0, 0, 1]
        game.queues = {1: [2, 8, 1], -1: [0, 5]}
        game.moves, game.turn = 5, -1
        self.assertFalse(game.switch_is_fair((0, 8)))  # both showing lifetime 2
        self.assertFalse(game.switch_is_fair((5, 1)))  # both showing lifetime 3
        self.assertIsNone(game.switch_pair())
        game.play(3)
        self.assertEqual(game.last_event, "")

    def test_random_one_switch_games_never_lose_by_the_switch_alone(self):
        rng = random.Random(3)
        checked = 0
        for _ in range(150):
            game = Game("switch_one", max_moves=60)
            while not game.done:
                pair = game.switch_pair()
                if pair:
                    checked += 1
                    mover = game.turn
                    survivors = []
                    for action in game.legal_actions():
                        after = game.clone()
                        after.play(action)
                        if after.winner == -mover:
                            continue
                        if after.done or not any(
                                (lambda g: (g.play(r), g.winner)[1])(after.clone()) == -mover
                                for r in after.legal_actions()):
                            survivors.append(action)
                    self.assertTrue(survivors, (game.board, game.queues, pair))
                game.play(rng.choice(game.legal_actions()))
        self.assertGreater(checked, 50)

    def test_nine_switching_flips_every_owner(self):
        game = Game("switch_nine", switch_turns=(5,))
        for a in (0, 3, 1, 4, 8):
            game.play(a)
        self.assertEqual(game.board, [-1, -1, 0, 1, 1, 0, 0, 0, -1])
        self.assertEqual(game.queues, {1: [3, 4], -1: [0, 1, 8]})
        self.assertEqual(game.turn, -1)
        self.assertFalse(game.done)

    def test_move_that_wins_is_not_undone_by_switch(self):
        game = Game("switch_nine", switch_turns=(5,))
        for a in (0, 3, 1, 4, 2):
            game.play(a)
        self.assertEqual((game.winner, game.last_event), (1, ""))

    def test_switch_schedule_is_shared_by_clones(self):
        game = Game("switch_one")
        self.assertTrue(game.switch_turns)
        self.assertGreaterEqual(game.switch_turns[0], 4)
        self.assertEqual(game.clone().switch_turns, game.switch_turns)
        self.assertEqual(Game("vanishing").switch_turns, ())

    def test_all_modes_terminate_and_preserve_piece_invariants(self):
        rng = random.Random(42)
        for mode in MODES:
            for _ in range(20):
                game = Game(mode, max_moves=60)
                while not game.done:
                    game.play(rng.choice(game.legal_actions()))
                    for player in (1, -1):
                        self.assertEqual(set(game.queues[player]), {a for a, p in enumerate(game.board) if p == player})
                        if game.mode.vanishing:
                            self.assertLessEqual(len(game.queues[player]), 3)
                    if game.mode.gravity:
                        for a in range(6):
                            self.assertTrue(game.board[a + 3] or not game.board[a], (mode, game.board))
                self.assertLessEqual(game.moves, 60)


class ButtonTests(unittest.TestCase):
    def test_bounce_emits_one_click_on_release(self):
        f = ButtonFilter()
        events = []
        for t, pressed in ((0, False), (.01, True), (.02, False), (.03, True), (.08, True),
                           (.10, False), (.11, True), (.12, False), (.17, False), (.3, False)):
            events += f.feed(1, pressed, t)
        self.assertEqual([(e.button, e.kind) for e in events], [(1, "short")])

    def test_long_center_never_emits_a_short_click(self):
        f = ButtonFilter()
        events = []
        for t, pressed in ((0, False), (.1, True), (.15, True), (1.5, True), (1.6, False), (1.65, False)):
            events += f.feed(5, pressed, t)
        self.assertEqual([e.kind for e in events], ["long"])

    def test_held_at_start_must_be_released(self):
        f = ButtonFilter()
        self.assertEqual(f.feed(8, True, 0), [])
        self.assertEqual(f.feed(8, False, 1), [])
        self.assertEqual(f.feed(8, False, 1.1), [])

    def test_release_keeps_press_start_for_screen_transition_filter(self):
        f = ButtonFilter()
        f.feed(8, False, 0)
        f.feed(8, True, .1)
        f.feed(8, True, .15)
        f.feed(8, False, 3)
        events = f.feed(8, False, 3.1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].timestamp, .15)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = runtime_config()
        cfg["profile"] = str(Path(self.tmp.name) / "profile.json")
        self.now = [10.0]
        self.backend = HeadlessBackend()

        class BlankRenderer:
            def draw(self, app):
                from PIL import Image
                return Image.new("RGB", (720, 720), "white")

        self.app = Application(cfg, self.backend, BlankRenderer(), ai=GameAI(), clock=lambda: self.now[0])

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def press(self, button, kind="short"):
        self.app.handle(ButtonEvent(button, kind))

    def test_start_menu_modes_and_return_routes(self):
        self.press(8)
        self.assertEqual(self.app.screen, "menu")
        self.press(5)
        self.assertEqual(self.app.screen, "mode")
        for button, mode in MODE_BUTTONS.items():
            self.press(button)
            if mode == "original":  # no difficulty screen
                self.assertEqual((self.app.screen, self.app.mode_key), ("rps", mode))
                self.press(1)
                self.assertEqual(self.app.screen, "mode")
                continue
            self.assertEqual((self.app.screen, self.app.mode_key), ("setup", mode))
            self.press(8)
            self.assertEqual(self.app.screen, "rps")
            self.press(1)
            self.assertEqual(self.app.screen, "setup")
            self.press(1)
        self.press(1)
        self.press(2)
        self.assertEqual(self.app.screen, "shop")
        self.press(1)
        self.assertEqual(self.app.screen, "menu")

    def test_long_press_pauses_without_placing_and_result_saved_once(self):
        app = self.app
        app.mode_key, app.settings["opponent"] = "original", "local"
        app.start_game()
        self.press(5, "long")
        self.assertEqual((app.screen, app.game.moves), ("pause", 0))
        self.press(5)
        for button in (1, 4, 2, 5, 3):
            self.press(button)
        self.assertTrue(app.game.done)
        self.assertEqual(app.profile.data["stats"]["played"], 1)
        app.present()
        self.now[0] += 3
        for _ in range(5):
            app.tick()
        self.assertEqual(app.screen, "result")
        self.assertEqual(app.profile.data["stats"]["played"], 1)
        loaded = json.loads(Path(app.config["profile"]).read_text())
        self.assertEqual(loaded["coins"], 2)
        self.press(7)
        self.assertEqual(app.screen, "final_board")
        self.press(1)
        self.assertEqual(app.screen, "result")
        self.press(4)
        self.assertEqual(app.screen, "duel")
        app.rps_until = self.now[0]
        app.go("duel_result")
        app.tick()
        self.assertEqual(app.game.moves, 0)

    def test_blind_timer_begins_after_display_and_pause_cannot_reveal(self):
        app = self.app
        app.mode_key, app.settings["opponent"] = "blind", "local"
        app.start_game()
        self.press(1)
        self.now[0] += 8  # A slow full-screen SPI transfer must not use up reveal time.
        app.present()
        self.assertEqual(app.reveal_until, self.now[0] + app.config["blind_reveal_seconds"])
        self.press(2)
        self.assertEqual(app.game.moves, 1)
        self.now[0] += app.config["blind_reveal_seconds"] + 0.1
        app.tick()
        self.assertFalse(app.blind_visible)
        self.press(5, "long")
        self.press(5)
        self.assertFalse(app.blind_visible)

    def test_one_switch_is_announced_one_turn_ahead(self):
        app = self.app
        app.mode_key, app.settings["opponent"] = "switch_one", "local"
        app.start_game()
        app.game = Game("switch_one", switch_turns=(5,))
        for a in (0, 3, 1):
            app.make_move(a)
        self.assertEqual(app.notice, "")
        app.make_move(7)
        self.assertEqual(app.notice, "다음 수 후 위치 교환!")
        self.assertEqual(app.game.switch_pair(), (0, 3))  # both showing lifetime 2
        app.make_move(5)
        self.assertEqual(app.notice, "위치 교환!")
        self.assertIsNone(app.game.switch_pair())

    def test_settings_save_on_press_and_forced_first_skips_rps(self):
        app = self.app
        app.go("settings")
        self.press(6)
        saved = json.loads(Path(app.profile.path).read_text(encoding="utf-8"))
        self.assertFalse(saved["settings"]["show_lifetime"])
        self.press(5)  # difficulty is no longer a setting
        self.assertEqual(app.screen, "settings")
        self.press(7)
        self.assertTrue(json.loads(Path(app.profile.path).read_text(encoding="utf-8"))["settings"]["human_first"])
        app.go("mode")
        self.press(5)
        self.press(8)
        self.assertEqual((app.screen, app.human_mark), ("game", 1))
        app.go("mode")
        self.press(9)  # original, no difficulty screen
        self.assertEqual((app.screen, app.human_mark), ("game", 1))
        app.go("settings")
        self.press(7)
        app.go("mode")
        self.press(5)
        self.press(8)
        self.assertEqual(app.screen, "rps")

    def test_local_first_setting_is_disabled_and_every_restart_uses_rps(self):
        app = self.app
        app.settings.update(opponent="ai", human_first=True)
        app.go("settings")
        self.press(4)
        self.assertEqual(app.settings["opponent"], "local")
        self.press(7)
        self.assertTrue(app.settings["human_first"])
        self.press(2)
        self.assertEqual(app.notice, "")  # settings save automatically; no save button
        saved = json.loads(Path(app.profile.path).read_text(encoding="utf-8"))
        self.assertEqual(saved["settings"]["opponent"], "local")
        app.begin_match()
        self.assertEqual(app.screen, "duel")
        app.start_game()
        app.go("pause")
        self.press(6)
        self.assertEqual(app.screen, "duel")
        app.go("settings")
        self.press(4)
        self.press(7)
        self.assertFalse(app.settings["human_first"])

    def test_nine_switch_warning_persists_until_switch_and_clears_on_win(self):
        from vttt.render import Renderer, RED
        from PIL import ImageColor
        app = self.app
        app.mode_key, app.settings["opponent"] = "switch_nine", "local"
        app.start_game()
        app.game = Game("switch_nine", switch_turns=(5,))
        r = Renderer()
        for a in (0, 3, 1):
            app.make_move(a)
        self.assertFalse(app.game.nine_switch_due())
        app.make_move(4)
        self.assertTrue(app.game.nine_switch_due())
        self.now[0] += 5
        app.tick()
        self.assertEqual(r.draw(app).getpixel((0, 0)), ImageColor.getrgb(RED))
        app.make_move(8)
        self.assertEqual(app.game.last_event, "switch")
        self.assertFalse(app.game.nine_switch_due())
        self.assertEqual(r.draw(app).getpixel((0, 0)), ImageColor.getrgb(RED))
        app.present()
        self.now[0] += 1.1
        app.tick()
        for _ in range(4):
            app.present()
            self.now[0] += 0.2
            app.tick()
        self.assertNotEqual(r.draw(app).getpixel((0, 0)), ImageColor.getrgb(RED))
        app.start_game()
        app.game = Game("switch_nine", switch_turns=(5, 6))
        for a in (0, 3, 1, 4, 2):
            app.make_move(a)
        self.assertTrue(app.game.done)
        self.assertFalse(app.game.nine_switch_due())
        self.assertIsNone(app.nine_switch)

    def test_nine_switch_shows_placement_before_simultaneous_flip(self):
        from vttt.app import SWITCH_HOLD_SECONDS, SWITCH_FLIP_SECONDS
        from vttt.render import Renderer
        app = self.app
        app.mode_key, app.settings["opponent"] = "switch_nine", "local"
        app.start_game()
        app.game = Game("switch_nine", switch_turns=(5,))
        for action in (0, 3, 1, 4, 8):
            app.make_move(action)
        r = Renderer()
        board, lives, _ = r.motion_view(app)
        self.assertEqual(board[8], 1)  # the new piece is still the mover's
        self.assertEqual(board, [-mark for mark in app.game.board])
        self.assertEqual(lives, app.game.lifetimes())
        self.assertEqual(app.game.board[8], -1)  # rules remain atomic for AI/search
        original = app.game.key()
        self.press(6)
        self.press(5, "long")
        self.assertFalse(app.make_move(5))
        self.assertEqual((app.screen, app.game.key()), ("game", original))
        # Even a very slow first display cannot consume the confirmation time.
        self.now[0] += 20
        app.tick()
        self.assertEqual(app.nine_switch["phase"], "placed")
        app.present()
        self.now[0] += SWITCH_HOLD_SECONDS - 0.01
        app.tick()
        self.assertEqual(app.nine_switch["phase"], "placed")
        self.now[0] += 0.02
        app.tick()
        self.assertEqual(app.nine_switch["phase"], "switching")
        for progress in (0, 0.25, 0.5, 0.75):
            self.assertEqual(app.nine_switch["progress"], progress)
            self.now[0] += 20
            app.tick()  # no frame can be skipped before it is presented
            self.assertEqual(app.nine_switch["progress"], progress)
            app.present()
            self.now[0] += SWITCH_FLIP_SECONDS / 4 + 0.01
            app.tick()
        self.assertIsNone(app.nine_switch)
        self.assertEqual(r.motion_view(app)[0], app.game.board)
        self.assertEqual(app.game.key(), original)
        self.assertTrue(app.make_move(5))

    def test_nine_switch_blocks_ai_and_reset_clears_animation(self):
        app = self.app
        app.mode_key = "switch_nine"
        app.settings.update(opponent="ai", human_first=True)
        app.start_game()
        app.game = Game("switch_nine", switch_turns=(5,))
        for action in (0, 3, 1, 4, 8):
            app.make_move(action)
        self.assertTrue(app.is_ai_turn())
        self.now[0] += 20
        app.tick()
        self.assertIsNone(app.future)
        self.assertEqual(app.game.moves, 5)
        app.start_game()
        self.assertIsNone(app.nine_switch)
        self.assertTrue(app.make_move(0))

    def test_ai_move_waits_two_seconds_however_fast_it_thinks(self):
        app = self.app
        app.settings.update(opponent="ai", human_first=True, difficulty="easy")
        app.start_game()
        app.present()
        self.press(1)
        start = self.now[0]
        self.now[0] = start + 0.5
        app.tick()
        app.future.result(timeout=3)
        self.now[0] = start + 1.9
        app.tick()
        self.assertEqual(app.game.moves, 1)  # computed, but held back
        self.now[0] = start + 2.0
        app.tick()
        self.assertEqual(app.game.moves, 2)

    def test_vanishing_piece_fades_over_one_second_without_eating_clicks(self):
        app = self.app
        app.settings["opponent"] = "local"
        app.start_game()
        for a in (0, 3, 1, 4, 8, 6):
            app.make_move(a)
        self.assertIsNone(app.fade)
        app.make_move(2)
        self.assertEqual(app.fade[:2], (0, 1))
        app.present()
        pressed = self.now[0] + 0.05
        steps = []
        for _ in range(5):
            self.now[0] += 0.21
            app.tick()
            steps.append(app.fade_step)
            app.present()  # animation frames must not discard the click below
        self.assertEqual(steps, [1, 2, 3, 4, 5])
        self.assertIsNone(app.fade)
        app.handle(ButtonEvent(6, "short", pressed))
        self.assertEqual(app.game.moves, 8)

    def test_gravity_drop_then_vanish_then_fall_are_separate_motions(self):
        from vttt.render import Renderer
        app = self.app
        app.settings["opponent"] = "local"
        app.mode_key = "gravity"
        app.start_game()
        for button in (5, 5, 4, 4, 1, 2, 9, 6):
            if app.gravity_warning_waiting():
                app.present()
                self.now[0] += 3
            app.make_move(button - 1)
        view = Renderer().motion_view
        start = self.now[0]
        self.now[0] = start + 0.2  # new X drops into 6; the X on 8 is still whole
        board, _, movers = view(app)
        self.assertEqual([(a, b) for a, b, _, _ in movers], [(2, 5)])
        self.assertEqual((board[7], board[4]), (-1, -1))
        self.now[0] = start + 0.8  # X on 8 fades in place, nothing moves, X on 5 waits
        board, _, movers = view(app)
        self.assertEqual((movers, board[7], board[4]), ([], 0, -1))
        self.now[0] = start + 1.5  # then the X on 5 falls into 8
        board, _, movers = view(app)
        self.assertEqual([(a, b) for a, b, _, _ in movers], [(4, 7)])
        self.now[0] = start + 2.0
        app.tick()
        board, _, movers = view(app)
        self.assertEqual((movers, board), ([], app.game.board))

    def test_gravity_warning_holds_after_display_and_queues_only_first_click(self):
        from vttt.app import GRAVITY_WARNING_SECONDS
        app = self.app
        app.settings["opponent"] = "local"
        app.mode_key = "gravity"
        app.start_game()
        for action in (0, 1, 2, 0, 1):
            app.make_move(action)
        snapshot = app.game.key()
        self.press(3)
        self.press(1)
        self.assertEqual(app.gravity_warning["action"], 2)
        self.now[0] += 20
        app.tick()
        self.assertEqual(app.game.key(), snapshot)
        app.present()  # the timer starts after the full screen has been sent
        self.now[0] += GRAVITY_WARNING_SECONDS - 0.01
        app.tick()
        self.assertEqual(app.game.key(), snapshot)
        self.now[0] += 0.02
        app.tick()
        self.assertEqual((app.game.moves, app.game.last_event), (6, "clear"))
        self.assertEqual(app.game.last_action % 3, 2)
        self.assertIsNone(app.gravity_warning)

    def test_gravity_warning_stops_ai_and_resets_when_restarting(self):
        app = self.app
        app.settings.update(opponent="ai", human_first=True)
        app.mode_key = "gravity"
        app.start_game()
        for action in (0, 1, 2, 0, 1):
            app.make_move(action)
        self.assertTrue(app.is_ai_turn())
        self.now[0] += 20
        app.tick()
        self.assertIsNone(app.future)
        app.present()
        self.now[0] += 2.4
        app.tick()
        self.assertIsNone(app.future)
        self.assertEqual(app.game.moves, 5)
        app.start_game()
        self.assertIsNone(app.gravity_warning)

    def test_gravity_keeps_queued_column_when_another_click_arrives_at_timeout(self):
        app = self.app
        app.settings["opponent"] = "local"
        app.mode_key = "gravity"
        app.start_game()
        for action in (0, 1, 2, 0, 1):
            app.make_move(action)
        app.present()
        self.press(3)
        self.now[0] += 3
        self.press(1)  # event polling happens before tick; keep the first choice
        self.assertEqual((app.game.moves, app.game.last_action % 3), (6, 2))

    def test_blind_draws_only_the_piece_just_placed(self):
        from vttt.render import BG, Renderer
        app = self.app
        app.mode_key, app.settings["opponent"] = "blind", "local"
        app.start_game()
        for a in (0, 4, 8):
            app.make_move(a)
        renderer = Renderer()

        def drawn():
            frame = renderer.draw(app)
            cells = []
            for a in range(9):
                x, y = renderer.origin(a + 1)
                tile = frame.crop((x + 40, y + 40, x + 200, y + 180)).getcolors(10 ** 6)
                if any(color != Image.new("RGB", (1, 1), BG).getpixel((0, 0)) for _, color in tile):
                    cells.append(a)
            return cells

        from PIL import Image
        self.assertEqual(drawn(), [8])  # reveal window: newest piece only
        app.blind_visible = False
        self.assertEqual(drawn(), [])
        app.go("final_board")
        self.assertEqual(drawn(), [0, 4, 8])

    def test_ai_turn_blocks_human_clicks_and_stale_future_is_ignored(self):
        app = self.app
        app.settings["human_first"] = False
        app.rps_human_first = False  # AI won rock-paper-scissors
        app.start_game()
        self.press(1)
        self.assertEqual(app.game.moves, 0)
        self.now[0] += 1
        app.tick()
        self.assertIsNotNone(app.future)
        self.press(5, "long")
        self.assertEqual(app.screen, "pause")
        self.assertIsNone(app.future)
        self.press(4)
        app.tick()
        self.assertEqual((app.screen, app.game.moves), ("menu", 0))

    def test_input_from_old_frame_is_not_a_move(self):
        app = self.app
        app.settings["opponent"] = "local"
        app.start_game()
        app.present()
        app.handle(ButtonEvent(1, "short", 9.5))
        self.assertEqual(app.game.moves, 0)
        app.handle(ButtonEvent(1, "short", 10.5))
        self.assertEqual(app.game.moves, 1)

    def test_shop_prevents_overspending_and_persists_theme(self):
        profile = self.app.profile
        self.assertEqual(profile.buy_or_select("fishcat"), "코인이 부족합니다")
        profile.data["coins"] = 25
        profile.buy_or_select("fishcat")
        profile.buy_or_select("fishcat")
        restored = Profile(profile.path, self.app.config)
        self.assertEqual(restored.data["coins"], 5)
        self.assertEqual(restored.data["theme"], "fishcat")

    def test_win_rewards_follow_played_difficulty_including_fixed_modes(self):
        app = self.app
        app.settings.update(opponent="ai", human_first=True)
        total = app.profile.data["coins"]
        for mode in ("vanishing", "original"):
            for difficulty, reward in (("easy", 3), ("normal", 5), ("hard", 10)):
                with self.subTest(mode=mode, difficulty=difficulty):
                    app.mode_key = mode
                    app.settings["difficulty"] = difficulty
                    app.start_game()
                    for action in (0, 3, 1, 4, 2):
                        app.make_move(action)
                    expected = 5 if mode == "original" else reward
                    total += expected
                    self.assertEqual(app.last_coins, expected)
                    self.assertEqual(app.profile.data["coins"], total)
                    saved = json.loads(Path(app.profile.path).read_text(encoding="utf-8"))
                    self.assertEqual(saved["coins"], total)

    def test_losses_always_reward_one_and_draws_stay_two(self):
        app = self.app
        app.settings.update(opponent="ai", human_first=False)
        app.rps_human_first = False
        for difficulty in ("easy", "normal", "hard"):
            app.mode_key = "original"
            app.settings["difficulty"] = difficulty
            app.start_game()
            for action in (0, 3, 1, 4, 2):
                app.make_move(action)
            self.assertEqual(app.last_coins, 1)
            app.start_game()
            for action in (0, 1, 2, 4, 3, 5, 7, 6, 8):
                app.make_move(action)
            self.assertEqual(app.last_coins, 2)

    def test_model_ai_completes_a_controller_match_in_every_mode(self):
        app = self.app
        app.ai = GameAI(app.config, random.Random(17))
        app.settings.update(opponent="ai", human_first=True, difficulty="easy")
        for mode in MODES:
            app.mode_key = mode
            app.start_game()
            app.present()
            for _ in range(450):
                self.now[0] += 5
                app.tick()
                if app.future is not None:
                    app.future.result(timeout=3)
                    app.tick()
                elif app.screen == "game" and not app.game.done and not app.is_ai_turn():
                    self.press(app.game.legal_actions()[0] + 1)
                app.present()
                if app.game.done:
                    self.now[0] += 5
                    app.tick()
                    break
            self.assertTrue(app.game.done, mode)
            self.assertEqual(app.screen, "result", mode)
        self.assertEqual(app.profile.data["stats"]["played"], 6)


class AITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = GameAI(runtime_config(), random.Random(1))

    def test_checkpoint_cnn_has_finite_deterministic_nine_outputs(self):
        import numpy as np
        self.assertIsNotNone(self.ai.network)
        obs = Game().observation()
        a, b = self.ai.network(obs), self.ai.network(obs)
        self.assertEqual(a.shape, (9,))
        self.assertTrue(np.all(np.isfinite(a)))
        np.testing.assert_array_equal(a, b)

    def test_immediate_win_and_forced_block(self):
        win = Game("original")
        for a in (0, 3, 1, 4):
            win.play(a)
        self.assertEqual(self.ai.select_action(win, "hard"), 2)
        block = Game("original")
        for a in (0, 4, 1):
            block.play(a)
        self.assertEqual(self.ai.select_action(block, "hard"), 2)

    def test_vanishing_does_not_block_a_threat_that_disappears(self):
        game = Game()
        for a in (0, 3, 1, 4, 8):
            game.play(a)
        # Opponent's apparent 0,1,_ threat disappears when their oldest 0 vanishes.
        # Current player can win immediately at 5, which must take priority.
        self.assertEqual(self.ai.select_action(game, "hard"), 5)

    def test_difficulty_changes_how_often_an_open_win_is_taken(self):
        win = Game("original")
        for a in (0, 3, 1, 4):
            win.play(a)
        ai = GameAI(rng=random.Random(5))
        taken = {level: sum(ai.select_action(win, level) == 2 for _ in range(200))
                 for level in ("easy", "normal", "hard")}
        self.assertEqual(taken["hard"], 200)
        self.assertGreater(taken["normal"], taken["easy"])
        self.assertLess(taken["easy"], 170)

    def test_search_returns_legal_moves_for_all_modes(self):
        for mode in MODES:
            game = Game(mode)
            for _ in range(6):
                if game.done:
                    break
                action = self.ai.select_action(game, "normal")
                self.assertIn(action, game.legal_actions())
                game.play(action)

    def test_numpy_convolution_against_independent_scalar_reference(self):
        import numpy as np
        from vttt.network import conv3
        rng = np.random.default_rng(3)
        x = rng.normal(size=(2, 3, 3)).astype(np.float32)
        weights = rng.normal(size=(4, 2, 3, 3)).astype(np.float32)
        bias = rng.normal(size=4).astype(np.float32)
        expected = np.zeros((4, 3, 3), dtype=np.float32)
        for o in range(4):
            for r in range(3):
                for c in range(3):
                    expected[o, r, c] = bias[o]
                    for i in range(2):
                        for dr in range(-1, 2):
                            for dc in range(-1, 2):
                                if 0 <= r + dr < 3 and 0 <= c + dc < 3:
                                    expected[o, r, c] += x[i, r + dr, c + dc] * weights[o, i, dr + 1, dc + 1]
        np.testing.assert_allclose(conv3(x, weights, bias), expected, rtol=1e-5, atol=2e-6)

    def test_fused_batchnorm_preserves_full_network_outputs(self):
        import numpy as np
        from vttt.network import conv3
        model = self.ai.network
        w = model.weights

        def unfused(x, conv, bn):
            x = conv3(x, w[conv + ".weight"], np.zeros(w[conv + ".weight"].shape[0], dtype=np.float32))
            x = (x - w[bn + ".running_mean"][:, None, None]) / np.sqrt(w[bn + ".running_var"][:, None, None] + 1e-5)
            return x * w[bn + ".weight"][:, None, None] + w[bn + ".bias"][:, None, None]

        rng = np.random.default_rng(9)
        for _ in range(5):
            obs = rng.integers(0, 4, size=(2, 3, 3)).astype(np.float32)
            x = np.maximum(unfused(obs, "stem.0", "stem.1"), 0)
            for i in range(5):
                residual = x
                x = np.maximum(unfused(x, f"blocks.{i}.conv1", f"blocks.{i}.bn1"), 0)
                x = np.maximum(unfused(x, f"blocks.{i}.conv2", f"blocks.{i}.bn2") + residual, 0)
            x = np.maximum(w["head.1.weight"] @ x.reshape(-1) + w["head.1.bias"], 0)
            expected = w["head.4.weight"] @ x + w["head.4.bias"]
            np.testing.assert_allclose(model(obs), expected, rtol=1e-4, atol=2e-5)


class ConfigAndFrameTests(unittest.TestCase):
    def test_defaults_preserve_original_pins_and_polarity(self):
        cfg = hardware_config()
        self.assertEqual(cfg["lcd_cs_pins"], [2, 15, 4, 12, 16, 18, 14, 23, 24])
        self.assertTrue(cfg["button_active_high"])
        self.assertEqual(cfg["reset_pin"], 27)

    def test_frame_split_preserves_physical_row_major_positions(self):
        from PIL import Image, ImageDraw
        frame = Image.new("RGB", (720, 720))
        d = ImageDraw.Draw(frame)
        for i in range(9):
            d.rectangle((i % 3 * 240, i // 3 * 240, i % 3 * 240 + 239, i // 3 * 240 + 239), fill=(i * 20, 1, 2))
        tiles = split_frame(frame)
        for i, tile in enumerate(tiles):
            self.assertEqual(tile.getpixel((120, 120)), (i * 20, 1, 2))


if __name__ == "__main__":
    unittest.main()

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

    def test_gravity_clicks_drop_in_column(self):
        game = Game("gravity")
        self.assertEqual(game.play(0), 6)
        self.assertEqual(game.play(6), 3)
        self.assertEqual(game.play(3), 0)
        before = game.key()
        with self.assertRaises(ValueError):
            game.play(6)
        self.assertEqual(game.key(), before)

    def test_switching_moves_queues_and_lifetime_together(self):
        one = Game("switch_one")
        self.assertEqual(one.play(0), 2)
        self.assertEqual(one.queues[1], [2])
        self.assertEqual(one.play(0), 2)
        self.assertEqual(one.queues[1], [8])
        nine = Game("switch_nine")
        for a in (0, 3, 1, 4, 8, 6, 2, 0):
            nine.play(a)
        self.assertEqual(nine.last_action, 0)
        nine.play(3)
        self.assertEqual(nine.queues[1], [6, 8, 1])
        self.assertEqual(nine.last_action, 1)
        self.assertEqual(nine.lifetimes()[6], 1)

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
            self.assertEqual((self.app.screen, self.app.mode_key), ("setup", mode))
            self.press(8)
            self.assertEqual(self.app.screen, "help")
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
        self.assertEqual(app.game.moves, 0)

    def test_blind_timer_begins_after_display_and_pause_cannot_reveal(self):
        app = self.app
        app.mode_key, app.settings["opponent"] = "blind", "local"
        app.start_game()
        self.press(1)
        self.now[0] += 8  # A slow full-screen SPI transfer must not use up reveal time.
        app.present()
        self.assertEqual(app.reveal_until, self.now[0] + 1.5)
        self.press(2)
        self.assertEqual(app.game.moves, 1)
        self.now[0] += 1.6
        app.tick()
        self.assertFalse(app.blind_visible)
        self.press(5, "long")
        self.press(5)
        self.assertFalse(app.blind_visible)

    def test_ai_turn_blocks_human_clicks_and_stale_future_is_ignored(self):
        app = self.app
        app.settings["human_first"] = False
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
        self.assertEqual(self.ai.select_action(win), 2)
        block = Game("original")
        for a in (0, 4, 1):
            block.play(a)
        self.assertEqual(self.ai.select_action(block), 2)

    def test_vanishing_does_not_block_a_threat_that_disappears(self):
        game = Game()
        for a in (0, 3, 1, 4, 8):
            game.play(a)
        # Opponent's apparent 0,1,_ threat disappears when their oldest 0 vanishes.
        # Current player can win immediately at 5, which must take priority.
        self.assertEqual(self.ai.select_action(game), 5)

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

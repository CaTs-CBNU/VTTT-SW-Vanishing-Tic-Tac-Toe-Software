"""Transparent theme assets and the player labels shown on the game screens."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from vttt.app import Application
from vttt.backends import HeadlessBackend
from vttt.config import runtime_config
from vttt.profile import THEMES
from vttt.render import ASSETS, Renderer


class PieceRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = Renderer()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        config = runtime_config()
        config["profile"] = str(Path(self.temp.name) / "profile.json")
        self.app = Application(config, HeadlessBackend(), self.renderer, ai=object())
        self.app.settings["opponent"] = "local"
        self.app.start_game()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_all_twelve_pieces_have_transparent_backgrounds(self):
        for theme in THEMES:
            for mark in ("o", "x"):
                with self.subTest(theme=theme, mark=mark):
                    with Image.open(ASSETS / "theme" / f"{theme}-{mark}.png") as image:
                        self.assertEqual(image.mode, "RGBA")
                        self.assertEqual(image.getchannel("A").getextrema(), (0, 255))
                        for corner in ((0, 0), (image.width - 1, 0),
                                       (0, image.height - 1), (image.width - 1, image.height - 1)):
                            self.assertEqual(image.getpixel(corner)[3], 0)

    def test_piece_keeps_winning_tile_background_visible(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                self.app.profile.data["theme"] = theme
                for action in (0, 3, 1, 4, 2):
                    self.app.make_move(action)
                image = self.renderer.draw(self.app)
                icon = self.renderer.icons[theme, "o"]
                # Sample a transparent pixel inside the pasted image's rectangle.
                point = next((x, y) for y in range(icon.height) for x in range(icon.width)
                             if icon.getpixel((x, y))[3] == 0)
                location = ((240 - icon.width) // 2 + point[0], 38 + point[1])
                self.assertEqual(image.getpixel(location), (0xE3, 0xF4, 0xE9))
                self.app.start_game()

    def test_result_uses_winner_piece_for_every_theme_and_either_player(self):
        for theme in THEMES:
            for winner in (1, -1):
                with self.subTest(theme=theme, winner=winner):
                    self.app.profile.data["theme"] = theme
                    self.app.game.winner, self.app.game.done = winner, True
                    self.app.local_first_mark = -winner
                    self.app.go("result")
                    with patch.object(self.renderer, "piece_text", wraps=self.renderer.piece_text) as label:
                        self.renderer.draw(self.app)
                    self.assertEqual(label.call_args.args[2:5], (winner, theme, "승리!"))

    def test_local_turn_uses_current_piece_at_text_size(self):
        self.app.profile.data["theme"] = "squirrel"
        for mark in (1, -1):
            self.app.game.turn = mark
            with patch.object(self.renderer, "piece_text", wraps=self.renderer.piece_text) as label:
                self.renderer.draw(self.app)
            self.assertEqual(label.call_args.args[2:6], (mark, "squirrel", "차례", 19))

    def test_duel_result_labels_follow_the_assigned_marks(self):
        self.app.profile.data["theme"] = "fishcat"
        self.app.rps_human_first = False
        self.app.go("duel_result")
        with patch.object(self.renderer, "piece_text", wraps=self.renderer.piece_text) as labels:
            self.renderer.draw(self.app)
        top, bottom = labels.call_args_list[-2:]
        self.assertEqual((top.args[2], top.kwargs["prefix"]), (1, "위: "))
        self.assertEqual((bottom.args[2], bottom.kwargs["prefix"]), (-1, "아래: "))


if __name__ == "__main__":
    unittest.main()

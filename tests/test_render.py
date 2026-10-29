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
                    self.assertEqual(label.call_args.kwargs["icon_size"], 72)

    def test_local_turn_uses_current_piece_at_text_size(self):
        self.app.profile.data["theme"] = "squirrel"
        for mark in (1, -1):
            self.app.game.turn = mark
            with patch.object(self.renderer, "piece_text", wraps=self.renderer.piece_text) as label:
                self.renderer.draw(self.app)
            self.assertEqual(label.call_args.args[2:6], (mark, "squirrel", "차례", 19))
            self.assertEqual(label.call_args.kwargs["icon_size"], 48)

    def test_help_page_indicator_is_on_display_eight_and_rule_status_is_removed(self):
        from PIL import ImageChops
        self.app.go("help")
        for index in range(7):
            self.app.help_index = index
            with patch.object(self.renderer, "text", wraps=self.renderer.text) as labels:
                image = self.renderer.draw(self.app)
            pages = [call for call in labels.call_args_list if call.args[2] == f'{index + 1} / 7']
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0].args[1], (360, 610))
            self.assertFalse(any('규칙 상태' in call.args[2] or '확정 규칙' in call.args[2]
                                 for call in labels.call_args_list))
            self.assertIsNone(ImageChops.difference(image.crop((6, 6, 234, 234)),
                             self.renderer.art['go_back_button'].crop((6, 6, 234, 234))).getbbox())

    def test_gravity_warns_on_all_three_bottom_tiles_only_before_a_clear(self):
        from PIL import ImageColor
        from vttt.render import RED
        self.app.mode_key = "gravity"
        self.app.start_game()
        for action in (0, 1, 2, 0):
            self.app.make_move(action)
        before = self.renderer.draw(self.app)
        self.app.make_move(1)
        with patch.object(self.renderer, "strip", wraps=self.renderer.strip) as strips:
            warning = self.renderer.draw(self.app)
        labels = {call.args[1] for call in strips.call_args_list if call.args[2] == "이제 지워집니다!"}
        self.assertEqual(labels, {7, 8, 9})
        self.app.present()
        self.app.gravity_warning["shown_at"] -= 3
        self.app.make_move(2)
        after = self.renderer.draw(self.app)
        for button in (7, 8, 9):
            x, y = self.renderer.origin(button)
            point = (x + 120, y + 4)
            self.assertNotEqual(before.getpixel(point), ImageColor.getrgb(RED))
            self.assertEqual(warning.getpixel(point), ImageColor.getrgb(RED))
            self.assertNotEqual(after.getpixel(point), ImageColor.getrgb(RED))
        # One continuous outer frame, without red dividers between the tiles.
        for x in (0, 239, 240, 479, 480, 719):
            self.assertEqual(warning.getpixel((x, 480)), ImageColor.getrgb(RED))
            self.assertEqual(warning.getpixel((x, 719)), ImageColor.getrgb(RED))
        for x in (239, 240, 479, 480):
            self.assertNotEqual(warning.getpixel((x, 600)), ImageColor.getrgb(RED))

    def test_duel_result_labels_follow_the_assigned_marks(self):
        self.app.profile.data["theme"] = "fishcat"
        self.app.rps_human_first = False
        self.app.go("duel_result")
        with patch.object(self.renderer, "piece_text", wraps=self.renderer.piece_text) as labels:
            self.renderer.draw(self.app)
        top, bottom = labels.call_args_list[-2:]
        self.assertEqual((top.args[2], top.kwargs["prefix"]), (1, "위: "))
        self.assertEqual((bottom.args[2], bottom.kwargs["prefix"]), (-1, "아래: "))

    def test_mode_theme_tile_updates_after_applying_a_theme(self):
        from PIL import ImageChops
        from vttt.buttons import ButtonEvent
        app = self.app
        app.go("mode")
        before = self.renderer.draw(app)
        app.handle(ButtonEvent(3, "short"))
        self.assertEqual(app.screen, "themes")
        app.profile.data["owned"].append("squirrel")
        app.shop_page = 0
        app.handle(ButtonEvent(5, "short"))
        app.handle(ButtonEvent(8, "short"))
        self.assertEqual(app.profile.data["theme"], "squirrel")
        app.handle(ButtonEvent(1, "short"))
        self.assertEqual(app.screen, "mode")
        app.flash = ()
        after = self.renderer.draw(app)
        self.assertIsNotNone(ImageChops.difference(before.crop((480, 0, 720, 240)),
                                                  after.crop((480, 0, 720, 240))).getbbox())
        self.assertIsNone(ImageChops.difference(before.crop((0, 240, 720, 720)),
                                               after.crop((0, 240, 720, 720))).getbbox())


if __name__ == "__main__":
    unittest.main()

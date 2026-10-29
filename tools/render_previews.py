"""Render reproducible UI previews without opening GPIO or a desktop window."""

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vttt.ai import GameAI
from vttt.app import Application, GRAVITY_WARNING_SECONDS
from vttt.backends import HeadlessBackend
from vttt.config import runtime_config
from vttt.render import Renderer
from vttt.rules import Game, MODES


def render(output, font=None):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        cfg = runtime_config()
        cfg["profile"] = str(Path(temp) / "profile.json")
        app = Application(cfg, HeadlessBackend(), Renderer(font), ai=GameAI(cfg))
        try:
            for screen in ("start", "menu", "mode", "setup", "rps", "shop", "settings", "scores", "help", "diagnostic"):
                app.go(screen)
                app.renderer.draw(app).save(output / (screen + ".png"))
            ui = app.connectivity
            for screen in ("communication", "connection", "room_create", "room_search"):
                for connection in ("local", "online"):
                    ui.mode = connection
                    app.go(screen)
                    ui.room_ready = True
                    app.renderer.draw(app).save(output / (screen + "-" + connection + ".png"))
            ui.network = ui.networks[0]
            for screen in ("wifi_scanning", "wifi_scan", "wifi_password", "wifi_chars", "wifi_symbols", "wifi_connecting", "wifi_result"):
                ui.characters = "abcdefghi"
                app.go(screen)
                app.renderer.draw(app).save(output / (screen + ".png"))
            ui.result = "success"
            app.renderer.draw(app).save(output / "wifi-success.png")
            app.shop_page = 4
            app.go("themes")
            app.renderer.draw(app).save(output / "themes-page2.png")
            app.shop_page, app.shop_selected = 0, "squirrel"
            app.go("shop")
            app.renderer.draw(app).save(output / "shop-selected.png")
            app.settings["opponent"] = "local"
            app.go("settings")
            app.renderer.draw(app).save(output / "settings-local.png")
            app.start_game()
            for a in (0, 3, 1, 4):
                app.make_move(a)
            app.renderer.draw(app).save(output / "game.png")
            app.go("pause")
            app.renderer.draw(app).save(output / "pause.png")
            app.go("game")
            app.make_move(2)
            app.renderer.draw(app).save(output / "winning-board.png")
            app.go("result")
            app.renderer.draw(app).save(output / "result.png")
            app.profile.data["theme"] = "squirrel"
            app.renderer.draw(app).save(output / "result-themed.png")
            app.go("game")
            app.renderer.draw(app).save(output / "winning-board-themed.png")
            app.start_game()
            for a in (0, 3, 1, 4):
                app.make_move(a)
            app.renderer.draw(app).save(output / "game-themed.png")
            app.profile.data["theme"] = "default"
            app.mode_key = "blind"
            app.start_game()
            app.make_move(0)
            app.make_move(4)
            app.renderer.draw(app).save(output / "blind-reveal.png")
            app.blind_visible = False
            app.renderer.draw(app).save(output / "blind-hidden.png")
            for name, mode, moves, switch_turns in (("gravity-warning", "gravity", (0, 1, 2, 0, 1), None),
                                                    ("gravity-clear", "gravity", (0, 1, 2, 0, 1, 2), None),
                                                    ("switch-one-warning", "switch_one", (0, 3, 1, 7), (5,)),
                                                    ("switch-one", "switch_one", (0, 8, 1, 7), (4,)),
                                                    ("switch-nine-warning", "switch_nine", (0, 3, 1, 4), (5,)),
                                                    ("switch-nine", "switch_nine", (0, 3, 1, 4, 8), (5,))):
                app.mode_key = mode
                app.start_game()
                app.game = Game(mode, cfg["max_moves"], switch_turns=switch_turns)
                for a in moves:
                    if app.gravity_warning is not None:
                        app.gravity_warning["shown_at"] = app.clock() - GRAVITY_WARNING_SECONDS - 0.01
                    app.make_move(a)
                if app.nine_switch is not None:
                    app.renderer.draw(app).save(output / (name + "-placed.png"))
                    app.nine_switch.update(phase="switching", progress=0.25)
                    app.renderer.draw(app).save(output / (name + "-flip.png"))
                    app.nine_switch.update(progress=0.75)
                    app.renderer.draw(app).save(output / (name + "-flipped.png"))
                    app.nine_switch = None
                app.renderer.draw(app).save(output / (name + ".png"))
            app.settings.update(opponent="local", human_first=False)
            app.mode_key = "vanishing"
            app.begin_match()
            for phase, name in ((1, "duel-countdown"), (3, "duel-press")):
                app.duel_phase = phase
                app.renderer.draw(app).save(output / (name + ".png"))
            app.duel_picks = {"top": 0, "bottom": 1}
            app.rps_human_first, app.duel_reason = True, ""
            app.go("duel_result")
            app.renderer.draw(app).save(output / "duel-result.png")
            app.go("settings")
            app.flash = (6,)
            app.renderer.draw(app).save(output / "press-flash.png")
            app.flash = ()
            for index in range(1, len(MODES) + 1):
                app.help_index = index
                app.go("help")
                app.renderer.draw(app).save(output / ("help-" + list(MODES)[index - 1] + ".png"))
        finally:
            app.close()
    print("Rendered previews:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/previews")
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    render(args.output, args.font)

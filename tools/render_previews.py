"""Render reproducible UI previews without opening GPIO or a desktop window."""

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vttt.ai import GameAI
from vttt.app import Application
from vttt.backends import HeadlessBackend
from vttt.config import runtime_config
from vttt.render import Renderer


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
            app.settings["opponent"] = "local"
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
            app.mode_key = "blind"
            app.start_game()
            app.make_move(0)
            app.make_move(4)
            app.blind_visible = False
            app.renderer.draw(app).save(output / "blind-hidden.png")
        finally:
            app.close()
    print("Rendered previews:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/previews")
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    render(args.output, args.font)

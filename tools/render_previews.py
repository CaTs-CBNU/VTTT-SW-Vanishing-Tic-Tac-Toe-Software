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
            for screen in ("start", "menu", "mode", "setup", "shop", "settings", "scores", "help", "diagnostic"):
                app.go(screen)
                app.renderer.draw(app).save(output / (screen + ".png"))
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

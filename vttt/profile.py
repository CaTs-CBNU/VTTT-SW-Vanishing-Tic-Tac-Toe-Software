"""Local, atomic persistence for settings, match records and virtual cosmetics."""

import json
import os
import tempfile
from pathlib import Path

THEMES = {"default": ("기본", 0), "fishcat": ("고양이", 20),
          "squirrel": ("다람쥐", 20), "xmas": ("크리스마스", 30)}


class Profile:
    def __init__(self, path, defaults):
        self.path = Path(path)
        self.warning = ""
        self.data = {"coins": 0, "theme": "default", "owned": ["default"],
                     "settings": {k: defaults[k] for k in ("opponent", "difficulty", "human_first", "show_lifetime")},
                     "stats": {"played": 0, "wins": 0, "losses": 0, "draws": 0, "local": 0}}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("invalid profile")
                self.data["coins"] = max(0, int(loaded.get("coins", 0)))
                owned = loaded.get("owned", [])
                self.data["owned"] = sorted({"default"} | {t for t in owned if t in THEMES})
                theme = loaded.get("theme", "default")
                self.data["theme"] = theme if theme in self.data["owned"] else "default"
                settings = loaded.get("settings", {})
                for k, choices in (("opponent", ("ai", "local")), ("difficulty", ("easy", "normal", "hard"))):
                    if settings.get(k) in choices:
                        self.data["settings"][k] = settings[k]
                for k in ("human_first", "show_lifetime"):
                    if type(settings.get(k)) is bool:
                        self.data["settings"][k] = settings[k]
                stats = loaded.get("stats", {})
                self.data["stats"] = {k: max(0, int(stats.get(k, 0))) for k in self.data["stats"]}
            except (ValueError, TypeError, AttributeError):
                self.warning = "기록 파일을 읽지 못해 기본값으로 시작합니다."

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.path.parent, encoding="utf-8", delete=False) as stream:
                tmp = stream.name
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def buy_or_select(self, theme):
        if theme not in THEMES:
            raise ValueError("Unknown theme")
        if theme not in self.data["owned"]:
            price = THEMES[theme][1]
            if self.data["coins"] < price:
                return "코인이 부족합니다"
            self.data["coins"] -= price
            self.data["owned"].append(theme)
        self.data["theme"] = theme
        self.save()
        return THEMES[theme][0] + " 선택 완료"

    def record(self, game, opponent, human_mark):
        if not game.done:
            raise ValueError("Only finished games can be recorded")
        stats = self.data["stats"]
        stats["played"] += 1
        if opponent == "local":
            stats["local"] += 1
            coins = 2
        elif game.winner == 0:
            stats["draws"] += 1
            coins = 2
        elif game.winner == human_mark:
            stats["wins"] += 1
            coins = 5
        else:
            stats["losses"] += 1
            coins = 1
        self.data["coins"] += coins
        self.save()
        return coins

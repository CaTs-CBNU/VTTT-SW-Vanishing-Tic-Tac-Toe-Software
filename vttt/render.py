"""Pillow renderer: compose one logical canvas, then let the backend split it."""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import ROOT
from .profile import THEMES
from .rules import MODES
from .ui_render import image_tile, draw_setup, draw_rps, draw_duel, draw_shop, draw_settings, draw_result, draw_scores, draw_help, draw_connectivity

BG, INK, BLUE, PINK, GREEN, ORANGE, RED = "#F7F3EF", "#45494C", "#5579FF", "#E965B9", "#45AD76", "#F0A030", "#E5383B"
ASSETS = ROOT / "src/static/images"


def countdown_color(left, total):
    """Grey at a full count, shading to red as the count runs out."""
    t = (total - left) / (total - 1)
    grey, red = (0x76, 0x71, 0x6D), (0xE5, 0x38, 0x3B)
    return tuple(round(g + (r - g) * t) for g, r in zip(grey, red))


class Renderer:
    def __init__(self, font_path=None):
        candidates = [font_path, os.environ.get("VTTT_FONT_PATH"),
                      ROOT / "src/static/fonts/potato.ttf",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                      "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                      "C:/Windows/Fonts/malgun.ttf",
                      "/System/Library/Fonts/AppleSDGothicNeo.ttc"]
        self.font_path = next((p for p in candidates if p and Path(p).is_file()), None)
        if self.font_path is None:
            raise RuntimeError("한글 글꼴이 필요합니다. Pi: sudo apt install fonts-noto-cjk / --font 글꼴경로")
        self.fonts = {}
        self.pages = {}
        self.icons = {}
        self.art = {}
        for path in (ASSETS / "ui").glob("*.jpeg"):
            with Image.open(path) as img:
                self.art[path.stem] = img.convert("RGB").resize((240, 240), Image.Resampling.LANCZOS)
        for group in ("result", "settings", "shop"):
            for path in (ASSETS / group).glob("*.jpeg"):
                with Image.open(path) as img:
                    self.art[f"{group}/{path.stem}"] = img.convert("RGB").resize((240, 240), Image.Resampling.LANCZOS)
        for page in ("start", "menu", "mode"):
            canvas = Image.new("RGB", (720, 720), BG)
            for i in range(1, 10):
                stem = ASSETS / page / f"{page}{i}"
                file = next((stem.with_suffix(ext) for ext in (".png", ".jpeg", ".jpg")
                             if stem.with_suffix(ext).is_file()), None)
                if file is None:
                    raise FileNotFoundError("화면 이미지가 없습니다: " + str(stem))
                with Image.open(file) as img:
                    tile = img.convert("RGB").resize((240, 240), Image.Resampling.LANCZOS)
                canvas.paste(tile, self.origin(i))
            self.pages[page] = canvas
        menu_tile = Image.new("RGB", (240, 240), BG)
        menu_tile.paste(self.art["multiplay_icon"].resize((176,176), Image.Resampling.LANCZOS), (32,5))
        self.text(ImageDraw.Draw(menu_tile), (120,210), "통신", 32)
        self.pages["menu"].paste(menu_tile, self.origin(8))
        for button, name in {1: "go_back_button", 2: "mode_selection_button", 3: "theme_selection_button",
                             4: "blind_mode", 5: "vanishing_mode", 6: "gravity_mode",
                             7: "9switching_mode", 8: "1switching_mode", 9: "original_mode"}.items():
            image_tile(self, self.pages["mode"], button, name)
        for theme in THEMES:
            for mark in ("o", "x"):
                with Image.open(ASSETS / "theme" / f"{theme}-{mark}.png") as img:
                    icon = img.convert("RGBA")
                    bounds = icon.getchannel("A").getbbox()
                    if bounds:
                        icon = icon.crop(bounds)
                    self.icons[theme, mark] = ImageOps.contain(icon, (150, 150))

    @staticmethod
    def origin(button):
        return ((button - 1) % 3 * 240, (button - 1) // 3 * 240)

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = ImageFont.truetype(self.font_path, size)
        return self.fonts[size]

    def text(self, draw, xy, text, size=26, color=INK, max_width=212):
        font = self.font(size)
        while size > 12 and draw.textlength(text, font=font) > max_width:
            size -= 1
            font = self.font(size)
        draw.text(xy, text, font=font, fill=color, anchor="mm")

    def tile(self, canvas, button, title, lines=(), accent=BLUE, footer="", selected=False):
        x, y = self.origin(button)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((x + 6, y + 6, x + 234, y + 234), radius=15,
                            fill="#FFFFFF" if selected else BG, outline=accent if selected else "#D7D4D0", width=3)
        self.text(d, (x + 120, y + 44), title, 31, accent)
        for i, line in enumerate(lines):
            self.text(d, (x + 120, y + 98 + i * 30), line, 23)
        if footer:
            self.text(d, (x + 120, y + 207), footer, 17, "#74787D")

    def strip(self, canvas, button, text, color=INK):
        x, y = self.origin(button)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((x + 8, y + 205, x + 232, y + 234), radius=8, fill=BG)
        self.text(d, (x + 120, y + 219), text, 17, color)

    def piece_text(self, canvas, xy, mark, theme, text, size=26, color=INK, prefix="", max_width=212, icon_size=None):
        """Center a text line with a transparent piece as an inline player label."""
        d = ImageDraw.Draw(canvas)
        gap = 6
        while size > 12:
            font = self.font(size)
            width = d.textlength(prefix, font=font) + (icon_size or size) + gap + d.textlength(text, font=font)
            if width <= max_width:
                break
            size -= 1
        font = self.font(size)
        before = d.textlength(prefix, font=font)
        icon_size = icon_size or size
        width = before + icon_size + gap + d.textlength(text, font=font)
        left, cy = xy[0] - width / 2, xy[1]
        d.text((left, cy), prefix, font=font, fill=color, anchor="lm")
        icon = ImageOps.contain(self.icons[theme, "o" if mark == 1 else "x"], (icon_size, icon_size), Image.Resampling.LANCZOS)
        canvas.paste(icon, (round(left + before + (icon_size - icon.width) / 2), round(cy - icon.height / 2)), icon)
        d.text((left + before + icon_size + gap, cy), text, font=font, fill=color, anchor="lm")

    def result_message(self, canvas, xy, app, size=26, icon_size=None):
        if app.game.winner:
            self.piece_text(canvas, xy, app.game.winner, app.profile.data["theme"], app.result_title(), size, icon_size=icon_size)
        else:
            self.text(ImageDraw.Draw(canvas), xy, app.result_title(), size)

    def draw(self, app):
        canvas = self.compose(app)
        for button in app.flash:  # pressed: darken the tile and ring it
            x, y = self.origin(button)
            tile = canvas.crop((x, y, x + 240, y + 240))
            canvas.paste(Image.blend(tile, Image.new("RGB", (240, 240), INK), 0.18), (x, y))
            ImageDraw.Draw(canvas).rounded_rectangle((x + 3, y + 3, x + 236, y + 236), radius=14, outline=BLUE, width=8)
        if app.duel_window_open():  # "눌러!": red frame around the whole board
            ImageDraw.Draw(canvas).rectangle((0, 0, 719, 719), outline=RED, width=16)
        if app.screen == "game" and (app.game.nine_switch_due() or app.nine_switch is not None):
            self.strip(canvas, 2, "스위칭!" if app.nine_switch and app.nine_switch["phase"] == "switching" else "이제 바뀝니다!", RED)
            ImageDraw.Draw(canvas).rectangle((0, 0, 719, 719), outline=RED, width=12)
        if app.screen == "game" and not app.game.done and app.game.clear_due():
            for button in (7, 8, 9):
                self.strip(canvas, button, "이제 지워집니다!", RED)
            ImageDraw.Draw(canvas).rectangle((0, 480, 719, 719), outline=RED, width=12)
        return canvas

    def compose(self, app):
        screen = app.screen
        if screen in ("start", "menu", "mode"):
            canvas = self.pages[screen].copy()
            if screen == "mode":
                theme = app.profile.data["theme"]
                d = ImageDraw.Draw(canvas)
                d.rectangle((480, 0, 719, 239), fill=BG)
                self.text(d, (600, 35), "테마 선택", 31, BLUE)
                for mark, x in (("o", 494), ("x", 614)):
                    icon = ImageOps.contain(self.icons[theme, mark], (92, 110), Image.Resampling.LANCZOS)
                    canvas.paste(icon, (x + (92 - icon.width) // 2, 68 + (110 - icon.height) // 2), icon)
                self.text(d, (600, 211), THEMES[theme][0], 24)
            if app.notice:
                self.strip(canvas, 8 if screen == "start" else 2, app.notice)
            return canvas
        canvas = Image.new("RGB", (720, 720), BG)
        s = app.settings
        mode = MODES[app.mode_key]
        if screen == "setup":
            draw_setup(self, canvas, app)
        elif screen in ("duel", "duel_result"):
            draw_duel(self, canvas, app)
        elif screen in ("rps", "rps_result"):
            draw_rps(self, canvas, app)
        elif screen in ("communication", "connection", "room_create", "room_search") or screen.startswith("wifi_"):
            draw_connectivity(self, canvas, app)
        elif screen == "game":
            self.game(canvas, app)
        elif screen == "pause":
            self.tile(canvas, 2, "일시정지", (mode.title,))
            self.tile(canvas, 4, "메인 메뉴", ("현재 대국 포기",))
            self.tile(canvas, 5, "계속하기", ("대국으로 복귀",), accent=GREEN, selected=True)
            self.tile(canvas, 6, "다시 시작", ("같은 설정으로", "새 대국 시작"))
            self.tile(canvas, 8, "종료", ("프로그램 종료", "라즈베리파이는 유지"), accent=PINK)
        elif screen == "result":
            draw_result(self, canvas, app)
        elif screen == "final_board":
            self.game(canvas, app, reveal=True)
            self.strip(canvas, 5, "아무 칸: 결과로")
        elif screen in ("shop", "themes"):
            draw_shop(self, canvas, app)
        elif screen == "settings":
            draw_settings(self, canvas, app)
        elif screen == "scores":
            draw_scores(self, canvas, app)
        elif screen == "help":
            draw_help(self, canvas, app)
        elif screen == "diagnostic":
            for i in range(1, 10):
                self.tile(canvas, i, str(i), ("버튼 / LCD", "입력 확인" if app.diagnostic_button == i else "이 칸을 눌러보세요"),
                          accent=GREEN if app.diagnostic_button == i else BLUE,
                          selected=app.diagnostic_button == i, footer="5번 길게: 돌아가기")
        if app.notice and screen in ("setup", "settings", "scores", "help", "diagnostic", "pause", "result"):
            self.strip(canvas, 2, app.notice, PINK)
        return canvas

    def mark(self, canvas, x, y, mark, theme, size=150):
        icon = ImageOps.contain(self.icons[theme, "o" if mark == 1 else "x"], (size, size), Image.Resampling.LANCZOS)
        canvas.paste(icon, (x + (240 - icon.width) // 2, y + 38), icon)

    def motion_view(self, app):
        """Board, lifetimes and sliding pieces for the current animation frame.

        Order after a move: the pieces drop (0.35 s), the vanished piece blurs out in place
        (1 s), then whatever it held up falls (0.35 s). Falling slides with speed lines;
        vanishing never moves, so the two read differently.
        """
        game = app.game
        board, lives = game.board, game.lifetimes()
        if app.nine_switch is not None:
            return app.nine_switch["board"], lives, []
        if not app.motion:
            return board, lives, []
        now = app.clock()
        start, drop_end, fade_end, fall_end = app.motion
        if now < fade_end:
            board, lives = game.before_fall()
        if now < drop_end:
            board = board.copy()
            if game.vanished:
                board[game.vanished[0]] = game.vanished[1]
            moves, t = game.drops, (now - start) / (drop_end - start)
        elif fade_end <= now < fall_end:
            board = board.copy()
            moves, t = game.fell, (now - fade_end) / (fall_end - fade_end)
        else:
            return board, lives, []
        movers = [(a, b, board[b], t) for a, b in moves]
        for _, b in moves:
            board[b] = 0
        return board, {k: v for k, v in lives.items() if board[k]}, movers

    def draw_movers(self, canvas, app, movers):
        d = ImageDraw.Draw(canvas)
        for a, b, mark, t in movers:
            (x0, y0), (x1, y1) = self.origin(a + 1), self.origin(b + 1)
            e = t * t  # accelerating, like a drop
            x, y = round(x0 + (x1 - x0) * e), round(y0 + (y1 - y0) * e)
            if y > y0 + 4:  # speed lines trailing above the piece
                streak = "#B8C6FF" if mark == 1 else "#F6B9DF"
                for dx in (-40, 0, 40):
                    d.line((x + 120 + dx, max(y0 + 40, y - 30), x + 120 + dx, y + 40), fill=streak, width=6)
            self.mark(canvas, x, y, mark, app.profile.data["theme"], size=130 if b == 4 else 150)

    def game(self, canvas, app, reveal=False):
        game = app.game
        board, lives, movers = self.motion_view(app)
        hidden = game.mode.blind and not reveal and not game.done
        swapping = (game.switch_pair() or ()) if not reveal else ()
        for button in range(1, 10):
            action = button - 1
            x, y = self.origin(button)
            d = ImageDraw.Draw(canvas)
            mark = board[action]
            winning = action in game.winning_cells
            d.rounded_rectangle((x + 6, y + 6, x + 234, y + 234), radius=12,
                                fill="#E3F4E9" if winning else BG,
                                outline=GREEN if winning else ORANGE if action in swapping else "#D5D0CB",
                                width=4 if winning else 6 if action in swapping else 2)
            if app.fade and app.fade[0] == action and not mark and not hidden:
                # A vanished piece blurs and fades out over five frames.
                t = app.fade_step / 5
                ghost = Image.new("RGB", (240, 240), BG)
                self.mark(ghost, 0, 0, app.fade[1], app.profile.data["theme"], size=130 if button == 5 else 150)
                ghost = ghost.filter(ImageFilter.GaussianBlur(2 + 10 * t))
                ghost = Image.blend(ghost, Image.new("RGB", (240, 240), BG), t)
                canvas.paste(ghost.crop((20, 36, 220, 196)), (x + 20, y + 36))
            self.text(d, (x + 215, y + 24), str(button), 17, "#98938F")
            if action in swapping:
                self.text(d, (x + 120, y + 26), "교환 예정", 17, ORANGE)
            # Blind shows only the piece just placed, and only during the reveal window.
            if mark and (not hidden or (app.blind_visible and action == game.last_action)):
                animation = app.nine_switch
                if animation is not None and animation["phase"] == "switching":
                    progress = animation["progress"]
                    icon = self.icons[app.profile.data["theme"], "o" if (mark if progress < 0.5 else -mark) == 1 else "x"]
                    if button == 5:
                        icon = ImageOps.contain(icon, (130, 130), Image.Resampling.LANCZOS)
                    width = max(1, round(icon.width * abs(1 - 2 * progress)))
                    icon = icon.resize((width, icon.height), Image.Resampling.LANCZOS)
                    canvas.paste(icon, (x + (240 - width) // 2, y + 38), icon)
                else:
                    self.mark(canvas, x, y, mark, app.profile.data["theme"], size=130 if button == 5 else 150)
                if app.settings["show_lifetime"] and action in lives:
                    self.text(d, (x + 29, y + 25), str(lives[action]), 23, PINK if lives[action] == 1 else BLUE)
            elif not mark and not hidden and action == game.last_action:
                self.text(d, (x + 120, y + 110), "", 26)
            if button == 5:
                if app.nine_switch is not None:
                    if app.nine_switch["phase"] == "placed":
                        self.piece_text(canvas, (x + 120, y + 201), -game.turn, app.profile.data["theme"], "착수!", 19, icon_size=48)
                    else:
                        self.text(d, (x + 120, y + 201), "말 스위칭 중", 19, RED)
                elif game.done:
                    self.result_message(canvas, (x + 120, y + 201), app, 19, icon_size=48)
                elif app.notice:
                    self.text(d, (x + 120, y + 201), app.notice, 19)
                else:
                    status = ("AI 차례" if app.is_ai_turn() else "내 차례") if app.settings["opponent"] == "ai" else "차례"
                    self.piece_text(canvas, (x + 120, y + 201), game.turn, app.profile.data["theme"], status, 19, icon_size=48)
                self.text(d, (x + 120, y + 231), "5 길게: 일시정지", 12, "#76716D")
            elif button == 1:
                self.text(d, (x + 120, y + 219), game.mode.title, 16, "#76716D")
            elif button == 9 and game.mode.clear_every and not game.done:
                left = game.mode.clear_every - game.moves % game.mode.clear_every
                self.text(d, (x + 120, y + 216), f"아래줄 삭제까지 {left}수", 20, countdown_color(left, game.mode.clear_every))
            elif button == 9 and hidden:
                self.text(d, (x + 120, y + 219), "방금 둔 말 공개 중" if app.blind_visible else "기억하세요", 16, "#76716D")
        if not hidden:
            self.draw_movers(canvas, app, movers)

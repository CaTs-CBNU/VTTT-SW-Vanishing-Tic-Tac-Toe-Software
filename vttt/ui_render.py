"""Image-first layouts matching UI예시.pdf; text-only Wi-Fi panels."""

from PIL import Image, ImageDraw
from .profile import THEMES
from .connectivity_ui import SYMBOLS, NETWORK_SLOTS

BG = '#F7F3EF'
SHOP_THEMES = ('fishcat', 'squirrel', 'xmas', 'default', 'chiikawa1', 'chiikawa2')


def image_tile(renderer, canvas, button, name, selected=False):
    canvas.paste(renderer.art[name], renderer.origin(button))
    if selected:
        x, y = renderer.origin(button)
        ImageDraw.Draw(canvas).rectangle((x+3, y+3, x+236, y+236), outline='#5579FF', width=5)


def draw_grid(canvas):
    d = ImageDraw.Draw(canvas)
    for edge in (240, 480):
        d.line((edge, 0, edge, 719), fill='#061B29', width=6)
        d.line((0, edge, 719, edge), fill='#061B29', width=6)
    d.rectangle((0, 0, 719, 719), outline='#061B29', width=6)


def draw_settings(r, canvas, app):
    s = app.settings
    for button, name in ((1, 'go_back_button'),
                         (4, 'settings/game_mode'), (5, 'settings/setting_middle'),
                         (6, 'settings/show_the_life'), (7, 'settings/AI_turn_order'),
                         (8, 'settings/show_rules'), (9, 'settings/check_device')):
        image_tile(r, canvas, button, name)
    d = ImageDraw.Draw(canvas)
    r.text(d, (120, 385), 'AI' if s['opponent'] == 'ai' else '2인 대국', 34)
    r.text(d, (600, 385), '켜짐' if s['show_lifetime'] else '꺼짐', 34)
    local = s['opponent'] == 'local'
    r.text(d, (120, 625), '가위바위보' if local else ('켜짐' if s['human_first'] else '꺼짐'), 30)
    if local:
        x, y = r.origin(7)
        tile = canvas.crop((x, y, x + 240, y + 240)).convert('L').convert('RGB')
        canvas.paste(Image.blend(tile, Image.new('RGB', tile.size, '#989898'), 0.55), (x, y))
    draw_grid(canvas)


def draw_result(r, canvas, app):
    for button, name in ((2, 'result_title'), (4, 're_game_button'),
                         (6, 'change_mode_button'), (7, 'check_the_board'), (8, 'go_to_mainmenu')):
        image_tile(r, canvas, button, 'result/' + name)
    d = ImageDraw.Draw(canvas)
    for button in (1, 3, 9):
        x, y = r.origin(button)
        d.rectangle((x, y, x + 239, y + 239), fill='#545656')
    # Corner tiles show the O/X motif from the supplied layout.
    for x, y, mark in ((-20, -10, 1), (40, 50, -1),
                       (460, 460, -1), (520, 540, 1)):
        r.mark(canvas, x, y, mark, 'default')
    if app.game.winner:
        r.mark(canvas, 480, -10, app.game.winner, app.profile.data['theme'], size=190)
    else:
        d.rectangle((484, 4, 715, 235), fill='#545656')
        r.text(d, (600, 120), '무승부', 40, '#FFFFFF')
    r.result_message(canvas, (360, 330), app, 32, icon_size=72)
    r.text(d, (360, 380), f'{app.game.moves}회 착수', 23)
    r.text(d, (360, 415), f'골드 +{app.last_coins}', 24, '#D6AD24')
    draw_grid(canvas)


def draw_shop(r, canvas, app):
    image_tile(r, canvas, 1, 'go_back_button')
    d = ImageDraw.Draw(canvas)
    d.rectangle((240, 0, 479, 239), fill='#545656')
    d.text((360, 120), '상점', font=r.font(90), anchor='mm', fill='#FFCC25',
           stroke_width=7, stroke_fill='#FFFFFF')
    image_tile(r, canvas, 3, 'shop/shop_gold_status')
    r.text(ImageDraw.Draw(canvas), (600, 170), str(app.profile.data['coins']), 36, '#D6AD24')
    for b, key in zip((4, 5, 6), [SHOP_THEMES[(app.shop_page+i)%len(SHOP_THEMES)] for i in range(3)]):
        x, y = r.origin(b)
        for mark, dx, dy in (('o', 16, 12), ('x', 124, 12), ('x', 16, 108), ('o', 124, 108)):
            icon = r.icons[key, mark].resize((100, 100), Image.Resampling.LANCZOS)
            canvas.paste(icon, (x+dx, y+dy), icon)
        if app.shop_selected == key:
            d = ImageDraw.Draw(canvas)
            # Yellow dashed frame around the selected theme.
            for offset in range(8, 232, 30):
                d.line((x+offset, y+6, x+min(offset+14, 232), y+6), fill='#FFCC25', width=10)
                d.line((x+offset, y+234, x+min(offset+14, 232), y+234), fill='#FFCC25', width=10)
                d.line((x+6, y+offset, x+6, y+min(offset+14, 232)), fill='#FFCC25', width=10)
                d.line((x+234, y+offset, x+234, y+min(offset+14, 232)), fill='#FFCC25', width=10)
            r.text(d, (x+120, y+216), THEMES[key][0], 27, '#061B29')
    image_tile(r, canvas, 7, 'shop/shop_left_button')
    image_tile(r, canvas, 9, 'shop/shop_right_button')
    key = app.shop_selected
    d = ImageDraw.Draw(canvas)
    if key:
        owned = key in app.profile.data['owned']
        r.text(d, (360, 555), '보유 중' if owned else f'{THEMES[key][1]}골드', 37, '#061B29')
        r.text(d, (360, 635), '적용' if owned else '구매', 66, '#FFCC25')
    else:
        r.text(d, (360, 590), '테마 선택', 35)
    if app.notice:
        r.strip(canvas, 2, app.notice, '#E965B9')
    draw_grid(canvas)


def draw_setup(r, canvas, app):
    image_tile(r, canvas, 1, 'go_back_button')
    image_tile(r, canvas, 2, 'level_selection_title')
    for b, key, name in ((4, 'easy', 'easy_level_button'), (5, 'normal', 'medium_level_button'),
                         (6, 'hard', 'high_level_button')):
        image_tile(r, canvas, b, name, app.pending_difficulty == key)
    r.tile(canvas, 7, '지움')
    image_tile(r, canvas, 8, 'select_button')


def draw_rps(r, canvas, app):
    image_tile(r, canvas, 1, 'go_back_button')
    image_tile(r, canvas, 2, ('sissor_button', 'rock_button', 'paper_button')[app.rps_spin if app.rps_choice is None else app.rps_choice])
    for b, name in ((4, 'sissor_text'), (5, 'rock_text'), (6, 'paper_text'),
                    (7, 'sissor_button'), (8, 'rock_button'), (9, 'paper_button')):
        image_tile(r, canvas, b, name)
    if app.screen == 'rps_result':
        r.strip(canvas, 2, '')
        r.piece_text(canvas, (360, 219), 1, app.profile.data['theme'],
                     '선공' if app.settings['opponent'] == 'local' else
                     '내가 먼저 둬요' if app.rps_human_first else 'AI가 먼저 둬요', 17)
    elif app.notice:
        r.strip(canvas, 2, app.notice)


def draw_duel(r, canvas, app):
    """Two-player RPS; player pieces are assigned once the first mover is decided."""
    hands = ('sissor_button', 'rock_button', 'paper_button')
    show = app.screen == 'duel_result' or app.duel_phase < 0  # reveal only after both chose
    picks = app.duel_picks
    for b, hand in ((3, 0), (2, 1), (1, 2)):
        canvas.paste(r.art[hands[hand]].rotate(180), r.origin(b))
        if show and picks['top'] == hand:
            x, y = r.origin(b)
            ImageDraw.Draw(canvas).rectangle((x+3, y+3, x+236, y+236), outline='#5579FF', width=5)
    for b, hand in ((7, 0), (8, 1), (9, 2)):
        image_tile(r, canvas, b, hands[hand], show and picks['bottom'] == hand)
    image_tile(r, canvas, 4, 'go_back_button')
    x, y = r.origin(5)
    d = ImageDraw.Draw(canvas)
    if app.screen == 'duel_result':
        r.tile(canvas, 5, '', (app.duel_reason,) if app.duel_reason else ())
        r.piece_text(canvas, (x + 120, y + 44), 1, app.profile.data['theme'], '먼저!', 31)
        r.text(d, (x + 120, y + 155), '아래쪽 선공' if app.rps_human_first else '위쪽 선공', 23)
    elif app.duel_phase < 0:
        r.text(d, (x + 120, y + 120), app.notice or '준비', 30)
    else:
        r.text(d, (x + 120, y + 112), ('3', '2', '1', '눌러!', '')[app.duel_phase],
               110 if app.duel_phase < 3 else 64, '#E5383B' if app.duel_phase == 3 else '#45494C')
    r.tile(canvas, 6, '가위바위보', ('위쪽 플레이어', '아래쪽 플레이어', '눌러! 때 1초 안에')
           if app.screen != 'duel_result' else ('', '', '눌러! 때 1초 안에'))
    if app.screen == 'duel_result':
        bottom_mark = 1 if app.rps_human_first else -1
        for cy, mark, prefix in ((338, -bottom_mark, '위: '), (368, bottom_mark, '아래: ')):
            r.piece_text(canvas, (600, cy), mark, app.profile.data['theme'], '', 23, prefix=prefix)


def draw_connectivity(r, canvas, app):
    ui, screen = app.connectivity, app.screen
    art = lambda b, name, selected=False: image_tile(r, canvas, b, name, selected)
    tile = lambda b, title, lines=(), **kw: r.tile(canvas, b, title, lines, **kw)
    def character(b, label, footer):
        tile(b, '', footer=footer)
        x, y = r.origin(b)
        r.text(ImageDraw.Draw(canvas), (x+120,y+112), label, 68)

    if screen in ('communication', 'connection', 'room_create', 'room_search'):
        art(1, 'go_back_button'); art(3, 'network_setting_button')
        if screen == 'communication':
            art(2, 'multiplay_title')
            art(4, 'local_multi_button', ui.mode == 'local')
            art(5, 'multiplay_icon')
            art(6, 'online_multi_button', ui.mode == 'online')
            art(7, 'local_multi_info'); art(8, 'select_button'); art(9, 'online_multi_info')
            r.strip(canvas, 5, 'UI 데모 · 실제 통신 준비 중')
        else:
            art(2, ui.mode + '_multi_title')
            if screen == 'connection':
                art(4, 'create_room_button_' + ui.mode)
                art(5, 'search_room_button_' + ui.mode)
                r.strip(canvas, 7, 'UI 데모 · 실제 연결 없음')
            elif not ui.room_ready:
                art(5, 'making_room_status' if screen == 'room_create' else 'searching_room_status')
                art(8, 'multi_game_disabled_button')
                r.strip(canvas, 5, '예시 화면 표시 중')
            else:
                art(5, 'making_room_status' if screen == 'room_create' else 'searching_room_status')
                # Dynamic room text replaces only the blank lower part of the status asset.
                x,y=r.origin(5);d=ImageDraw.Draw(canvas)
                d.rectangle((x+4,y+90,x+235,y+236),fill=BG)
                r.text(d,(x+120,y+127),f'방 번호: {ui.room_number:03}',25)
                r.text(d,(x+120,y+190),'대기 중 (예시)' if screen == 'room_create' else '예시 방 · 실제 상대 없음',19)
                art(8, 'multi_game_disabled_button' if screen == 'room_create' else 'enter_button')
                art(9, 'resetting_room_number_button' if screen == 'room_create' else 're_search_button')
                r.strip(canvas, 7, 'UI 데모 · 실제 연결 없음')
        if app.notice: r.strip(canvas, 5, app.notice)
        return
    if screen in ('wifi_scan', 'wifi_scanning'):
        tile(1, '← 돌아가기')
        tile(2, 'Wi-Fi 선택', ('UI 데모 · 예시 목록', '네트워크 버튼을 누르세요'), footer=f'{ui.scan_page+1} / 3')
        tile(3, '다시 검색', ('실제 검색은 하지 않음',))
        if screen == 'wifi_scanning':
            tile(5, '검색 중…', ('예시 목록 준비 중',))
        else:
            for b, net in zip(NETWORK_SLOTS, ui.networks):
                tile(b, '잠금' if net.secured else '개방', ('', '비밀번호 필요' if net.secured else '비밀번호 없음'), footer='예시 네트워크')
                # Clip the marquee to a single physical LCD.
                x,y=r.origin(b);strip=Image.new('RGB',(212,38),BG);d=ImageDraw.Draw(strip)
                font=r.font(24);width=d.textlength(net.ssid,font=font)
                offset=int(app.clock()*32) % (int(width)+60) if width>212 else 0
                d.text((-offset,1),net.ssid,font=font,fill='#45494C')
                if width>212:d.text((int(width)+60-offset,1),net.ssid,font=font,fill='#45494C')
                canvas.paste(strip,(x+14,y+80))
        tile(7,'◀ 이전 목록',footer='첫 목록' if ui.scan_page==0 else '')
        tile(9,'다음 목록 ▶',footer='마지막 목록' if ui.scan_page==2 else '')
    elif screen == 'wifi_password':
        tile(1,'← 취소',('네트워크 목록으로',))
        tile(2,'입력 내용', (ui.masked_password or '(비어 있음)', f'{len(ui.password)} / 63자'),
             footer='대문자 ABC' if ui.uppercase else '소문자 abc')
        tile(3,'연결',('UI 데모', '실제 연결 없음'))
        for b,label in ((4,'A~I' if ui.uppercase else 'a~i'),(5,'J~R' if ui.uppercase else 'j~r'),(6,'S~Z' if ui.uppercase else 's~z')):
            tile(b,label,('문자 그룹 선택',))
        tile(7,'소문자로 전환' if ui.uppercase else '대문자로 전환',footer='현재: ABC' if ui.uppercase else '현재: abc')
        tile(8,'숫자·기호',('숫자 / 기호 / 공백',))
        tile(9,'한 글자 삭제')
        r.strip(canvas,1,ui.network.ssid)
    elif screen == 'wifi_chars':
        for b in range(1,10):
            character(b,ui.characters[b-1] if b<=len(ui.characters) else '',
                      ('ABC' if ui.uppercase else 'abc') + ' · 아무 버튼 길게: 취소')
    elif screen == 'wifi_symbols':
        for b in range(1,7):
            c=ui.symbols[b-1] if b<=len(ui.symbols) else None
            character(b,'공백' if c==' ' else c or '', '아무 버튼 길게: 취소')
        tile(7,'◀ 이전',footer=f'{ui.symbol_page+1} / {(len(SYMBOLS)+5)//6}')
        tile(8,'그룹 선택으로',('문자 입력 취소',))
        tile(9,'다음 ▶')
    elif screen == 'wifi_connecting':
        tile(1,'← 취소')
        tile(2,'연결 중…',('UI 데모 · 실제 연결 없음',))
        tile(4,'성공 화면 보기',('데모 결과 선택',))
        tile(5,'Wi-Fi 연결',('연결 과정을 표시합니다',),footer='기본: 실패 예시로 이동')
        tile(6,'실패 화면 보기',('데모 결과 선택',))
    elif screen == 'wifi_result':
        tile(1,'← 돌아가기',('통신 화면으로',))
        tile(2,'연결 성공 (예시)' if ui.result=='success' else '연결 실패 (예시)',('UI 데모 · 실제 연결 없음',))
        tile(4,'비밀번호 수정',('입력 내용 유지',) if ui.network.secured else ('개방형 네트워크',))
        tile(5,'다시 연결',('예시 연결 화면으로',))
        tile(6,'실패 화면 보기' if ui.result=='success' else '성공 화면 보기',('데모 결과 전환',))
        tile(8,'다른 네트워크 선택',('예시 목록으로',))
    if app.notice:r.strip(canvas,2,app.notice)

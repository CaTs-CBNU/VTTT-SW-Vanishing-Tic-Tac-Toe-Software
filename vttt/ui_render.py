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


def draw_shop(r, canvas, app):
    image_tile(r, canvas, 1, 'go_back_button')
    # Existing menu artwork supplies the shop heading.
    canvas.paste(r.pages['menu'].crop((240, 0, 480, 240)), (240, 0))
    r.tile(canvas, 3, '골드', (str(app.profile.data['coins']),), accent='#D6AD24')
    for b, key in zip((4, 5, 6), [SHOP_THEMES[(app.shop_page+i)%len(SHOP_THEMES)] for i in range(3)]):
        name, price = THEMES[key]
        r.tile(canvas, b, name, selected=app.shop_selected == key,
               footer='보유' if key in app.profile.data['owned'] else f'{price} 골드')
        x, y = r.origin(b)
        for mark, dx in (('o', 20), ('x', 126)):
            icon = r.icons[key, mark].resize((94, 94))
            canvas.paste(icon, (x+dx, y+82))
    r.tile(canvas, 7, '◀', ('이전 테마',))
    key = app.shop_selected
    title = ('적용' if key in app.profile.data['owned'] else f'{THEMES[key][1]}골드 구매') if key else '테마 선택'
    r.tile(canvas, 8, title, (THEMES[key][0] if key else '위에서 골라주세요',), selected=bool(key))
    r.tile(canvas, 9, '▶', (f'{app.shop_page+1} / {len(SHOP_THEMES)}', '다음 테마'))


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
        r.strip(canvas, 2, '1P 선공' if app.settings['opponent'] == 'local' and app.rps_human_first else
                '2P 선공' if app.settings['opponent'] == 'local' else
                '내가 먼저 둬요' if app.rps_human_first else 'AI가 먼저 둬요')
    elif app.notice:
        r.strip(canvas, 2, app.notice)


def draw_duel(r, canvas, app):
    """2-player RPS: 2P on the top row (drawn upside down for them), 1P on the bottom row."""
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
        r.tile(canvas, 5, '1P 먼저!' if app.rps_human_first else '2P 먼저!', (app.duel_reason,) if app.duel_reason else ())
    elif app.duel_phase < 0:
        r.text(d, (x + 120, y + 120), app.notice or '준비', 30)
    else:
        r.text(d, (x + 120, y + 112), ('3', '2', '1', '눌러!', '')[app.duel_phase],
               110 if app.duel_phase < 3 else 64, '#E5383B' if app.duel_phase == 3 else '#45494C')
    r.tile(canvas, 6, '가위바위보', ('위: 2P', '아래: 1P', '눌러! 때 1초 안에'))


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

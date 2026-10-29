"""Live local-network and NetworkManager screens, using the nine-display layout."""
from PIL import Image, ImageDraw
from .ui_render import image_tile


def draw_lan(r, canvas, app):
    lan, screen = app.lan, app.screen
    image_tile(r, canvas, 1, 'go_back_button')
    def room_tile(button, number, footer):
        r.tile(canvas, button, '방 번호', footer=footer)
        x, y = r.origin(button)
        r.text(ImageDraw.Draw(canvas), (x + 120, y + 128), number, 68)
    if screen == 'lan_search':
        r.tile(canvas, 2, '방 찾기', ('같은 Wi-Fi의 방',))
        r.tile(canvas, 3, '다시 검색')
        rooms = lan.rooms[lan.room_page * 4:lan.room_page * 4 + 4]
        for button, room in zip((4, 5, 6, 8), rooms):
            room_tile(button, room.number, '눌러서 입장 확인')
        if not rooms:
            r.tile(canvas, 5, '검색 중', (lan.error or '방장이 방을 만들어야', '목록에 표시됩니다'))
        r.tile(canvas, 7, '이전 목록')
        r.tile(canvas, 9, '다음 목록', (f'{lan.room_page + 1} / {max(1, (len(lan.rooms) + 3) // 4)}',))
    elif screen == 'lan_confirm':
        r.tile(canvas, 2, '입장 확인')
        room_tile(5, lan.selected_room.number, '이 방이 맞나요?')
        image_tile(r, canvas, 8, 'enter_button')
    elif screen in ('lan_lobby', 'lan_wait'):
        r.tile(canvas, 2, '로컬 통신', ('같은 Wi-Fi로 대국',))
        number = lan.link.room.number if lan.link else ''
        room_tile(5, number, '상대 입장을 기다립니다' if screen == 'lan_lobby' else
                  '방장이 모드를 고릅니다' if lan.synced else '방에 연결 중입니다')
    elif screen == 'lan_rps':
        r.tile(canvas, 2, '선공 정하기', ('가위바위보',))
        hands = ('sissor_button', 'rock_button', 'paper_button')
        for button, name in zip((7, 8, 9), hands):
            image_tile(r, canvas, button, name)
        if lan.other_pick is not None:
            image_tile(r, canvas, 4, hands[lan.other_pick])
            r.strip(canvas, 4, '상대의 선택')
        else:
            r.tile(canvas, 4, '상대', ('선택 완료' if lan.opponent_ready else '선택을 기다리는 중',))
        if lan.my_pick is not None:
            image_tile(r, canvas, 5, hands[lan.my_pick])
            r.strip(canvas, 5, '내 선택')
        else:
            r.tile(canvas, 5, '내 선택', ('아래 버튼에서', '가위 / 바위 / 보'))
        if lan.phase == 'rps_tie':
            r.tile(canvas, 6, '무승부', ('잠시 후 다시 선택',))
        elif lan.phase == 'rps_result':
            r.tile(canvas, 6, '선공 결정')
            r.piece_text(canvas, (600, 370), 1, app.profile.data['theme'],
                         '내가 먼저' if app.human_mark == 1 else '상대가 먼저', 24, icon_size=42)
        else:
            r.tile(canvas, 6, '선택 안내', ('양쪽이 선택하면', '결과를 공개합니다'))
    elif screen == 'lan_closed':
        r.tile(canvas, 5, '대국 연결 종료', ('상대가 방을 나갔습니다', '돌아가서 새 방을 찾으세요'))


def draw_reconnect(r, canvas, app):
    canvas.paste(Image.blend(canvas, Image.new('RGB', canvas.size, '#000000'), .65))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((248, 250, 472, 470), radius=16, fill='#F7F3EF', outline='#E5383B', width=4)
    r.text(d, (360, 290), '통신 연결 끊김', 25, '#B73159')
    r.text(d, (360, 335), '상대 연결을 확인 중', 20)
    r.text(d, (360, 381), '재연결 중' + '.' * (int(app.clock() * 2) % 4), 27, '#3156C4')
    r.text(d, (360, 437), '복구되면 이어서 진행해요', 17)


def draw_wifi_real(r, canvas, app):
    ui, screen = app.connectivity, app.screen
    if screen in ('wifi_chars', 'wifi_symbols'):
        return False
    image_tile(r, canvas, 1, 'go_back_button')
    if screen in ('wifi_scan', 'wifi_scanning'):
        r.tile(canvas, 2, 'Wi-Fi 선택', ('사용할 공유기를 누르세요',), footer=f'{ui.scan_page + 1} / {max(1, (len(ui.available_networks) + 3) // 4)}')
        r.tile(canvas, 3, '다시 검색')
        if screen == 'wifi_scanning':
            r.tile(canvas, 5, '검색 중' + '.' * (int(app.clock() * 2) % 4), ('무선 LAN을 확인합니다',))
        elif not ui.networks:
            r.tile(canvas, 5, '검색 결과 없음', (ui.error or '공유기를 찾지 못했습니다', 'Wi-Fi 설정을 확인하세요'))
        else:
            for button, network in zip((4, 5, 6, 8), ui.networks):
                r.tile(canvas, button, '연결됨' if network.active else '잠금' if network.secured else '개방',
                       (network.ssid, f'신호 {network.signal}%'), footer='눌러서 연결')
        r.tile(canvas, 7, '이전 목록')
        r.tile(canvas, 9, '다음 목록')
    elif screen == 'wifi_password':
        r.tile(canvas, 2, '비밀번호 입력', (ui.masked_password or '(비어 있음)', f'{len(ui.password)} / 63자'),
               footer='대문자 ABC' if ui.uppercase else '소문자 abc')
        r.tile(canvas, 3, '연결', (ui.network.ssid,))
        for button, title in ((4, 'A~I' if ui.uppercase else 'a~i'), (5, 'J~R' if ui.uppercase else 'j~r'),
                              (6, 'S~Z' if ui.uppercase else 's~z')):
            r.tile(canvas, button, title, ('문자 그룹 선택',))
        r.tile(canvas, 7, '소문자로 전환' if ui.uppercase else '대문자로 전환')
        r.tile(canvas, 8, '숫자 / 기호', ('공백도 입력 가능',))
        r.tile(canvas, 9, '한 글자 삭제')
    elif screen == 'wifi_connecting':
        r.tile(canvas, 2, '연결 중' + '.' * (int(app.clock() * 2) % 4))
        r.tile(canvas, 5, 'Wi-Fi 연결', (ui.network.ssid, '최대 40초 정도 걸립니다'))
        r.strip(canvas, 1, '눌러서 취소')
    elif screen == 'wifi_result':
        r.tile(canvas, 2, '연결 성공' if ui.result == 'success' else '연결 실패')
        r.tile(canvas, 5, ui.network.ssid, ('Wi-Fi에 연결되었습니다',) if ui.result == 'success' else (ui.error,))
        if ui.result != 'success':
            r.tile(canvas, 4, '비밀번호 다시 입력', ('이전 비밀번호는 지웠어요',))
            r.tile(canvas, 6, '다시 시도', ('4번에서 비밀번호 입력',))
        r.tile(canvas, 8, '다른 네트워크 선택')
    if app.notice:
        r.strip(canvas, 2, app.notice)
    return True

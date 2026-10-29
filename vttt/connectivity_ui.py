"""Offline connectivity screens. No sockets, system commands or credential storage."""

from dataclasses import dataclass
import string


@dataclass(frozen=True)
class DemoNetwork:
    ssid: str
    secured: bool = True


DEMO_NETWORKS = (
    DemoNetwork('공유기 A'), DemoNetwork('공유기 B'), DemoNetwork('공유기 C', False),
    DemoNetwork('공유기 D'), DemoNetwork('VTTT_Long_Network_Name_For_Scrolling_123'),
    DemoNetwork('게스트 Wi-Fi', False), DemoNetwork('공유기 E'), DemoNetwork('공유기 F'),
    DemoNetwork('공유기 G'),
)
# Six symbols plus three navigation keys on every page; includes ASCII space.
SYMBOLS = string.digits + string.punctuation + ' '
NETWORK_SLOTS = (4, 5, 6, 8)
SYMBOL_SLOTS = (1, 2, 3, 4, 5, 6)


class ConnectivityUI:
    """State used only to preview physical-button navigation."""
    def __init__(self, app):
        self.app = app
        self.mode = 'local'
        self.room_number = 123
        self.room_ready = False
        self.scan_page = 0
        self.network = None
        self.password = ''
        self.uppercase = False
        self.characters = ''
        self.symbol_page = 0
        self.last_character_until = 0
        self.deadline = None
        self.result = 'failure'
        self.return_screen = 'communication'
        self.animation_step = -1

    @property
    def networks(self):
        return DEMO_NETWORKS[self.scan_page * 4:self.scan_page * 4 + 4]

    @property
    def symbols(self):
        return SYMBOLS[self.symbol_page * 6:self.symbol_page * 6 + 6]

    @property
    def masked_password(self):
        # A bounded tail keeps the most recently entered character visible.
        tail = '•' * len(self.password)
        if self.password and self.app.clock() < self.last_character_until:
            tail = tail[:-1] + self.password[-1]
        return ('…' if len(tail) > 10 else '') + tail[-10:]

    def forget(self):
        self.password = ''
        self.last_character_until = 0
        self.characters = ''

    def open_wifi(self):
        self.return_screen = self.app.screen
        self.forget()
        self.scan_page = 0
        self.app.go('wifi_scan')

    def leave_wifi(self):
        self.forget()
        self.app.go(self.return_screen)
        if self.return_screen in ('room_create', 'room_search') and not self.room_ready:
            self.deadline = self.app.clock() + .8

    def scan(self):
        self.scan_page = 0
        self.deadline = self.app.clock() + .8
        self.app.go('wifi_scanning')

    def connect(self):
        self.last_character_until = 0
        self.deadline = self.app.clock() + 1.5
        self.app.go('wifi_connecting')

    def add_character(self, char):
        if len(self.password) >= 63:
            self.app.message('최대 63자까지 입력할 수 있습니다')
        else:
            self.password += char
            self.last_character_until = self.app.clock() + 1.2
        self.app.go('wifi_password')

    def handle(self, event):
        app, screen, b = self.app, self.app.screen, event.button
        if screen not in ('communication', 'connection', 'room_create', 'room_search',
                          'wifi_scan', 'wifi_scanning', 'wifi_password', 'wifi_chars',
                          'wifi_symbols', 'wifi_connecting', 'wifi_result'):
            return False
        if event.kind == 'long':
            if screen in ('wifi_chars', 'wifi_symbols'):
                self.characters = ''
                app.go('wifi_password')
            return True
        if event.kind != 'short':
            return True
        if screen == 'communication':
            if b == 1: app.go('menu')
            elif b == 3: self.open_wifi(); self.scan()
            elif b in (4, 6):
                self.mode = 'local' if b == 4 else 'online'
                app.go('connection')
        elif screen in ('connection', 'room_create', 'room_search'):
            if b == 1:
                app.go('communication' if screen == 'connection' else 'connection')
            elif b == 3:
                self.open_wifi(); self.scan()
            elif screen == 'connection' and b in (4, 5):
                self.room_ready = False
                self.deadline = app.clock() + .8
                app.go('room_create' if b == 4 else 'room_search')
            elif screen == 'room_create' and b == 9:
                self.room_number = self.room_number % 999 + 1
                self.room_ready = False
                self.deadline = app.clock() + .8
                app.touch()
            elif screen == 'room_search' and b == 9:
                self.room_ready = False
                self.deadline = app.clock() + .8
                app.touch()
            elif b == 8 and self.room_ready:
                app.message('UI 데모 · 상대 연결과 게임 시작은 준비 중입니다')
        elif screen in ('wifi_scan', 'wifi_scanning'):
            if b == 1:
                self.leave_wifi()
            elif b == 3: self.scan()
            elif screen == 'wifi_scan':
                if b in (7, 9):
                    last = (len(DEMO_NETWORKS) - 1) // 4
                    self.scan_page = max(0, min(last, self.scan_page + (-1 if b == 7 else 1)))
                    app.touch()
                elif b in NETWORK_SLOTS:
                    index = NETWORK_SLOTS.index(b)
                    if index < len(self.networks):
                        self.network = self.networks[index]
                        self.forget(); self.uppercase = False
                        if self.network.secured: app.go('wifi_password')
                        else: self.connect()
        elif screen == 'wifi_password':
            if b == 1:
                self.forget(); app.go('wifi_scan')
            elif b == 3: self.connect()
            elif b in (4, 5, 6):
                self.characters = ('abcdefghi', 'jklmnopqr', 'stuvwxyz')[b - 4]
                if self.uppercase: self.characters = self.characters.upper()
                app.go('wifi_chars')
            elif b == 7:
                self.uppercase = not self.uppercase; app.touch()
            elif b == 8:
                self.symbol_page = 0; app.go('wifi_symbols')
            elif b == 9:
                self.password = self.password[:-1]; self.last_character_until = 0; app.touch()
        elif screen == 'wifi_chars':
            if 1 <= b <= len(self.characters): self.add_character(self.characters[b - 1])
        elif screen == 'wifi_symbols':
            if b == 7:
                self.symbol_page = (self.symbol_page - 1) % ((len(SYMBOLS) + 5) // 6); app.touch()
            elif b == 9:
                self.symbol_page = (self.symbol_page + 1) % ((len(SYMBOLS) + 5) // 6); app.touch()
            elif b == 8: app.go('wifi_password')
            elif b in SYMBOL_SLOTS and b <= len(self.symbols): self.add_character(self.symbols[b - 1])
        elif screen == 'wifi_connecting':
            if b == 1: app.go('wifi_password' if self.network.secured else 'wifi_scan')
            elif b in (4, 6):
                self.result = 'success' if b == 4 else 'failure'; app.go('wifi_result')
        elif screen == 'wifi_result':
            if b == 1:
                self.leave_wifi()
            elif b == 4:
                app.go('wifi_password' if self.network.secured else 'wifi_scan')
            elif b == 5: self.connect()
            elif b == 6:
                self.result = 'success' if self.result == 'failure' else 'failure'; app.touch()
            elif b == 8:
                self.forget(); app.go('wifi_scan')
        return True

    def tick(self):
        app, now = self.app, self.app.clock()
        if self.deadline is not None and now >= self.deadline:
            self.deadline = None
            if app.screen == 'wifi_scanning': app.go('wifi_scan')
            elif app.screen == 'wifi_connecting':
                self.result = 'failure'; app.go('wifi_result')
            elif app.screen in ('room_create', 'room_search'):
                self.room_ready = True; app.touch()
        step = int(now * 5)
        if app.screen in ('wifi_scan', 'wifi_password') and step != self.animation_step:
            self.animation_step = step
            app.touch()

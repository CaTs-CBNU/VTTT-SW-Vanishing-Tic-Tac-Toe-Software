"""Host-authoritative two-device matches; presentation remains device-local."""
from dataclasses import asdict, fields
import time
import uuid

from .lan_transport import Discovery, LanLink, Room
from .rules import Game, MODES


def game_to_wire(game):
    return asdict(game) if game else None


def game_from_wire(value):
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(Game)}:
        raise ValueError('bad game snapshot')
    value = dict(value)
    if (value['mode_key'] not in MODES or type(value['moves']) is not int or
            not 0 <= value['moves'] <= 10000 or type(value['max_moves']) is not int or
            not 9 <= value['max_moves'] <= 10000 or len(value['board']) != 9 or
            any(type(mark) is not int or mark not in (-1, 0, 1) for mark in value['board']) or
            value['turn'] not in (-1, 1) or value['winner'] not in (-1, 0, 1)):
        raise ValueError('bad game snapshot')
    value['queues'] = {int(p): list(q) for p, q in value['queues'].items()}
    if set(value['queues']) != {1, -1}:
        raise ValueError('bad queues')
    seen = []
    for player, cells in value['queues'].items():
        if any(type(cell) is not int or not 0 <= cell < 9 or value['board'][cell] != player for cell in cells):
            raise ValueError('bad queues')
        seen += cells
    if len(seen) != len(set(seen)) or set(seen) != {i for i, mark in enumerate(value['board']) if mark}:
        raise ValueError('bad queues')
    for key in ('switch_turns', 'winning_cells', 'vanished'):
        value[key] = tuple(value[key])
    for key in ('fell', 'drops'):
        value[key] = tuple(tuple(pair) for pair in value[key])
    return Game(**value)


class LanController:
    def __init__(self, app):
        self.app = app
        self.discovery = None
        self.link = None
        self.active = False
        self.synced = False
        self.phase = 'lobby'
        self.stage = 0
        self.revision = 0
        self.mode = 'vanishing'
        self.match_id = ''
        self.game = None
        self.host_mark = 1
        self.picks = {'host': None, 'guest': None}
        self.ready = {'host': False, 'guest': False}
        self.rematch = {'host': False, 'guest': False}
        self.ack = 0
        self.sequence = 0
        self.pending = {}
        self.stage_started = None
        self.view_key = None
        self.game_view_id = None
        self.view_phase = None
        self.presented_key = None
        self.sent_ready = None
        self.selected_room = None
        self.rooms = []
        self.room_page = 0
        self.error = ''
        self.animation_step = -1
        self.was_disconnected = False
        self.opponent_ready = False
        self.my_pick = None
        self.other_pick = None

    @property
    def role(self):
        return 'host' if self.link and self.link.is_host else 'guest'

    @property
    def reconnecting(self):
        return self.active and self.link is not None and self.link.ever_connected and (not self.link.connected or not self.synced)

    def _discovery(self):
        if self.discovery is None:
            self.discovery = Discovery(self.app.config.get('discovery_port', 44244))
        return self.discovery

    def host(self):
        self.close()
        try:
            self.link = LanLink(host=True)
            self._discovery().advertise(self.link.room)
        except OSError:
            self.close()
            self.app.message('방 생성 실패: 네트워크 권한을 확인하세요')
            return
        self.active, self.synced = True, False
        self.phase, self.stage, self.revision = 'lobby', 0, 0
        self.match_id, self.game = '', None
        self.ack, self.sequence = 0, 0
        self.view_key = self.presented_key = None
        self.app.go('lan_lobby')

    def search(self):
        try:
            self._discovery()
            self.error = ''
        except OSError:
            self.error = '방 검색 실패: 네트워크 권한을 확인하세요'
        self.room_page = 0
        self.app.go('lan_search')

    def join(self, room):
        self.close()
        self.selected_room = room
        self.active, self.synced = True, False
        self.phase, self.stage, self.revision = 'lobby', -1, -1
        self.ack = self.sequence = 0
        self.pending = {}
        self.view_key = self.presented_key = None
        self.link = LanLink(room=room)
        try:
            self._discovery()
        except OSError:
            self.error = '방 재검색을 사용할 수 없습니다'
        self.app.go('lan_wait')

    def close(self):
        if self.link:
            self.link.close()
        if self.discovery:
            self.discovery.close()
        self.link = self.discovery = None
        self.active = self.synced = False
        self.pending = {}
        self.was_disconnected = False

    def _stage(self, phase):
        self.phase = phase
        self.stage += 1
        self.ready = {'host': False, 'guest': False}
        self.stage_started = None

    def _snapshot(self, role):
        reveal = self.phase in ('rps_tie', 'rps_result')
        other = 'guest' if role == 'host' else 'host'
        return dict(type='state', revision=self.revision, stage=self.stage, phase=self.phase,
                    mode=self.mode, match_id=self.match_id, game=game_to_wire(self.game),
                    host_mark=self.host_mark, ready=self.ready, rematch=self.rematch,
                    ack=self.ack, mine=self.picks[role], other=self.picks[other] if reveal else None,
                    opponent_ready=self.picks[other] is not None)

    def _publish(self):
        self.revision += 1
        self._apply(self._snapshot('host'))
        if self.link and self.link.connected:
            self.link.send(self._snapshot('guest'))

    def command(self, action, **values):
        if not self.active or not self.link.connected or not self.synced:
            return
        message = dict(type='command', action=action, stage=self.stage, match_id=self.match_id,
                       moves=self.game.moves if self.game else 0, **values)
        if self.role == 'host':
            self._command(message, 'host')
        else:
            self.sequence += 1
            message['seq'] = self.sequence
            self.pending[self.sequence] = message
            self.link.send(message)

    def _command(self, message, role):
        if (message.get('stage') != self.stage or message.get('match_id') != self.match_id or
                not self.link.connected):
            return
        action = message.get('action')
        if action == 'ready':
            self.ready[role] = True
        elif action == 'mode' and role == 'host' and self.phase == 'mode' and message.get('mode') in MODES:
            self.mode = message['mode']
            self.match_id = uuid.uuid4().hex
            self.game = None
            self.picks = {'host': None, 'guest': None}
            self._stage('rps')
        elif action == 'hand' and self.phase == 'rps' and self.picks[role] is None:
            hand = message.get('hand')
            if type(hand) is not int or hand not in (0, 1, 2):
                return
            self.picks[role] = hand
            if None not in self.picks.values():
                host, guest = self.picks['host'], self.picks['guest']
                if host == guest:
                    self._stage('rps_tie')
                else:
                    self.host_mark = 1 if (host - guest) % 3 == 1 else -1
                    self._stage('rps_result')
        elif action == 'move' and self.phase == 'game' and self.game and not self.game.done:
            mark = self.host_mark if role == 'host' else -self.host_mark
            if (not all(self.ready.values()) or self.game.turn != mark or
                    message.get('moves') != self.game.moves or type(message.get('cell')) is not int):
                return
            try:
                self.game.play(message['cell'])
            except ValueError:
                return
            self._stage('game')
        elif action == 'pause' and self.phase == 'game' and all(self.ready.values()) and not self.game.done:
            self._stage('pause')
        elif action == 'resume' and self.phase == 'pause':
            self._stage('game')
        elif action == 'rematch' and (self.phase in ('result', 'pause') or
                                     (self.phase == 'game' and self.game.done)):
            self.rematch[role] = True
            if all(self.rematch.values()):
                self.match_id = uuid.uuid4().hex
                self.game = None
                self.picks = {'host': None, 'guest': None}
                self.rematch = {'host': False, 'guest': False}
                self._stage('rps')
        elif action == 'change_mode' and role == 'host' and (self.phase == 'result' or
                                                            (self.phase == 'game' and self.game.done)):
            self._stage('mode')
        else:
            return
        self._publish()

    def _restore(self, game):
        app = self.app
        app.game = game.clone()
        app.mode_key = game.mode_key
        app.fade = app.motion = app.nine_switch = None
        app.gravity_warning = {'shown_at': None, 'action': None} if not game.done and game.clear_due() else None
        app.blind_visible = False if game.mode.blind and game.moves else True
        app.reveal_pending = False
        app.reveal_until = None
        app.result_pending = game.done
        app.result_at = None
        app.go('game')

    def _apply(self, state):
        app = self.app
        phase = state['phase']
        if phase not in ('lobby', 'mode', 'rps', 'rps_tie', 'rps_result', 'game', 'pause', 'result'):
            raise ValueError('bad phase')
        if state['mode'] not in MODES or type(state['stage']) is not int or state['host_mark'] not in (-1, 1):
            raise ValueError('bad state')
        remote = game_from_wire(state['game']) if state['game'] is not None else None
        old_game = app.game
        new_match = state['match_id'] != self.game_view_id
        force = self.was_disconnected
        old_phase = self.view_phase
        self.view_phase = phase
        self.phase, self.stage, self.revision = phase, state['stage'], state['revision']
        self.mode, self.match_id, self.host_mark = state['mode'], state['match_id'], state['host_mark']
        self.ready = dict(state['ready'])
        self.rematch = dict(state['rematch'])
        self.my_pick, self.other_pick = state['mine'], state['other']
        self.opponent_ready = state['opponent_ready']
        self.synced = True
        self.was_disconnected = False
        key = (self.match_id, self.stage)
        changed = key != self.view_key or force
        if changed:
            self.presented_key = self.sent_ready = None
        self.view_key = key
        if self.role != 'host':
            self.game = remote
            self.pending = {seq: msg for seq, msg in self.pending.items() if seq > state['ack']}
        app.human_mark = self.host_mark if self.role == 'host' else -self.host_mark
        app.local_first_mark = app.human_mark
        if remote:
            if new_match or not old_game or old_game.mode_key != remote.mode_key:
                self.game_view_id = self.match_id
                app.mode_key = remote.mode_key
                app.start_game()
                app.human_mark = self.host_mark if self.role == 'host' else -self.host_mark
                app.local_first_mark = app.human_mark
                self._restore(remote)
            elif force or remote.moves < old_game.moves or remote.moves > old_game.moves + 1:
                self._restore(remote)
            elif remote.moves == old_game.moves + 1:
                # Replay the committed move locally to keep gravity/switch animations.
                app.gravity_warning = None
                app.nine_switch = None
                app.make_move(remote.last_action if not remote.mode.gravity else remote.last_action % 3)
                if app.game.key() != remote.key():
                    self._restore(remote)
            if phase == 'pause' and changed:
                app.go('pause')
            elif phase == 'mode' and changed:
                app.go('mode' if self.role == 'host' else 'lan_wait')
            elif phase == 'result' and changed:
                app.go('result')
            elif phase == 'game' and old_phase == 'pause' and changed:
                app.resume()
        elif changed:
            if phase == 'mode':
                app.go('mode' if self.role == 'host' else 'lan_wait')
            elif phase.startswith('rps'):
                app.go('lan_rps')
            elif phase == 'lobby':
                app.go('lan_lobby' if self.role == 'host' else 'lan_wait')
        self._record()
        app.touch()

    def _record(self):
        app = self.app
        if not app.game or not app.game.done or app.recorded:
            return
        try:
            app.last_coins = app.profile.record_network(app.game, app.human_mark, self.match_id)
            app.recorded = True
        except OSError:
            app.message('결과 저장 실패: 다시 시도 중')

    def presented(self):
        if self.active and self.synced and not self.reconnecting:
            self.presented_key = self.view_key

    def _view_ready(self):
        app = self.app
        if self.presented_key != self.view_key:
            return False
        if self.phase == 'game':
            if app.game and app.game.done:
                return app.screen in ('result', 'final_board')
            return not (app.nine_switch or app.motion or app.fade or app.gravity_warning_waiting() or
                        app.reveal_pending or app.reveal_until is not None)
        return True

    def tick(self):
        app = self.app
        if app.screen in ('lan_search', 'lan_confirm') and self.discovery:
            rooms = self.discovery.list_rooms()
            if rooms != self.rooms:
                self.rooms = rooms
                app.touch()
        if not self.active or not self.link:
            return
        if self.role == 'guest' and not self.link.connected and self.discovery:
            endpoint = self.discovery.find_room(self.link.room.id)
            if endpoint:
                self.link.room = endpoint
        for event, message in self.link.poll():
            if event == 'left':
                self.close()
                app.go('lan_closed')
                return
            if event == 'disconnected':
                self.synced = False
                self.was_disconnected = True
                self.ready = {'host': False, 'guest': False}
                self.stage_started = None
                self.presented_key = self.sent_ready = None
                app.touch()
            elif event == 'connected':
                self.synced = True
                self.ready = {'host': False, 'guest': False}
                self.presented_key = self.sent_ready = None
                if self.role == 'host':
                    self._stage('mode' if self.phase == 'lobby' else self.phase)
                    self._publish()
                    room = self.link.room
                    self._discovery().advertise(Room(room.id, room.number, room.host, room.port, False))
                else:
                    self.synced = False  # wait for the authoritative snapshot
            elif event == 'message':
                try:
                    if self.role == 'host' and message.get('type') == 'command':
                        sequence = message.get('seq')
                        if type(sequence) is int and 0 < sequence <= self.ack + 128:
                            if sequence > self.ack:
                                self.ack = sequence
                                self._command(message, 'guest')
                            self._publish()
                    elif self.role == 'guest' and message.get('type') == 'state':
                        if type(message.get('revision')) is int and message['revision'] >= self.revision:
                            resync = not self.synced
                            self._apply(message)
                            if resync:
                                for pending in self.pending.values():
                                    self.link.send(pending)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                    self.link.drop_connection()
        if self.reconnecting:
            step = int(app.clock() * 2) % 4
            if step != self.animation_step:
                self.animation_step = step
                app.animate()
            return
        if not self.synced:
            return
        self._record()
        if self._view_ready() and self.sent_ready != self.view_key:
            self.sent_ready = self.view_key
            self.command('ready')
        if self.role == 'host' and all(self.ready.values()):
            if self.phase in ('rps_tie', 'rps_result'):
                if self.stage_started is None:
                    self.stage_started = app.clock()
                elif app.clock() - self.stage_started >= 1.5:
                    if self.phase == 'rps_tie':
                        self.picks = {'host': None, 'guest': None}
                        self._stage('rps')
                    else:
                        self.game = Game(self.mode, app.config['max_moves'])
                        self.rematch = {'host': False, 'guest': False}
                        self._stage('game')
                    self._publish()
            elif self.phase == 'game' and self.game.done:
                self._stage('result')
                self._publish()

    def handle(self, event):
        app, b = self.app, event.button
        screen = app.screen
        if screen == 'lan_closed':
            if event.kind == 'short' and b == 1:
                app.go('menu')
            return True
        if screen == 'lan_search':
            if event.kind != 'short':
                return True
            if b == 1:
                app.go('connection')
            elif b == 3:
                self.search()
            elif b in (7, 9):
                self.room_page = max(0, min(max(0, (len(self.rooms) - 1) // 4), self.room_page + (-1 if b == 7 else 1)))
                app.touch()
            elif b in (4, 5, 6, 8):
                index = self.room_page * 4 + (4, 5, 6, 8).index(b)
                if index < len(self.rooms):
                    self.selected_room = self.rooms[index]
                    app.go('lan_confirm')
            return True
        if screen == 'lan_confirm':
            if event.kind == 'short':
                if b == 1:
                    app.go('lan_search')
                elif b == 8:
                    self.join(self.selected_room)
            return True
        if not self.active:
            return False
        if event.kind == 'short' and b == 1 and screen in ('lan_lobby', 'lan_wait'):
            self.close()
            app.go('connection')
            return True
        if self.reconnecting or not self.synced:
            return True
        if screen in ('themes', 'help'):
            return False
        if event.kind == 'long' and b == 5 and screen == 'game':
            self.command('pause')
            return True
        if event.kind != 'short':
            return True
        app.flash, app.flash_until = (b,), app.clock() + .15
        app.animate()
        if b == 1 and screen in ('mode', 'lan_wait', 'lan_lobby', 'lan_rps'):
            self.close()
            app.go('connection')
        elif screen == 'mode' and self.role == 'host':
            if b == 3:
                return False
            from .app import MODE_BUTTONS
            if b in MODE_BUTTONS:
                self.command('mode', mode=MODE_BUTTONS[b])
        elif screen == 'lan_rps' and b in (7, 8, 9):
            self.command('hand', hand=b - 7)
        elif screen == 'game':
            if app.game and not app.game.done and app.game.turn == app.human_mark and all(self.ready.values()):
                self.command('move', cell=b - 1)
        elif screen == 'pause':
            if b == 4:
                self.close(); app.go('menu')
            elif b == 5:
                self.command('resume')
            elif b == 6:
                self.command('rematch')
        elif screen == 'result':
            if b == 4:
                self.command('rematch')
                app.message('서로 다시하기를 누르면 시작합니다')
            elif b == 6:
                if self.role == 'host':
                    self.command('change_mode')
                else:
                    app.message('모드 변경은 방장이 선택합니다')
            elif b == 7:
                app.go('final_board')
            elif b == 8:
                self.close(); app.go('menu')
        elif screen == 'final_board':
            app.go('result')
        return True

"""Real loopback TCP/UDP integration, using the same controllers as the Pi."""
from pathlib import Path
import socket
import tempfile
import time
import unittest
from PIL import Image

from vttt.app import Application
from vttt.backends import HeadlessBackend
from vttt.buttons import ButtonEvent
from vttt.config import runtime_config
from vttt.lan import game_from_wire, game_to_wire
from vttt.lan_transport import Discovery, Room
from vttt.rules import Game, MODES


class BlankRenderer:
    def draw(self, app): return Image.new('RGB', (720, 720), '#F7F3EF')


class LanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.apps = []
        for name in ('host', 'guest'):
            config = runtime_config()
            config['profile'] = str(Path(self.temp.name) / (name + '.json'))
            self.apps.append(Application(config, HeadlessBackend(), BlankRenderer(), ai=object()))
        self.host, self.guest = self.apps

    def tearDown(self):
        for app in self.apps: app.close()
        self.temp.cleanup()

    def pump(self, predicate, timeout=6):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for app in self.apps:
                app.tick(); app.present()
            if predicate(): return
            time.sleep(.01)
        self.fail('LAN state did not converge: ' + repr([(a.screen, a.lan.phase, a.lan.ready) for a in self.apps]))

    def connect(self):
        self.host.lan.host()
        self.assertIsNotNone(self.host.lan.link, self.host.notice)
        room = self.host.lan.link.room
        self.guest.lan.join(Room(room.id, room.number, '127.0.0.1', room.port))
        self.pump(lambda: self.host.screen == 'mode' and self.guest.lan.synced)

    def start(self, button=9):
        self.host.handle(ButtonEvent(button, 'short'))
        self.pump(lambda: all(a.lan.phase == 'rps' for a in self.apps))
        self.host.handle(ButtonEvent(8, 'short'))
        self.guest.handle(ButtonEvent(7, 'short'))
        self.pump(lambda: all(a.lan.phase == 'game' and all(a.lan.ready.values()) for a in self.apps))

    def move(self, cell):
        before = self.host.game.moves
        player = next(a for a in self.apps if a.human_mark == a.game.turn)
        player.handle(ButtonEvent(cell + 1, 'short'))
        self.pump(lambda: all(a.game.moves == before + 1 for a in self.apps))
        if not self.host.game.done:
            self.pump(lambda: all(all(a.lan.ready.values()) for a in self.apps))
        self.assertEqual(self.host.game.key(), self.guest.game.key())

    def test_match_reconnect_pause_results_and_rematch(self):
        self.connect(); self.start()
        self.host.handle(ButtonEvent(1, 'short', self.host.accept_after - .1))
        self.assertEqual(self.host.game.moves, 0)
        self.move(0)
        before = self.host.game.key()
        # Keep the reconnect attempt off-line long enough to exercise both overlays.
        original = self.guest.lan.link.room
        self.guest.lan.discovery.close(); self.guest.lan.discovery = None
        self.guest.lan.link.room = Room(original.id, original.number, '127.0.0.1', 1)
        self.guest.lan.link.drop_connection()
        self.pump(lambda: all(a.lan.reconnecting for a in self.apps))
        for app in self.apps:
            app.handle(ButtonEvent(5, 'short'))
            self.assertEqual(app.game.key(), before)
        self.guest.lan.link.room = original
        self.pump(lambda: all(not a.lan.reconnecting and all(a.lan.ready.values()) for a in self.apps))
        self.assertEqual(self.host.game.key(), before)
        self.guest.handle(ButtonEvent(5, 'long'))
        self.pump(lambda: all(a.screen == 'pause' for a in self.apps))
        self.host.handle(ButtonEvent(5, 'short'))
        self.pump(lambda: all(a.screen == 'game' and all(a.lan.ready.values()) for a in self.apps))
        for cell in (3, 1, 4, 2): self.move(cell)
        self.pump(lambda: all(a.screen == 'result' for a in self.apps))
        self.assertEqual([a.last_coins for a in self.apps], [5, 1])
        for app in self.apps:
            self.assertEqual(app.profile.data['stats']['lan_played'], 1)
        self.host.handle(ButtonEvent(4, 'short')); self.guest.handle(ButtonEvent(4, 'short'))
        self.pump(lambda: all(a.lan.phase == 'rps' for a in self.apps))
        self.host.handle(ButtonEvent(7, 'short')); self.guest.handle(ButtonEvent(8, 'short'))
        self.pump(lambda: all(a.lan.phase == 'game' and all(a.lan.ready.values()) for a in self.apps))
        self.assertEqual([a.human_mark for a in self.apps], [-1, 1])
        self.assertTrue(all(not a.recorded and a.game.moves == 0 for a in self.apps))
        for cell in (0, 3, 1, 4, 2): self.move(cell)
        self.pump(lambda: all(a.lan.phase == 'result' for a in self.apps))
        self.assertEqual([a.last_coins for a in self.apps], [1, 5])
        self.assertEqual([a.profile.data['coins'] for a in self.apps], [6, 6])
        for app in self.apps:
            self.assertEqual((app.profile.data['stats']['lan_wins'], app.profile.data['stats']['lan_losses']), (1, 1))

    def test_all_modes_use_the_same_schedule_and_presentation_gates(self):
        self.connect()
        for button in (4, 5, 6, 7, 8, 9):
            # Host returns to mode selection, as on the result screen.
            self.host.lan.game = None
            self.host.lan._stage('mode'); self.host.lan._publish()
            self.pump(lambda: self.host.screen == 'mode' and self.guest.lan.phase == 'mode')
            self.start(button)
            self.assertEqual(self.host.game.switch_turns, self.guest.game.switch_turns)
            if self.host.game.mode.switch:
                # A controlled switching turn, shared by both peers.
                for app in self.apps: app.game.switch_turns = (5,)
                self.host.lan.game.switch_turns = (5,)
            for cell in (0, 3, 1, 4, 8):
                if self.host.game.done: break
                legal = self.host.game.legal_actions()
                self.move(cell if cell in legal else legal[0])
            if self.host.game.mode.gravity and not self.host.game.done:
                self.assertTrue(self.host.game.clear_due())
                self.move(self.host.game.legal_actions()[0])
                self.assertEqual(self.host.game.last_event, 'clear')

    def test_multicast_discovery_lists_a_real_host(self):
        self.host.lan.host()
        self.assertIsNotNone(self.host.lan.link, self.host.notice)
        self.guest.lan.search()
        self.pump(lambda: any(r.id == self.host.lan.link.room.id for r in self.guest.lan.rooms))
        room = next(r for r in self.guest.lan.rooms if r.id == self.host.lan.link.room.id)
        self.assertEqual(room.number, self.host.lan.link.room.number)
        self.guest.handle(ButtonEvent(4, 'short'))
        self.assertEqual(self.guest.screen, 'lan_confirm')
        self.guest.handle(ButtonEvent(8, 'short'))
        self.pump(lambda: self.host.screen == 'mode' and self.guest.lan.synced)


class SnapshotTests(unittest.TestCase):
    def test_round_trip_every_mode_and_reject_malformed_boards(self):
        import json
        for mode in MODES:
            game = Game(mode)
            for _ in range(3): game.play(game.legal_actions()[0])
            wire = json.loads(json.dumps(game_to_wire(game)))
            self.assertEqual(game_from_wire(wire).key(), game.key())
            wire['board'] = [99] * 9
            with self.assertRaises(ValueError): game_from_wire(wire)

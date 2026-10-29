"""Offline UI contract through physical-button events and deterministic time."""
import json
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import patch

from vttt.app import Application
from vttt.backends import HeadlessBackend, RecoveryButtonFilter, DesktopBackend
from vttt.buttons import ButtonEvent, ButtonFilter
from vttt.config import runtime_config
from vttt.connectivity_ui import DEMO_NETWORKS, SYMBOLS


class OfflineUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        cfg = runtime_config(); cfg['profile'] = str(Path(self.temp.name)/'profile.json')
        self.now = 10.
        self.app = Application(cfg, HeadlessBackend(), None, ai=object(), clock=lambda:self.now)
        self.ui = self.app.connectivity

    def tearDown(self):
        self.app.close(); self.temp.cleanup()

    def press(self, b, kind='short'):
        self.app.handle(ButtonEvent(b, kind))

    def advance(self, seconds=2):
        self.now += seconds; self.app.tick()

    def password_screen(self):
        self.app.go('communication'); self.press(3); self.advance(); self.press(4)
        self.assertEqual(self.app.screen, 'wifi_password')

    def test_menu_positions_and_both_connection_routes(self):
        self.press(8); self.press(4); self.assertEqual(self.app.screen,'scores')
        self.press(1); self.press(6); self.assertEqual(self.app.screen,'settings')
        self.press(1); self.press(8); self.assertEqual(self.app.screen,'communication')
        for b, mode in ((4,'local'),(6,'online')):
            self.press(b); self.press(8)
            self.assertEqual((self.app.screen,self.ui.mode),('connection',mode))
            for action, screen in ((4,'room_create'),(5,'room_search')):
                self.press(action); self.assertEqual(self.app.screen,screen)
                self.advance(); self.assertTrue(self.ui.room_ready)
                self.press(8); self.assertEqual(self.app.screen,screen)
                self.assertIsNone(self.app.game)
                self.press(3); self.advance(); self.press(1)
                self.assertEqual(self.app.screen,screen)
                self.press(1)
            self.press(1)

    def test_wifi_pagination_scrolling_source_and_open_network(self):
        self.app.go('connection'); self.press(3); self.advance()
        self.assertEqual(self.ui.networks, DEMO_NETWORKS[:4])
        self.press(9); self.assertGreater(len(self.ui.networks[0].ssid),24)
        self.press(9); self.assertEqual(len(self.ui.networks),1)
        self.press(8); self.assertEqual(self.app.screen,'wifi_scan')
        self.press(3); self.advance(); self.press(6)
        self.assertEqual(self.app.screen,'wifi_connecting')
        self.advance(); self.assertEqual(self.app.screen,'wifi_result')
        self.assertEqual(self.ui.result,'failure')

    def test_every_letter_symbol_and_space_can_be_entered(self):
        self.password_screen()
        for uppercase in (False, True):
            if uppercase:self.press(7)
            for group, chars in ((4,'abcdefghi'),(5,'jklmnopqr'),(6,'stuvwxyz')):
                for b, c in enumerate(chars,1):
                    self.ui.password=''; self.press(group); self.press(b)
                    self.assertEqual(self.ui.password,c.upper() if uppercase else c)
        for index, char in enumerate(SYMBOLS):
            self.ui.password=''; self.press(8)
            for _ in range(index//6):self.press(9)
            self.press(index%6+1)
            self.assertEqual(self.ui.password,char)
        self.assertEqual(set(SYMBOLS),set(string.digits+string.punctuation+' '))

    def test_all_nine_long_presses_cancel_without_appending(self):
        self.password_screen()
        for group in (4,5,6,8):
            for b in range(1,10):
                self.press(group); self.press(b,'long')
                self.assertEqual((self.app.screen,self.ui.password),('wifi_password',''))

    def test_password_mask_failure_retry_edit_cancel_and_no_persistence(self):
        self.password_screen(); self.press(4); self.press(2)
        self.assertEqual(self.ui.masked_password,'b')
        self.advance(); self.assertEqual(self.ui.masked_password,'•')
        self.press(3); self.advance()
        self.assertEqual((self.ui.result,self.ui.password),('failure','b'))
        self.press(4); self.press(9); self.assertEqual(self.ui.password,'')
        self.press(4); self.press(1); self.press(3); self.press(4)
        self.assertEqual((self.app.screen,self.ui.result),('wifi_result','success'))
        self.app.save_settings()
        self.assertNotIn('password',json.loads(Path(self.app.config['profile']).read_text()))
        self.press(8); self.assertEqual(self.ui.password,'')

    def test_max_length_and_delete_do_not_reveal_earlier_character(self):
        self.password_screen(); self.ui.password='a'*63
        self.press(4); self.press(2); self.assertEqual(len(self.ui.password),63)
        self.press(9); self.assertEqual(self.ui.masked_password,'…'+'•'*10)

    def test_animated_redraw_does_not_stale_a_held_group_input(self):
        from PIL import Image
        class Renderer:
            def draw(self, app): return Image.new('RGB',(720,720))
        self.app.renderer=Renderer(); self.password_screen(); self.app.present()
        started=self.now+.01
        self.advance(.3); self.app.present()
        self.app.handle(ButtonEvent(4,'short',started))
        self.assertEqual(self.app.screen,'wifi_chars')

    def test_rps_ai_hand_cycles_until_human_picks(self):
        self.app.go('rps'); self.now = 100.1
        shown = []
        for _ in range(4):
            self.advance(.2); shown.append(self.app.rps_spin)
        self.assertTrue(all(b == (a + 1) % 3 for a, b in zip(shown, shown[1:])), shown)
        with patch('random.randrange', return_value=2): self.press(8)  # rock vs paper: AI wins
        self.assertEqual((self.app.screen, self.app.rps_choice), ('rps_result', 2))
        self.app.go('rps'); self.app.rps_choice = None
        with patch('random.randrange', return_value=1): self.press(8)  # rock vs rock: tie
        self.advance(.4); self.assertEqual((self.app.screen, self.app.rps_choice), ('rps', 1))
        self.advance(1.0); self.assertIsNone(self.app.rps_choice)

    def duel(self):
        self.app.settings.update(opponent='local', human_first=False)
        self.app.mode_key = 'vanishing'
        self.app.begin_match()
        self.assertEqual(self.app.screen, 'duel')
        self.advance(0)

    def test_duel_counts_down_and_only_accepts_presses_in_the_window(self):
        self.duel()
        phases = []
        for _ in range(3):
            self.press(9)  # too early: ignored
            phases.append(self.app.duel_phase)
            self.advance(1.0)
        self.assertEqual(phases, [0, 1, 2])
        self.assertEqual(self.app.duel_picks, {'top': None, 'bottom': None})
        self.assertTrue(self.app.duel_window_open())
        self.press(3)  # top player: scissors (their left)
        self.press(8)  # bottom player: rock -> 1P wins
        self.assertEqual(self.app.screen, 'duel_result')
        self.assertTrue(self.app.rps_human_first)
        self.advance(2)
        self.assertEqual((self.app.screen, self.app.human_mark), ('game', 1))

    def test_duel_late_player_loses_and_nobody_restarts(self):
        self.duel()
        self.advance(3.0)
        self.press(9)  # only 1P presses
        self.advance(1.0)
        self.assertEqual((self.app.screen, self.app.rps_human_first, self.app.duel_reason), ('duel_result', True, '위쪽이 늦었어요'))
        self.duel()
        self.advance(3.0); self.advance(1.0)
        self.assertEqual((self.app.screen, self.app.notice), ('duel', '둘 다 안 눌렀어요 · 다시!'))
        self.advance(1.3)
        self.assertEqual(self.app.duel_phase, 0)  # countdown starts over

    def test_duel_tie_restarts(self):
        self.duel()
        self.advance(3.0)
        self.press(2); self.press(8)  # rock vs rock
        self.assertEqual((self.app.screen, self.app.notice), ('duel', '비겼어요 · 다시!'))

    def test_two_player_skips_difficulty_and_forced_first_applies(self):
        self.app.settings.update(opponent='local', human_first=False)
        for button in (4, 5, 6, 7, 8, 9):
            self.app.go('mode'); self.press(button)
            self.assertEqual(self.app.screen, 'duel', button)
            self.press(4)  # back goes straight to mode selection
            self.assertEqual(self.app.screen, 'mode')
        self.app.settings['human_first'] = True  # AI-only setting: 2P still plays RPS
        self.press(5)
        self.assertEqual(self.app.screen, 'duel')
        self.app.rps_human_first = False
        self.app.start_game()
        self.assertEqual(self.app.human_mark, -1)
        self.app.settings.update(opponent='ai', human_first=False)
        self.app.go('mode'); self.press(5)
        self.assertEqual(self.app.screen, 'setup')

    def test_every_press_flashes_its_tile(self):
        self.app.go('settings')
        self.press(3)  # a tile that does nothing still lights up
        self.assertEqual(self.app.flash, (3,))
        self.advance(0.2)
        self.assertEqual(self.app.flash, ())
        self.duel(); self.advance(3.0)
        self.press(1)
        self.assertEqual(self.app.flash, (1, 2, 3))  # whole row: the chosen hand stays secret

    def test_difficulty_confirm_and_rps_leave_game_ready(self):
        self.app.go('setup'); self.press(7); self.press(8)
        self.assertEqual(self.app.screen,'setup')
        self.press(6); self.press(8)
        with patch('random.randrange',return_value=0):self.press(8)
        self.assertEqual(self.app.screen,'rps_result')
        self.advance(); self.assertEqual(self.app.screen,'game')
        self.assertEqual(self.app.settings['difficulty'],'hard')
        self.assertEqual((self.app.rps_human_first, self.app.human_mark), (True, 1))
        self.assertFalse(self.app.settings['human_first'])  # RPS result is not a setting


class HoldInputTests(unittest.TestCase):
    def test_every_gpio_button_long_cancels_and_release_never_types(self):
        for b in range(1,10):
            f=RecoveryButtonFilter(); f.wifi_input=True; events=[]
            for t,pressed in ((0,False),(.1,True),(.15,True),(1.6,True),(2.2,True),(2.3,False),(2.4,False)):
                events+=f.feed(b,pressed,t)
            self.assertEqual([(e.button,e.kind) for e in events],[(b,'long')])

    def test_button_three_works_on_first_entry_to_character_screen(self):
        f=RecoveryButtonFilter(); f.feed(3,False,0);f.wifi_input=True
        events=[]
        for t,pressed in ((.1,True),(.15,True),(.3,False),(.4,False)):
            events+=f.feed(3,pressed,t)
        self.assertEqual([e.kind for e in events],['short'])

    def test_cancel_hold_cannot_become_lcd_recovery_after_screen_change(self):
        f=RecoveryButtonFilter(); f.wifi_input=True
        for t,p in ((0,False),(.1,True),(.15,True),(1.6,True)): f.feed(3,p,t)
        f.wifi_input=False
        events=[]
        for t,p in ((2.4,True),(2.5,False),(2.6,False)):events+=f.feed(3,p,t)
        self.assertEqual(events,[])

    def test_desktop_noncenter_hold_is_long_in_input_screen(self):
        b=DesktopBackend.__new__(DesktopBackend);b.events=[];b.long_seconds=1.3
        b.set_input_context('wifi_chars');b.down={'mouse':(3,1.,False)}
        with patch('vttt.backends.time.monotonic',return_value=3.):b._release('mouse')
        self.assertEqual(b.events[0].kind,'long')


if __name__=='__main__':unittest.main()

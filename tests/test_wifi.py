"""Exercise nmcli commands without changing the test machine's network."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from vttt.wifi import NetworkManagerWifi, WifiError, WifiNetwork, split_fields
from vttt.profile import Profile
from vttt.config import runtime_config
from vttt.rules import Game


class WifiTests(unittest.TestCase):
    def test_scan_escaped_names_deduplicates_and_keeps_strongest_signal(self):
        calls = []
        def run(args, cancel, timeout):
            calls.append(args)
            if args[-2:] == ['device', 'status']:
                return 'eth0:ethernet\nwlan0:wifi\n'
            if 'list' in args:
                return 'Cafe\\:Wi\\\\Fi:WPA2:20:\nCafe\\:Wi\\\\Fi:WPA2:90:*\nFree:--:50:\n:WPA2:10:\n'
            return ''
        result = NetworkManagerWifi(run).scan(threading.Event())
        self.assertEqual([n.ssid for n in result], ['Cafe:Wi\\Fi', 'Free'])
        self.assertEqual((result[0].signal, result[0].active, result[1].secured), (90, True, False))
        self.assertIn('--rescan', calls[-1])

    def test_secret_is_not_an_argument_and_temporary_file_is_removed(self):
        password = 'ab:$`"\\C 123'
        paths, calls = [], []
        def run(args, cancel, timeout):
            calls.append(args)
            self.assertNotIn(password, repr(args))
            if args[-2:] == ['device', 'status']:
                return 'wlan0:wifi\n'
            if 'passwd-file' in args:
                path = Path(args[-1]); paths.append(path)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text(), '802-11-wireless-security.psk:' + password + '\n')
            return ''
        result = NetworkManagerWifi(run).connect(WifiNetwork('Cafe:$()`', security='WPA2'), password, threading.Event())
        self.assertEqual(result, 'Cafe:$()`')
        self.assertTrue(paths)
        self.assertFalse(paths[0].exists())
        self.assertFalse(any('delete' in call for call in calls))
        creation = next(call for call in calls if 'add' in call)
        self.assertEqual(creation[creation.index('wifi-sec.psk-flags') + 1], '0')

    def test_failed_activation_deletes_only_its_own_profile_and_secret(self):
        calls, path = [], []
        def run(args, cancel, timeout):
            calls.append(args)
            if args[-2:] == ['device', 'status']:
                return 'wlan0:wifi\n'
            if 'passwd-file' in args:
                path.append(Path(args[-1]))
                raise WifiError('activation failed')
            return ''
        with self.assertRaises(WifiError):
            NetworkManagerWifi(run).connect(WifiNetwork('Test', security='WPA2'), 'password123', threading.Event())
        created_uuid = calls[1][calls[1].index('connection.uuid') + 1]
        self.assertEqual(calls[-1][-2:], ['uuid', created_uuid])
        self.assertIn('delete', calls[-1])
        self.assertFalse(path[0].exists())

    def test_open_network_has_no_secret_file_and_enterprise_is_rejected(self):
        calls = []
        def run(args, cancel, timeout):
            calls.append(args)
            return 'wlan0:wifi\n' if 'status' in args else ''
        wifi = NetworkManagerWifi(run)
        wifi.connect(WifiNetwork('Open', False), '', threading.Event())
        self.assertFalse(any('passwd-file' in call for call in calls))
        with self.assertRaises(WifiError):
            wifi.connect(WifiNetwork('Enterprise', security='WPA2 802.1X'), 'password123', threading.Event())

    def test_saved_profile_survives_adapter_restart_and_reuses_secret(self):
        older = '00000000-0000-0000-0000-000000000001'
        newest = '00000000-0000-0000-0000-000000000002'
        other_device = '00000000-0000-0000-0000-000000000003'
        calls = []
        def run(args, cancel, timeout):
            calls.append(args)
            if args[-2:] == ['device', 'status']:
                return 'wlan0:wifi\n'
            if args[-2:] == ['connection', 'show']:
                return f'{older}:802-11-wireless:100\n{newest}:802-11-wireless:200\n{other_device}:802-11-wireless:300\n'
            if args[-2] == 'uuid' and 'show' in args:
                device = 'wlan1' if args[-1] == other_device else 'wlan0'
                return (f'connection.interface-name:{device}\n'
                        '802-11-wireless.ssid:Cafe\\:Wi\\\\Fi\n'
                        '802-11-wireless-security.key-mgmt:wpa-psk\n')
            if 'list' in args:
                return 'Cafe\\:Wi\\\\Fi:WPA2:90:\nNew:WPA2:60:\n'
            return ''
        # No in-memory cache is shared between these two application lifetimes.
        first = NetworkManagerWifi(run).scan(threading.Event())
        second = NetworkManagerWifi(run).scan(threading.Event())
        self.assertEqual(first[0].saved_uuid, newest)
        self.assertEqual(second[0].saved_uuid, newest)
        self.assertEqual(second[1].saved_uuid, '')
        calls.clear()
        result = NetworkManagerWifi(run).connect(second[0], '', threading.Event())
        self.assertEqual(result, 'Cafe:Wi\\Fi')
        self.assertEqual(calls[-1], ['--wait', '35', 'connection', 'up', 'uuid', newest, 'ifname', 'wlan0'])
        self.assertFalse(any('add' in c or 'passwd-file' in c or '--show-secrets' in c for c in calls))

    def test_saved_failure_preserves_profile_and_new_password_replaces_by_new_profile(self):
        saved = '00000000-0000-0000-0000-000000000001'
        calls = []
        def run(args, cancel, timeout):
            calls.append(args)
            if args[-2:] == ['device', 'status']:
                return 'wlan0:wifi\n'
            if 'up' in args and saved in args:
                raise WifiError('stored password failed')
            return ''
        wifi = NetworkManagerWifi(run)
        network = WifiNetwork('Saved', security='WPA2', saved_uuid=saved)
        with self.assertRaises(WifiError):
            wifi.connect(network, '', threading.Event())
        self.assertFalse(any('delete' in c or 'add' in c for c in calls))
        wifi.connect(network, 'replacement123', threading.Event())
        self.assertTrue(any('add' in c for c in calls))
        self.assertFalse(any('delete' in c for c in calls))
        self.assertNotIn('replacement123', repr(calls))


class NetworkRewardTests(unittest.TestCase):
    def test_individual_rewards_are_persisted_once_even_after_reloading(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = runtime_config()
            win = Game('original')
            for cell in (0, 3, 1, 4, 2): win.play(cell)
            draw = Game('original')
            for cell in (0, 1, 2, 4, 3, 5, 7, 6, 8): draw.play(cell)
            for name, mark, reward in (('winner', 1, 5), ('loser', -1, 1)):
                path = Path(tmp) / (name + '.json')
                profile = Profile(path, config)
                self.assertEqual(profile.record_network(win, mark, 'a' * 32), reward)
                profile = Profile(path, config)
                profile.record_network(win, mark, 'a' * 32)
                self.assertEqual(profile.data['coins'], reward)
                self.assertEqual(profile.data['stats']['lan_played'], 1)
                self.assertEqual(profile.record_network(draw, mark, 'b' * 32), 2)
                self.assertEqual(profile.data['stats']['lan_draws'], 1)
                with patch.object(profile, 'save', side_effect=OSError):
                    with self.assertRaises(OSError):
                        profile.record_network(win, mark, 'c' * 32)
                self.assertEqual(profile.data['stats']['lan_played'], 2)
                profile.record_network(win, mark, 'c' * 32)
                self.assertEqual(profile.data['stats']['lan_played'], 3)


class LiveWifiUITests(unittest.TestCase):
    def setUp(self):
        from vttt.app import Application
        from vttt.backends import HeadlessBackend
        self.temp = tempfile.TemporaryDirectory()
        config = runtime_config(); config['profile'] = str(Path(self.temp.name) / 'profile.json')
        self.app = Application(config, HeadlessBackend(), None, ai=object())

    def tearDown(self):
        self.app.close(); self.temp.cleanup()

    def wait(self, screen):
        import time
        end = time.monotonic() + 2
        while time.monotonic() < end:
            self.app.tick()
            if self.app.screen == screen: return
            time.sleep(.01)
        self.fail(self.app.screen)

    def test_real_scan_and_connect_result_cannot_be_forged_by_demo_buttons(self):
        from vttt.buttons import ButtonEvent
        from concurrent.futures import Future
        ui = self.app.connectivity
        self.assertFalse(ui.demo)
        network = WifiNetwork('Real AP', True, 88, False, 'WPA2')
        ui.wifi.scan = lambda cancel: [network]
        ui.scan(); self.wait('wifi_scan')
        self.app.handle(ButtonEvent(4, 'short'))
        self.assertEqual(self.app.screen, 'wifi_password')
        ui.password = 'password123'
        future = Future()
        with patch.object(ui.pool, 'submit', return_value=future) as submit:
            ui.connect()
        self.assertEqual(ui.password, '')
        self.assertEqual(submit.call_args.args[2], 'password123')
        self.app.handle(ButtonEvent(4, 'short'))
        self.app.handle(ButtonEvent(6, 'short'))
        self.assertEqual(self.app.screen, 'wifi_connecting')
        future.set_result('Real AP'); self.app.tick()
        self.assertEqual((self.app.screen, ui.result), ('wifi_result', 'success'))
        self.app.handle(ButtonEvent(6, 'short'))
        self.assertEqual(self.app.screen, 'wifi_password')

    def test_cancelled_scan_cannot_change_the_next_screen(self):
        from concurrent.futures import Future
        ui = self.app.connectivity
        future = Future(); future.set_running_or_notify_cancel()
        with patch.object(ui.pool, 'submit', return_value=future): ui.scan()
        ui.leave_wifi()
        future.set_result([WifiNetwork('Old AP')])
        self.app.tick()
        self.assertEqual(self.app.screen, 'communication')
        self.assertTrue(ui.cancel.is_set())
        self.assertEqual(ui.available_networks, [])

    def test_saved_wifi_skips_password_and_refreshes_list_after_success(self):
        from vttt.buttons import ButtonEvent
        ui = self.app.connectivity
        network = WifiNetwork('Saved AP', security='WPA2', saved_uuid='a' * 32)
        ui.wifi.scan = lambda cancel: [network]
        with patch.object(ui.wifi, 'connect', return_value=network.ssid) as connect:
            ui.scan(); self.wait('wifi_scan')
            self.app.handle(ButtonEvent(4, 'short'))
            self.assertEqual(self.app.screen, 'wifi_connecting')
            self.wait('wifi_result')
            self.assertEqual(ui.result, 'success')
            self.assertEqual(connect.call_args.args[:2], (network, ''))
            self.assertEqual(ui.password, '')
            self.app.handle(ButtonEvent(8, 'short'))
            self.wait('wifi_scan')
            self.assertEqual(ui.networks[0].saved_uuid, network.saved_uuid)

    def test_saved_failure_allows_manual_password_update_and_retry(self):
        from vttt.buttons import ButtonEvent
        ui = self.app.connectivity
        network = WifiNetwork('Saved AP', security='WPA2', saved_uuid='a' * 32)
        ui.wifi.scan = lambda cancel: [network]
        ui.scan(); self.wait('wifi_scan')
        with patch.object(ui.wifi, 'connect', side_effect=WifiError('비밀번호 변경됨')):
            self.app.handle(ButtonEvent(4, 'short'))
            self.wait('wifi_result')
        self.assertEqual(ui.result, 'failure')
        self.app.handle(ButtonEvent(4, 'short'))
        self.assertEqual(self.app.screen, 'wifi_password')
        ui.password = 'new-password'
        with patch.object(ui.wifi, 'connect', return_value=network.ssid) as connect:
            self.app.handle(ButtonEvent(3, 'short'))
            self.wait('wifi_result')
        self.assertEqual(connect.call_args.args[:2], (network, 'new-password'))
        self.assertEqual(ui.password, '')
        self.assertEqual(ui.result, 'success')

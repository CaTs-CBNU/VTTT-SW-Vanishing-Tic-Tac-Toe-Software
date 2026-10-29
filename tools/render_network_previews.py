"""Preview live-network screens using explicit fixtures, without opening sockets."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vttt.app import Application
from vttt.backends import HeadlessBackend
from vttt.config import runtime_config
from vttt.lan_transport import Room
from vttt.render import Renderer
from vttt.wifi import WifiNetwork


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        config = runtime_config(); config['profile'] = str(Path(tmp) / 'profile.json')
        app = Application(config, HeadlessBackend(), Renderer(), ai=object())
        def save(screen, filename=None):
            app.go(screen)
            app.renderer.draw(app).save(output / ((filename or screen) + '.png'))
        try:
            room = Room('a' * 32, '1234', '192.168.1.10', 44245)
            app.lan.rooms = [room]
            app.lan.selected_room = room
            save('lan_search'); save('lan_confirm')
            app.lan.link = SimpleNamespace(room=room, connected=True, ever_connected=True, is_host=True, close=lambda:None)
            app.lan.active = app.lan.synced = True
            save('lan_lobby'); save('lan_wait')
            app.lan.phase = 'rps_result'
            app.lan.my_pick, app.lan.other_pick = 1, 0
            app.human_mark = 1
            save('lan_rps')
            app.start_game()
            app.profile.data['theme'] = 'squirrel'
            for action in (0, 3, 1, 4): app.make_move(action)
            app.lan.link.connected = False
            app.lan.synced = False
            save('game', 'lan-reconnecting')
            app.lan.active = False
            app.lan.link = None
            app.connectivity.available_networks = [WifiNetwork('VTTT Wi-Fi', True, 92, True, 'WPA2'),
                                                  WifiNetwork('Guest', False, 70)]
            app.connectivity.network = app.connectivity.available_networks[0]
            save('communication', 'communication-live')
            save('wifi_scan', 'wifi-live-list')
            save('wifi_connecting', 'wifi-live-connecting')
            app.connectivity.result = 'success'
            save('wifi_result', 'wifi-live-success')
            app.profile.data['stats'].update(lan_played=10, lan_wins=6, lan_losses=3, lan_draws=1)
            app.score_network = True
            save('scores', 'scores-network')
        finally:
            app.close()
    print('Rendered network fixtures:', output)


if __name__ == '__main__':
    render(ROOT / 'docs/previews')

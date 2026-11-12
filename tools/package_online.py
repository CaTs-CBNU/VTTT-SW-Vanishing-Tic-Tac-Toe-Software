"""Package a standard-library relay and an update for existing game installations."""

from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'vttt/__init__.py', 'vttt/__main__.py', 'vttt/config.py', 'vttt/profile.py',
    'vttt/relay_server.py', 'vttt/online_transport.py', 'vttt/lan_transport.py',
    'vttt/lan.py', 'vttt/lan_ui.py', 'vttt/connectivity_ui.py', 'vttt/ui_render.py', 'vttt/wifi.py',
    'docs/ONLINE_SERVER_KO.md',
)


def main():
    """Keep profiles, GPIO configuration, models and credentials out of the archive."""
    output = ROOT / 'dist' / 'vttt-online-update.tar.gz'
    output.parent.mkdir(exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for relative in FILES:
            archive.add(ROOT / relative, arcname=relative)
    print(output)


if __name__ == '__main__':
    main()

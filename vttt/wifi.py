"""NetworkManager Wi-Fi adapter. Never passes credentials in process arguments."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    secured: bool = True
    signal: int = 0
    active: bool = False
    security: str = ''


class WifiError(RuntimeError):
    pass


def split_fields(line):
    fields, current, escaped = [], '', False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(current)
            current = ''
        else:
            current += char
    fields.append(current)
    return fields


class NetworkManagerWifi:
    def __init__(self, runner=None):
        self.runner = runner
        self.available = runner is not None or (sys.platform.startswith('linux') and shutil.which('nmcli') is not None)
        self.reason = ('NetworkManager와 nmcli 설치를 확인하세요' if sys.platform.startswith('linux') else
                       'PC에서는 OS에서 Wi-Fi를 연결하세요')

    def _run(self, args, cancel, timeout=45):
        if not self.available:
            raise WifiError(self.reason)
        if self.runner:
            return self.runner(args, cancel, timeout)
        if cancel.is_set():
            raise WifiError('연결 작업을 취소했습니다')
        env = dict(os.environ, LC_ALL='C.UTF-8')
        process = subprocess.Popen(['nmcli', '--colors', 'no', *args], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding='utf-8', errors='replace', env=env)
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel.is_set() or time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    raise WifiError('작업을 취소했거나 시간이 초과되었습니다')
                try:
                    output, error = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        if process.returncode:
            if 'not authorized' in error.lower() or 'insufficient' in error.lower():
                raise WifiError('네트워크 변경 권한을 확인하세요')
            raise WifiError('Wi-Fi 작업 실패: 비밀번호와 신호를 확인하세요')
        return output

    def interface(self, cancel):
        output = self._run(['-t', '-e', 'yes', '-f', 'DEVICE,TYPE', 'device', 'status'], cancel)
        for line in output.splitlines():
            fields = split_fields(line)
            if len(fields) == 2 and fields[1] == 'wifi':
                return fields[0]
        raise WifiError('무선 LAN 장치를 찾을 수 없습니다')

    def scan(self, cancel):
        interface = self.interface(cancel)
        self._run(['radio', 'wifi', 'on'], cancel)
        output = self._run(['-t', '-e', 'yes', '-f', 'SSID,SECURITY,SIGNAL,IN-USE',
                            'device', 'wifi', 'list', '--rescan', 'yes', 'ifname', interface], cancel)
        networks = {}
        for line in output.splitlines():
            fields = split_fields(line)
            if len(fields) != 4 or not fields[0]:
                continue
            ssid, security, signal, active = fields
            try:
                network = WifiNetwork(ssid, security not in ('', '--'), int(signal), active == '*', security)
            except ValueError:
                continue
            if ssid not in networks or network.signal > networks[ssid].signal:
                networks[ssid] = network
        return sorted(networks.values(), key=lambda n: (not n.active, -n.signal, n.ssid))

    def connect(self, network, password, cancel):
        interface = self.interface(cancel)
        security = network.security.upper()
        if network.secured and ('802.1X' in security or 'EAP' in security or 'WEP' in security):
            raise WifiError('기업용 인증과 WEP는 지원하지 않습니다')
        if network.secured and (not 8 <= len(password) <= 63 or '\n' in password or '\r' in password):
            raise WifiError('비밀번호는 8~63자로 입력하세요')
        profile_id = str(uuid.uuid4())
        arguments = ['connection', 'add', 'type', 'wifi', 'ifname', interface,
                     'con-name', 'VTTT-' + profile_id[:8], 'connection.uuid', profile_id,
                     'ssid', network.ssid, 'connection.autoconnect', 'yes']
        if network.secured:
            arguments += ['wifi-sec.key-mgmt', 'sae' if 'WPA3' in security and 'WPA2' not in security else 'wpa-psk']
        created = False
        secret_path = None
        try:
            self._run(arguments, cancel)
            created = True
            activation = ['--wait', '35', 'connection', 'up', 'uuid', profile_id, 'ifname', interface]
            if network.secured:
                descriptor, secret_path = tempfile.mkstemp(prefix='vttt-wifi-')
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    stream.write('802-11-wireless-security.psk:' + password + '\n')
                activation += ['passwd-file', secret_path]
            password = ''
            self._run(activation, cancel, timeout=40)
            # Success means NetworkManager finished activation, including IP setup.
            return network.ssid
        except (WifiError, OSError):
            if created:
                try:
                    self._run(['--wait', '5', 'connection', 'delete', 'uuid', profile_id], threading.Event(), timeout=7)
                except (WifiError, OSError):
                    pass
            raise
        finally:
            if secret_path:
                Path(secret_path).unlink(missing_ok=True)

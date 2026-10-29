#!/usr/bin/env bash
# Run explicitly on the Pi: sudo bash scripts/enable_wifi_control.sh
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
    echo 'sudo bash scripts/enable_wifi_control.sh 로 실행하세요.' >&2
    exit 1
fi
target_user=${1:-${SUDO_USER:-}}
if [[ -z "$target_user" || "$target_user" == root ]] || ! id -- "$target_user" >/dev/null 2>&1; then
    echo '앱을 실행할 일반 사용자명을 지정하세요.' >&2
    exit 1
fi
if ! command -v nmcli >/dev/null 2>&1; then
    echo 'NetworkManager와 nmcli가 필요합니다. Raspberry Pi OS Bookworm 이상을 확인하세요.' >&2
    exit 1
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
groupadd -f vttt-wifi
usermod -a -G vttt-wifi "$target_user"
install -d -m 0755 /etc/polkit-1/rules.d
install -m 0644 configs/60-vttt-wifi.rules /etc/polkit-1/rules.d/60-vttt-wifi.rules
echo 'Wi-Fi 검색·연결 권한을 설정했습니다. 재로그인 또는 재부팅 후 앱을 실행하세요.'

#!/usr/bin/env bash
# On each Raspberry Pi: sudo bash scripts/enable_autostart.sh
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo 'sudo bash scripts/enable_autostart.sh 로 실행하세요.' >&2
    exit 1
fi
if [[ $(uname -s) != Linux ]] || ! command -v systemctl >/dev/null 2>&1; then
    echo 'systemd가 있는 라즈베리파이에서 실행하세요.' >&2
    exit 1
fi
target_user=${1:-${SUDO_USER:-}}
if [[ -z "$target_user" || "$target_user" == root ]] || ! id -- "$target_user" >/dev/null 2>&1; then
    echo '게임 앱을 실행할 일반 사용자명을 지정하세요.' >&2
    exit 1
fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
# WorkingDirectory takes a single path value, not a shell-quoted argument.
working_path=${project_dir//%/%%}
# ExecStart uses quoted command arguments and its own environment expansion.
unit_path=${project_dir//\\/\\\\}
unit_path=${unit_path//\"/\\\"}
unit_path=${unit_path//%/%%}
unit_path=${unit_path//\$/\$\$}
if [[ "$project_dir" == *$'\n'* || "$project_dir" == *$'\r'* ]]; then
    echo '프로젝트 경로에는 줄바꿈을 사용할 수 없습니다.' >&2
    exit 1
fi
unit_dir=$(mktemp -d)
unit_file="$unit_dir/vttt.service"
trap 'rm -f -- "$unit_file"; rmdir -- "$unit_dir"' EXIT
cat > "$unit_file" <<EOF
[Unit]
Description=VTTT Raspberry Pi game
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$target_user
WorkingDirectory=$working_path
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash "$unit_path/scripts/run_hardware.sh"
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$unit_file"
fi
install -m 0644 "$unit_file" /etc/systemd/system/vttt.service
systemctl daemon-reload
systemctl enable vttt.service
echo '부팅 시 게임 앱 자동 실행을 등록했습니다. 현재 앱은 중복 실행하지 않습니다.'
echo '재부팅: sudo reboot'
echo '상태 확인: systemctl status vttt.service --no-pager'
echo '로그 확인: journalctl -u vttt.service -b -n 50 --no-pager'
echo '자동 실행 해제: sudo systemctl disable --now vttt.service'

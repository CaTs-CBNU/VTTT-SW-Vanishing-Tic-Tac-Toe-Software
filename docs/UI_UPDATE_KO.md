# 로컬 대국과 실제 Wi-Fi 연결

## 실행과 테스트

라즈베리파이와 PC가 같은 게임·통신 코드를 사용합니다. 하드웨어에서는
`bash scripts/run_hardware.sh`, PC에서는 `python3 -m vttt --simulate`로 실행합니다.
맥북·윈도우에서는 먼저 OS에서 Wi-Fi에 연결합니다. 앱 내부의 실제 Wi-Fi 변경은
Linux의 NetworkManager를 사용하며 맥북·윈도우의 네트워크 설정은 변경하지 않습니다.

맥북 하나에서 두 플레이어를 테스트하려면 터미널 두 개에서 각각 실행합니다.
Windows에서는 `python3` 대신 `py` 또는 `python`을 사용할 수 있습니다.

```bash
python3 -m vttt --simulate --profile runtime/test-host.json
python3 -m vttt --simulate --profile runtime/test-guest.json
```

실제 통신이 기본입니다. 예전 예시 화면만 확인하려면 `--demo-connectivity`를 추가합니다.
테스트용 프로필과 실제 플레이 프로필은 서로 다른 파일을 사용하세요.

## 라즈베리파이 Wi-Fi 준비

Raspberry Pi OS Bookworm 이상과 NetworkManager(`nmcli`)가 있는 환경을 대상으로 합니다.
Wi-Fi 국가 설정은 기기에서 올바르게 지정되어 있어야 합니다. 현재 상태는 다음 명령으로 확인합니다.

```bash
nmcli device status
nmcli general permissions
```

앱 실행 계정이 네트워크를 변경할 권한이 없으면 **라즈베리파이에서만** 다음 설정을 한 번 실행하고 재로그인 또는 재부팅합니다.
이 스크립트는 실행 계정을 전용 `vttt-wifi` 그룹에 추가하고 Wi-Fi 검색·무선 켜기·연결·프로필 관리 권한을 부여합니다.
맥북에는 실행하지 않습니다.

```bash
sudo bash scripts/enable_wifi_control.sh
```

통신 → 3번 네트워크 설정 → 검색된 공유기 선택 → 비밀번호 입력 → 3번 연결 순서입니다.
연결 성공은 NetworkManager의 연결 활성화 성공 결과로 판단합니다. 실패 화면은 오류 원인을 표시하며,
비밀번호를 다시 입력하거나 다른 공유기를 고를 수 있습니다. 연결 중 1번으로 취소할 수 있습니다.
WPA/WPA2 개인용, WPA3 개인용 및 개방형 네트워크를 지원합니다. WEP와 기업용 802.1X 인증은 지원하지 않습니다.

비밀번호는 프로세스 명령행·로그·게임 프로필에 넣지 않습니다. 권한 0600인 임시 파일로 NetworkManager에 전달하고
성공·실패·취소 후 삭제합니다. 성공한 연결은 **운영체제의 NetworkManager 프로필**에 저장되어 재접속에 사용됩니다.
앱 입력란은 연결 요청 시 비웁니다. 실패 후에는 비밀번호를 다시 입력해야 합니다.
문자 그룹·숫자·기호 입력과 길게 누르기 취소, 마지막 문자 잠깐 표시 기능은 유지합니다.

## 방 생성과 입장

1. 두 기기를 같은 Wi-Fi에 연결합니다.
2. 방장: 통신 → 로컬 → 방 만들기. 네 자리 방 번호가 표시됩니다.
3. 상대: 통신 → 로컬 → 방 찾기. 검색된 방을 누릅니다.
4. “이 방이 맞나요?”와 방 번호를 확인하고 8번으로 입장합니다.
5. 방장이 모드를 선택하고, 각 기기에서 7 가위 / 8 바위 / 9 보를 선택합니다.
6. 양쪽 선택이 끝나면 결과를 공개하고 선공을 정합니다. 비기면 다시 선택합니다.

방장은 모든 모드를 고를 수 있습니다. 테마는 각 기기 프로필의 테마를 사용하고 보드 방향은 동일합니다.
랜덤 스위칭 일정은 방장이 정하여 공유하므로 두 기기에 같은 턴에 적용됩니다.
상대 차례에는 착수할 수 없으며, 양쪽의 블라인드 공개·나인스위칭·그래비티 예고/낙하 연출이 끝나야 다음 착수를 허용합니다.
5번 길게 누르기로 양쪽 대국을 일시정지하고 5번으로 계속합니다. 재대국은 양쪽이 다시하기를 누르면 시작합니다.
모드 변경은 방장이 선택합니다. 방 나가기는 상대에게 연결 종료로 안내합니다.

방 검색은 UDP 44244 포트의 멀티캐스트와 브로드캐스트, 대국은 방장이 여는 TCP 포트를 사용합니다.
PC 방화벽에서 Python의 로컬 네트워크 통신을 허용해야 합니다. 공유기의 기기 격리/AP isolation이 켜진 게스트 Wi-Fi에서는
기기끼리 검색·접속할 수 없습니다. 인터넷 서버나 외부 인터넷 연결은 필요하지 않습니다.
외부 온라인 매칭은 아직 지원하지 않으며 화면에서도 안내합니다.

## 끊김과 재연결

통신 상태를 주기적으로 확인합니다. 연결 끊김이 감지되면 양쪽 모두 보드를 어둡게 하고
“재연결 중...”의 점이 반복해서 나타났다 사라지는 안내를 표시합니다. 이때 입력과 대국 진행을 막습니다.
같은 방과 같은 상대에게 계속 재접속하며, 방장의 IP가 바뀌면 같은 방을 재검색합니다.
복구되면 방장의 최신 보드·차례·말 수명·스위칭 일정으로 맞추고 이어서 진행합니다.
중복 전송된 착수는 두 번 적용하지 않습니다. 앱 프로세스가 실행 중인 동안의 네트워크 끊김 복구를 지원하며,
앱 종료나 전원 차단 뒤 진행 중인 대국을 복원하는 기능은 포함하지 않습니다.

## 기록과 보상

통신 대국의 승리 +5 / 패배 +1 / 무승부 +2 골드를 각 기기에 따로 저장합니다.
대국 ID로 중복 보상을 막으며 저장 실패 시 재시도합니다. 점수 화면의 9번으로 AI 기록과 통신 기록을 전환할 수 있습니다.
같은 기기에서 두 명이 두는 기존 2인 모드와 통신 대국의 기록은 구분합니다.

## 기존 화면과 게임 연출

- 모드 선택 3번은 현재 테마를 표시합니다. 설정은 변경 즉시 저장하며 별도 저장 버튼은 없습니다.
- 게임 설명은 공통 돌아가기 이미지와 세 가지 규칙 칸을 사용하고, 페이지 번호는 8번에 표시합니다.
- 나인스위칭은 전환 예고 후 자신의 말로 놓인 화면을 1초 유지하고 모든 말이 함께 뒤집힙니다.
- 그래비티는 삭제 직전 아래 3칸을 하나의 빨간 테두리로 감싸고 최소 2.5초 동안 예고합니다.
- 차례 안내·결과창에는 각 기기 테마의 투명 말 이미지를 사용합니다.
- AI 승리 보상은 초보 +3 / 중수 +5 / 고수 +10, 패배 +1이며 오리지널은 중수 기준입니다.

## 검증

```bash
python3 -m unittest discover -s tests
python3 tools/render_previews.py
python3 tools/render_network_previews.py
```

맥북의 실제 TCP/UDP 소켓으로 방 검색·입장·모든 모드의 보드 동기화·재접속·일시정지·재대국을 검증합니다.
NetworkManager 명령, SSID 이스케이프, 임시 비밀번호 파일, 실패 시 생성 프로필 정리, 기기별 보상은 자동 테스트로 검증합니다.
실제 라즈베리파이에서의 Wi-Fi 인증/DHCP와 LCD·GPIO 동작은 해당 기기에서 최종 확인해야 합니다.
`render_network_previews.py`의 방 번호·공유기·기록은 화면 확인용 고정 데이터이며 실제 연결 결과가 아닙니다.

참고: [라즈베리파이 공식 네트워크 설정](https://www.raspberrypi.com/documentation/computers/configuration.html),
[NetworkManager nmcli 공식 문서](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nmcli.html).

## 테마 말 이미지 배경 제거

2026-10-29, 내장 `image_gen` 도구의 투명 배경 편집을 사용했습니다.
기존 말 이미지를 각각 입력하여 6개 테마 × O/X 2종을 처리했습니다.
저장 위치는 `src/static/images/theme/{name}.png`입니다.

`name` 목록: `default-o`, `default-x`, `fishcat-o`, `fishcat-x`,
`squirrel-o`, `squirrel-x`, `xmas-o`, `xmas-x`, `chiikawa1-o`,
`chiikawa1-x`, `chiikawa2-o`, `chiikawa2-x`.

각 이미지에 사용한 프롬프트 (`{name}`에 해당 파일명 대입):

```text
Use case: background-extraction. Edit target: the provided {name} tic-tac-toe piece image. Remove only the plain beige/cream rectangular background and any tile border at the canvas edge, yielding a real transparent RGBA PNG cutout. Preserve the exact existing piece design, pose, shapes, colors, outlines, facial features and any existing markings/watermarks. Preserve white/cream fills INSIDE characters as opaque; make the central hole of a ring/wreath transparent. For simple O and X, retain just the colored symbol. Keep one complete piece centered with a small transparent margin, no cropping, no new elements, no text, no shadow, no checkerboard painted into the image. This is a production game asset, not a redesign. Return only this one isolated piece.
```

렌더러는 알파 채널을 보존하고, 큰 말과 안내 문구의 작은 말 모두 같은
테마 PNG를 사용합니다. 상점에서도 투명도를 유지해 합성합니다.

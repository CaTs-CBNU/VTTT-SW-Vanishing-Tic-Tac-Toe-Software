"""Validated portable application configuration."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("설정 파일은 JSON 객체여야 합니다")
    return value


def hardware_config(path=None):
    cfg = read_config(path or ROOT / "configs/hardware.json")
    for key in ("button_pins", "lcd_cs_pins"):
        pins = cfg[key]
        if len(pins) != 9 or len(set(pins)) != 9 or any(type(p) is not int or not 0 <= p <= 27 for p in pins):
            raise ValueError(key + ": 서로 다른 BCM GPIO 9개가 필요합니다")
    if type(cfg["button_active_high"]) is not bool:
        raise ValueError("button_active_high must be a JSON boolean")
    pins = cfg["button_pins"] + cfg["lcd_cs_pins"] + [cfg["dc_pin"], cfg["reset_pin"], 10, 11]
    if len(pins) != len(set(pins)):
        raise ValueError("버튼·CS·DC·RESET·SPI 핀이 겹칩니다")
    if sorted(cfg["screen_order"]) != list(range(1, 10)):
        raise ValueError("screen_order must be a permutation of 1..9")
    if len(cfg["rotation"]) != 9 or any(x not in (0, 90, 180, 270) for x in cfg["rotation"]):
        raise ValueError("rotation must contain nine quarter-turn angles")
    if cfg["width"] != 240 or cfg["height"] != 240:
        raise ValueError("이 UI는 240×240 LCD 9개용입니다")
    if not 100000 <= cfg["baudrate"] <= 32000000:
        raise ValueError("baudrate must be 100000..32000000")
    if not 5 <= cfg["poll_ms"] <= 100 or not 10 <= cfg["debounce_ms"] <= 300:
        raise ValueError("버튼 폴링/디바운스 설정 범위를 확인하세요")
    if not 500 <= cfg["long_press_ms"] <= 5000:
        raise ValueError("long_press_ms must be 500..5000")
    return cfg


def runtime_config(path=None):
    from .rules import MODES
    cfg = read_config(path or ROOT / "configs/runtime.json")
    if cfg["default_mode"] not in MODES or cfg["opponent"] not in ("ai", "local"):
        raise ValueError("게임 모드/상대 설정을 확인하세요")
    if cfg["difficulty"] not in ("easy", "normal", "hard"):
        raise ValueError("난이도 설정을 확인하세요")
    if not 9 <= cfg["max_moves"] <= 10000 or not 0.3 <= cfg["blind_reveal_seconds"] <= 10:
        raise ValueError("착수 제한/블라인드 공개 시간을 확인하세요")
    if not 0 <= cfg["ai_move_seconds"] <= 10:
        raise ValueError("AI 착수 대기 시간을 확인하세요")
    for key in ("model_npz", "model_pt", "profile"):
        cfg[key] = str((ROOT / cfg[key]).resolve())
    return cfg

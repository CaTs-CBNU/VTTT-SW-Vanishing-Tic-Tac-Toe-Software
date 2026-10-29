"""python -m vttt [--simulate] [--diagnostic]."""

import argparse
import logging
import os
from pathlib import Path
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")


def main(argv=None):
    parser = argparse.ArgumentParser(description="다이내믹 틱택토 · Raspberry Pi 4 / PC")
    parser.add_argument("--simulate", action="store_true", help="PC에서 9개 LCD와 버튼 시뮬레이션")
    parser.add_argument("--diagnostic", action="store_true", help="버튼/LCD 번호 확인 화면으로 시작")
    parser.add_argument("--hardware-config", type=Path)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--profile", type=Path, help="설정·기록 저장 파일 경로")
    parser.add_argument("--font", type=Path, help="한글 TTF/TTC/OTF 글꼴 경로")
    parser.add_argument("--check", action="store_true", help="GPIO 없이 설정·모델·이미지 확인")
    parser.add_argument("--demo-connectivity", action="store_true", help="실제 네트워크 대신 통신 UI 예시 사용")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    backend = None
    try:
        from .config import hardware_config, runtime_config
        from .render import Renderer
        from .ai import GameAI
        from .backends import DesktopBackend, RaspberryPiBackend
        from .app import Application
        hardware = hardware_config(args.hardware_config)
        runtime = runtime_config(args.runtime_config)
        runtime["demo_connectivity"] = args.demo_connectivity
        if args.profile:
            runtime["profile"] = str(args.profile.resolve())
        renderer = Renderer(args.font)
        ai = GameAI(runtime)
        logging.info("AI: %s", ai.status)
        logging.info("Buttons: BCM %s, active_%s", hardware["button_pins"], "high" if hardware["button_active_high"] else "low")
        logging.info("LCD CS: BCM %s", hardware["lcd_cs_pins"])
        if args.check:
            from .rules import Game
            action = ai.select_action(Game(), "normal")
            logging.info("설정·이미지·AI 확인 완료. 첫 수: %d번 버튼", action + 1)
            return 0
        backend = DesktopBackend(hardware) if args.simulate else RaspberryPiBackend(hardware)
        app = Application(runtime, backend, renderer, ai=ai)
        if args.diagnostic:
            app.go("diagnostic")
        app.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception("실행 실패. docs/HARDWARE_GUIDE_KO.md의 설치·배선 설정을 확인하세요.")
        return 1
    finally:
        if backend:
            backend.close()


if __name__ == "__main__":
    sys.exit(main())

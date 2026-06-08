import RPi.GPIO as GPIO

from .pin import BUTTON_PINS
from .utils import DisplayManager
from .start import start_page
from .menu import menu_page

def setup_buttons():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for pin in BUTTON_PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


def main():
    display_manager = None

    try:
        setup_buttons()

        display_manager = DisplayManager()

        start_page(display_manager)
        print("시작 화면 출력 완료 & start button pressed")

        selected_menu = menu_page(display_manager)
        print(f"선택된 메뉴 버튼: {selected_menu}")

    except KeyboardInterrupt:
        print("\n프로그램 종료")

    finally:
        if display_manager is not None:
            display_manager.cleanup()

        GPIO.cleanup()


if __name__ == "__main__":
    main()
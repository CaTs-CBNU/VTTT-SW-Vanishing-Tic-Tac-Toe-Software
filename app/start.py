import RPi.GPIO as GPIO
from pathlib import Path
import time
from pin import BUTTON_PINS
from utils import load_images

START_IMAGE_DIR = Path("./static/images/start")

def show_start_page(display_manager):
    start_images = load_images(START_IMAGE_DIR, "start")

    for lcd_num in range(0, 9):
        display_manager.show_image(
            lcd_num,
            start_images[lcd_num]
        )

def wait_start_button():
    start_button_pin = BUTTON_PINS[8]
    print(f"waiting for 8th button... GPIO{start_button_pin}")
    prev_state = GPIO.input(start_button_pin)
      
    while True:
        current_state = GPIO.input(start_button_pin)

        if prev_state == GPIO.LOW and current_state == GPIO.HIGH:
            print("start button pressed")
            break
        
        prev_state = current_state
        time.sleep(0.03)

def start_page(display_manager):
    show_page(display_manager)
    wait_start_button()
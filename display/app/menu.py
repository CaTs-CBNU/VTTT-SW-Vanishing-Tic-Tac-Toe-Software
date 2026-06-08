import RPi.GPIO as GPIO
from pathlib import Path
import time

from .pin import BUTTON_PINS
from .utils import load_images

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_ROOT = PROJECT_ROOT / "src" / "static" / "images"

MENU_IMAGE_DIR = IMAGE_ROOT / "menu"

MENU_BUTTONS = [2, 4, 5, 6, 8]

def show_menu_page(display_manager):
    images = load_images(MENU_IMAGE_DIR, "menu")

    for lcd_num in range(1, 10):
        display_manager.show_image(
            lcd_num,
            images[lcd_num]
        )
        
def wait_menu_button():

    prev_states = {}

    for button_num in MENU_BUTTONS:
        pin = BUTTON_PINS[button_num]
        prev_states[button_num] = GPIO.input(pin)
    
    print("waiting for menu I/O")
    
    while True:
        for button_num in MENU_BUTTONS:
            pin = BUTTON_PINS[button_num]
            current_state = GPIO.input(pin)

            if prev_states[button_num] == GPIO.LOW and current_state == GPIO.HIGH:
                print(f"{button_num} button pressed.")
                return button_num
            
            prev_states[button_num] = current_state
        
        time.sleep(0.03)

def menu_page(display_manager):
    show_menu_page(display_manager)
    selected_button = wait_menu_button()
    return selected_button
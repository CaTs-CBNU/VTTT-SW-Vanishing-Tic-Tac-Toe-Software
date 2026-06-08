import RPi.GPIO as GPIO
from pathlib import Path
import time

from pin import BUTTON_PINS
from utils import load_images

MENU_IMAGE_DIR = Path("./static/images/menu")
MENU_BUTTONS = [2, 4, 5, 6, 8]

def show_start_page(display_manager):
    images = load_images(MENU_IMAGE_DIR, "m")

    for lcd_num in range(1, 10):
        display_manager.show_image(
            images[lcd_num]
        )
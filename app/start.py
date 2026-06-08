import RPi.GPIO as GPIO
from pathlib import Path
import time
from pin import BUTTON_PINS
from utils import load_images

START_IMAGE_DIR = Path("./static/images/start")

def show_page(display_manager):
    start_images = load_images(START_IMAGE_DIR, "start")

    for lcd_num in range(0, 9):
        display_manager.show_image(
            lcd_num,
            start_images[lcd_num]
        )

import RPi.GPIO as GPIO
from pathlib import Path
import time

from pin import BUTTON_PINS
from utils import load_images

MENU_IMAGE_DIR = Path("./static/images/menu")
MENU_BUTTONS = [1, 4, 5, 6, 8]
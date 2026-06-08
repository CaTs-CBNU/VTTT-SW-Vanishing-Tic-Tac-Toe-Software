import RPi.GPIO as GPIO
from pathlib import Path
import time
from pin import BUTTON_PINS
from utils import load_images

START_IMAGE_DIR = Path("./static/images/start")

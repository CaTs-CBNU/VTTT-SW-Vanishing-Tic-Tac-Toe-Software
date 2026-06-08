import time
from PIL import Image

import RPi.GPIO as GPIO
import board
import digitalio
from adafruit_rgb_display import st7789

BUTTON_PINS = {
    1: 17,
    2: 22,
    3: 5,
    4: 6,
    5: 13,
    6: 19,
    7: 20,
    8: 21,
    9: 26,
}
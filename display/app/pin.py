import time

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

LCD_CS_PINS = {
    1: board.D2,    # GPIO2,  Pin 3
    2: board.D15,    # GPI15,  Pin 10
    3: board.D4,    # GPIO4,  Pin 7
    4: board.D12,   # GPIO12, Pin 32
    5: board.D16,   # GPIO16, Pin 36
    6: board.D18,   # GPIO18, Pin 12
    7: board.D14,   # GPIO14, Pin 8
    8: board.D23,   # GPIO23, Pin 16
    9: board.D24,   # GPIO24, Pin 18
}

DC_PIN = board.D25       # GPIO25, Pin 22
RESET_PIN = board.D27    # GPIO27, Pin 13
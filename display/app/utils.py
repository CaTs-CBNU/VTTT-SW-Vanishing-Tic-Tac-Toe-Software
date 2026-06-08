import time
import board
import digitalio
from adafruit_rgb_display import st7789
from PIL import Image

from .pin import LCD_CS_PINS, DC_PIN, RESET_PIN

class DisplayManager:
    def __init__(self):
        self.spi = board.SPI()

        self.dc_pin = digitalio.DigitalInOut(DC_PIN)
        self.dc_pin.direction = digitalio.Direction.OUTPUT

        self.cs_pins = {}
        self.displays = {}

        for lcd_num, cs_board_pin in LCD_CS_PINS.items():
            cs_pin = digitalio.DigitalInOut(cs_board_pin)
            cs_pin.direction = digitalio.Direction.OUTPUT
            cs_pin.value = True
            self.cs_pins[lcd_num] = cs_pin

        self.reset_all_displays()

        for lcd_num, cs_pin in self.cs_pins.items():
            self.displays[lcd_num] = st7789.ST7789(
                self.spi,
                cs=cs_pin,
                dc=self.dc_pin,
                rst=None,
                width=240,
                height=240,
                rotation=0,
                baudrate=1000000,
                y_offset=80,
            )

            self.disable_all_cs()
            time.sleep(0.05)
            
    def reset_all_displays(self):
        reset_pin = digitalio.DigitalInOut(RESET_PIN)
        reset_pin.direction = digitalio.Direction.OUTPUT

        reset_pin.value = True
        time.sleep(0.1)

        reset_pin.value = False
        time.sleep(0.2)

        reset_pin.value = True
        time.sleep(0.3)

        reset_pin.deinit()
        
    def disable_all_cs(self):
        for cs_pin in self.cs_pins.values():
            cs_pin.value = True
            
    def show_image(self, lcd_num, image):
        self.disable_all_cs()
        time.sleep(0.01)

        self.displays[lcd_num].image(image)

        self.disable_all_cs()
        time.sleep(0.01)
        
    def show_all(self, image):
        for lcd_num in self.displays.keys():
            self.show_image(lcd_num, image)
            
    def cleanup(self):
        self.disable_all_cs()

        for cs_pin in self.cs_pins.values():
            cs_pin.deinit()

        self.dc_pin.deinit()

def load_images(image_path, page):
    images = {}

    for lcd_num in range(1, 10):
        path = image_path / f"{page}{lcd_num}.png"
        image = Image.open(path).convert("RGB")
        image = image.resize((240, 240))

        images[lcd_num] = image
    return images
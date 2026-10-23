"""Mocked peripheral boundary: reset lifetime, chip selects and changed tiles."""

import sys
import types
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

from vttt.backends import RaspberryPiBackend
from vttt.config import hardware_config


class HardwareAdapterTests(unittest.TestCase):
    def make_modules(self, fail_at=None):
        self.pins = {}
        self.frames = []
        self.resets = []
        owner = self

        class Pin:
            def __init__(self, number):
                self.number, self.closed = number, False
                self._value = True
                owner.pins[number] = self

            def switch_to_output(self, value):
                self.value = value

            @property
            def value(self):
                return self._value

            @value.setter
            def value(self, value):
                self._value = value
                if self.number == 27:
                    owner.resets.append(value)

            def deinit(self):
                self.closed = True

        class Display:
            def __init__(self, spi, **kwargs):
                if fail_at is not None and len(owner.frames) == fail_at:
                    raise RuntimeError("synthetic initialization failure")
                owner.assertIsNone(kwargs["rst"])
                owner.assertTrue(owner.pins[27].value)
                self.cs = kwargs["cs"]
                self.calls = []
                owner.frames.append(self)

            def image(self, img):
                owner.assertTrue(all(owner.pins[x].value for x in hardware_config()["lcd_cs_pins"]))
                self.cs.value = False
                self.calls.append(img.copy())
                self.cs.value = True

        gpio = types.ModuleType("RPi.GPIO")
        gpio.BCM, gpio.IN, gpio.PUD_DOWN, gpio.PUD_UP = 11, 1, 21, 22
        self.setups, self.cleaned = [], []
        gpio.setmode = lambda mode: None
        gpio.setwarnings = lambda flag: None
        gpio.setup = lambda pin, direction, pull_up_down: self.setups.append((pin, pull_up_down))
        gpio.input = lambda pin: 0
        gpio.cleanup = lambda pins: self.cleaned.extend(pins)
        rpi = types.ModuleType("RPi")
        rpi.GPIO = gpio
        board = types.ModuleType("board")
        for n in range(28):
            setattr(board, "D" + str(n), n)
        self.spi = types.SimpleNamespace(closed=False)
        self.spi.deinit = lambda: setattr(self.spi, "closed", True)
        board.SPI = lambda: self.spi
        digitalio = types.ModuleType("digitalio")
        digitalio.DigitalInOut = Pin
        display = types.ModuleType("adafruit_rgb_display")
        display.st7789 = types.SimpleNamespace(ST7789=Display)
        return {"RPi": rpi, "RPi.GPIO": gpio, "board": board,
                "digitalio": digitalio, "adafruit_rgb_display": display}

    def test_shared_reset_once_and_only_changed_tiles_are_written(self):
        with patch.dict(sys.modules, self.make_modules()), patch("vttt.backends.time.sleep"):
            backend = RaspberryPiBackend(hardware_config())
            try:
                self.assertEqual(self.resets, [True, False, True])
                self.assertFalse(self.pins[27].closed)
                img = Image.new("RGB", (720, 720), "black")
                backend.show(img)
                backend.show(img)
                self.assertEqual([len(d.calls) for d in self.frames], [1] * 9)
                ImageDraw.Draw(img).rectangle((0, 0, 239, 239), fill="red")
                backend.show(img)
                self.assertEqual([len(d.calls) for d in self.frames], [2] + [1] * 8)
                self.assertTrue(all(pull == 21 for _, pull in self.setups))
            finally:
                backend.close()
            self.assertTrue(all(pin.closed for pin in self.pins.values()))
            self.assertTrue(self.spi.closed)
            self.assertEqual(self.cleaned, hardware_config()["button_pins"])

    def test_initialization_failure_releases_owned_peripherals(self):
        with patch.dict(sys.modules, self.make_modules(fail_at=3)), patch("vttt.backends.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                RaspberryPiBackend(hardware_config())
            self.assertTrue(all(pin.closed for pin in self.pins.values()))
            self.assertTrue(self.spi.closed)

    def test_active_low_config_and_screen_remapping(self):
        cfg = hardware_config()
        cfg["button_active_high"] = False
        cfg["screen_order"] = list(range(9, 0, -1))
        with patch.dict(sys.modules, self.make_modules()), patch("vttt.backends.time.sleep"):
            backend = RaspberryPiBackend(cfg)
            try:
                img = Image.new("RGB", (720, 720), "black")
                ImageDraw.Draw(img).rectangle((0, 0, 239, 239), fill="red")
                backend.show(img)
                self.assertEqual(self.frames[8].calls[0].getpixel((120, 120)), (255, 0, 0))
                self.assertEqual(self.frames[0].calls[0].getpixel((120, 120)), (0, 0, 0))
                self.assertTrue(all(pull == 22 for _, pull in self.setups))
            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main()

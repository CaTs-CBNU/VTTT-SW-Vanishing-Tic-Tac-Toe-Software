"""Mocked peripheral boundary: reset lifetime, chip selects and changed tiles."""

import sys
import types
import unittest
import json
import queue
import tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

from vttt.backends import RaspberryPiBackend, RecoveryButtonFilter
from vttt.config import hardware_config, button_active_high_for


class HardwareAdapterTests(unittest.TestCase):
    def test_local_button_override_is_scoped_and_validated(self):
        base = hardware_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'configs').mkdir()
            source = root / 'configs/hardware.json'
            source.write_text(json.dumps(base))
            local = root / 'configs/hardware.local.json'
            local.write_text(json.dumps({'button_active_high_overrides': {'5': False}}))
            with patch('vttt.config.ROOT', root):
                cfg = hardware_config()
                self.assertFalse(button_active_high_for(cfg, 5))
                self.assertTrue(all(button_active_high_for(cfg, b) for b in (1, 2, 3, 4, 6, 7, 8, 9)))
                self.assertTrue(button_active_high_for(hardware_config(source), 5))
                for invalid in ({'0': False}, {'10': False}, {'5': 'false'}, [False]):
                    local.write_text(json.dumps({'button_active_high_overrides': invalid}))
                    with self.assertRaises(ValueError):
                        hardware_config()

    def test_active_low_fifth_button_tap_and_hold_through_gpio_polling(self):
        cfg = hardware_config()
        cfg['button_active_high_overrides'] = {'5': False}
        for samples, expected in (
                ([(0, 1), (.1, 0), (.15, 0), (.2, 1), (.25, 1), (4, 1)], ['short']),
                ([(0, 1), (.1, 0), (.15, 0), (3.2, 0), (3.3, 1), (3.35, 1)], ['long'])):
            with self.subTest(expected=expected):
                index = [0]
                backend = RaspberryPiBackend.__new__(RaspberryPiBackend)
                backend.cfg = cfg
                backend.events = queue.Queue()
                backend.input_error = None
                backend.button_filter = RecoveryButtonFilter(cfg['debounce_ms'], cfg['long_press_ms'])
                backend.GPIO = types.SimpleNamespace(input=lambda pin: samples[index[0]][1] if pin == 13 else 0)
                backend.stop = types.SimpleNamespace(
                    is_set=lambda: index[0] >= len(samples),
                    wait=lambda delay: index.__setitem__(0, index[0] + 1))
                with patch('vttt.backends.time.monotonic', side_effect=lambda: samples[index[0]][0]):
                    backend._poll_buttons()
                self.assertIsNone(backend.input_error)
                events = list(backend.events.queue)
                self.assertEqual([event.kind for event in events], expected)
                self.assertTrue(all(event.button == 5 for event in events))

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

"""The same 720×720 frame and button events drive the Pi and desktop preview."""

import logging
import queue
import threading
import time

from .buttons import ButtonEvent, ButtonFilter

LOG = logging.getLogger(__name__)


def split_frame(frame):
    if frame.size != (720, 720):
        raise ValueError("A frame must be 720×720 pixels")
    return [frame.crop((c * 240, r * 240, (c + 1) * 240, (r + 1) * 240))
            for r in range(3) for c in range(3)]


class RecoveryButtonFilter(ButtonFilter):
    """Button 3 has an independent two-second hold; short clicks still work."""
    def __init__(self, debounce_ms=40, long_press_ms=2000):
        super().__init__(debounce_ms, long_press_ms)
        self.recovery = ButtonFilter(debounce_ms, 2000)

    def feed(self, button, pressed, now):
        if button == 3:
            return [ButtonEvent(3, event.kind, event.timestamp)
                    for event in self.recovery.feed(5, pressed, now)]
        return super().feed(button, pressed, now)


class DisplaySPI:
    """Override transaction speed through the public busio SPI interface.

    SPIDevice configures the bus before every transaction. Keeping the override
    here lets all nine drivers change speed without editing driver internals.
    This bus is dedicated to the LCDs.
    """
    def __init__(self, spi, baudrate):
        self.spi, self.baudrate = spi, baudrate

    def configure(self, **kwargs):
        kwargs["baudrate"] = self.baudrate
        return self.spi.configure(**kwargs)

    def __getattr__(self, name):
        return getattr(self.spi, name)


class RaspberryPiBackend:
    def __init__(self, cfg):
        # These dependencies are never imported by the simulator or rule tests.
        import RPi.GPIO as GPIO
        import board
        import digitalio
        from adafruit_rgb_display import st7789
        # Single-file update: use 6.4 MHz normally, 4 MHz during recovery.
        cfg = dict(cfg)
        cfg["baudrate"] = 6400000
        self.cfg, self.GPIO = cfg, GPIO
        self._display_class = st7789.ST7789
        self._last_frame = None
        self._recovery_notice_until = 0.0
        self._accept_after = float("-inf")
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.thread = None
        self.spi = None
        self.outputs, self.cs_pins, self.displays = [], [], []
        self.last_tiles = [None] * 9
        self.input_error = None
        self.closed = False
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            pull = GPIO.PUD_DOWN if cfg["button_active_high"] else GPIO.PUD_UP
            for pin in cfg["button_pins"]:
                GPIO.setup(pin, GPIO.IN, pull_up_down=pull)
            self.spi = DisplaySPI(board.SPI(), cfg["baudrate"])

            def output(number, value=True):
                pin = digitalio.DigitalInOut(getattr(board, "D" + str(number)))
                self.outputs.append(pin)
                pin.switch_to_output(value=value)
                return pin

            self.dc = output(cfg["dc_pin"])
            self.cs_pins = [output(number) for number in cfg["lcd_cs_pins"]]
            self.reset = output(cfg["reset_pin"])
            self._reset_displays()
            LOG.info("Image shifted? Hold button 3 for 2 seconds to reset all LCDs.")
            self.thread = threading.Thread(target=self._poll_buttons, daemon=True, name="vttt-buttons")
            self.thread.start()
        except Exception:
            self.close()
            raise

    def _reset_displays(self):
        self.disable_cs()
        time.sleep(0.1)
        self.reset.value = False
        time.sleep(0.2)
        self.reset.value = True
        time.sleep(0.3)
        self.displays = []
        for i, cs in enumerate(self.cs_pins):
            self.displays.append(self._display_class(
                self.spi, cs=cs, dc=self.dc, rst=None,
                width=240, height=240, baudrate=self.spi.baudrate,
                rotation=self.cfg["rotation"][i], x_offset=self.cfg["x_offset"],
                y_offset=self.cfg["y_offset"]))
            self.disable_cs()
        self.last_tiles = [None] * 9

    def _recover_displays(self):
        # Runs only in the main thread, never concurrently with an LCD write.
        self.spi.baudrate = 4000000
        LOG.info("Resetting all LCDs and redrawing at 4 MHz")
        self._reset_displays()
        self._recovery_notice_until = float("inf")
        if self._last_frame is not None:
            self.show(self._last_frame)
        # Future driver transactions use this rate through DisplaySPI.configure.
        self.spi.baudrate = 6400000
        self._accept_after = time.monotonic()
        self._recovery_notice_until = self._accept_after + 3.0
        LOG.info("LCD reset complete; normal speed restored to 6.4 MHz")

    def _with_recovery_hint(self, frame):
        from PIL import ImageDraw, ImageFont
        canvas = frame.copy()
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 14)
        except OSError:
            font = ImageFont.load_default()
        # Bottom of logical LCD 3, below the game piece.
        draw.rectangle((488, 198, 711, 234), fill="#F7F3EF")
        lines = (("LCD reset complete", "Normal speed restored")
                 if self._recovery_notice_until else
                 ("Image shifted?", "Hold 3 for 2s to reset"))
        for y, line in zip((207, 224), lines):
            draw.text((600, y), line, font=font, fill="#45494C", anchor="mm")
        return canvas

    def disable_cs(self):
        for pin in self.cs_pins:
            pin.value = True

    def _poll_buttons(self):
        filt = RecoveryButtonFilter(self.cfg["debounce_ms"], self.cfg["long_press_ms"])
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                for i, pin in enumerate(self.cfg["button_pins"], 1):
                    pressed = bool(self.GPIO.input(pin)) == self.cfg["button_active_high"]
                    for event in filt.feed(i, pressed, now):
                        self.events.put(event)
                self.stop.wait(self.cfg["poll_ms"] / 1000)
        except Exception as exc:
            self.input_error = exc
            LOG.exception("Button input failed")

    def show(self, frame):
        self._last_frame = frame.copy()
        frame = self._with_recovery_hint(frame)
        for logical, tile in enumerate(split_frame(frame)):
            payload = tile.tobytes()
            if payload == self.last_tiles[logical]:
                continue
            physical = self.cfg["screen_order"][logical] - 1
            self.disable_cs()
            try:
                self.displays[physical].image(tile)
            finally:
                self.disable_cs()
            self.last_tiles[logical] = payload

    def poll(self):
        if self.input_error:
            raise RuntimeError("버튼 입력을 읽지 못했습니다") from self.input_error
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                break
        result = [event for event in result if event.timestamp > self._accept_after]
        if any(event.button == 3 and event.kind == "long" for event in result):
            self._recover_displays()
            # Discard this batch; inputs started during recovery are filtered
            # by _accept_after even when their release arrives later.
            return []
        if self._recovery_notice_until and time.monotonic() >= self._recovery_notice_until:
            self._recovery_notice_until = 0.0
            if self._last_frame is not None:
                self.show(self._last_frame)
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        for pin in self.cs_pins:
            try:
                pin.value = True
            except Exception:
                pass
        for pin in reversed(self.outputs):
            try:
                pin.deinit()
            except Exception:
                LOG.debug("GPIO cleanup failed", exc_info=True)
        if self.spi:
            self.spi.deinit()
        self.GPIO.cleanup(self.cfg["button_pins"])


class DesktopBackend:
    def __init__(self, cfg):
        import tkinter as tk
        from PIL import ImageTk
        self.tk, self.ImageTk = tk, ImageTk
        self.root = tk.Tk()
        self.root.title("다이내믹 틱택토 · 9개 LCD 시뮬레이터")
        self.canvas = tk.Canvas(self.root, width=732, height=732, bg="#222222", highlightthickness=0)
        self.canvas.pack()
        tk.Label(self.root, text="칸 클릭 / 숫자 1~9 · 5 길게 또는 Esc: 일시정지 · 창 닫기: 종료").pack()
        self.events = []
        self.closed = False
        self.down = {}
        self.long_seconds = cfg["long_press_ms"] / 1000
        self.canvas.bind("<ButtonPress-1>", self._mouse_down)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_up)
        self.root.bind("<KeyPress>", self._key_down)
        self.root.bind("<KeyRelease>", self._key_up)
        self.root.bind("<FocusOut>", lambda _e: self.down.clear())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.photos = []

    def _cell(self, x, y):
        col, row = x // 244, y // 244
        return row * 3 + col + 1 if 0 <= col < 3 and 0 <= row < 3 else None

    def _mouse_down(self, event):
        cell = self._cell(event.x, event.y)
        if cell:
            self.down.setdefault("mouse", (cell, time.monotonic(), False))

    def _mouse_up(self, _event):
        self._release("mouse")

    def _key_down(self, event):
        if event.keysym == "Escape":
            self.events.append(ButtonEvent(5, "long", time.monotonic()))
        elif event.char in "123456789" and len(event.char) == 1:
            self.down.setdefault(event.keysym, (int(event.char), time.monotonic(), False))

    def _key_up(self, event):
        self._release(event.keysym)

    def _release(self, key):
        item = self.down.pop(key, None)
        if item and not item[2]:
            kind = "long" if item[0] == 5 and time.monotonic() - item[1] >= self.long_seconds else "short"
            self.events.append(ButtonEvent(item[0], kind, item[1]))

    def show(self, frame):
        self.photos = [self.ImageTk.PhotoImage(tile) for tile in split_frame(frame)]
        self.canvas.delete("all")
        for i, photo in enumerate(self.photos):
            self.canvas.create_image((i % 3) * 244 + 2, (i // 3) * 244 + 2, image=photo, anchor="nw")
        self.root.update_idletasks()

    def poll(self):
        if self.closed:
            return [ButtonEvent(0, "quit", time.monotonic())]
        self.root.update()
        now = time.monotonic()
        for key, (button, started, emitted) in list(self.down.items()):
            if button == 5 and not emitted and now - started >= self.long_seconds:
                self.events.append(ButtonEvent(5, "long", started))
                self.down[key] = (button, started, True)
        events, self.events = self.events, []
        return events

    def close(self):
        if not self.closed:
            self.closed = True
            self.root.destroy()


class HeadlessBackend:
    """Noninteractive adapter used by deterministic integration tests and previews."""
    def __init__(self):
        self.frame = None
        self.frames = 0
        self.events = []

    def show(self, frame):
        self.frame = frame.copy()
        self.frames += 1

    def poll(self):
        events, self.events = self.events, []
        return events

    def close(self):
        pass

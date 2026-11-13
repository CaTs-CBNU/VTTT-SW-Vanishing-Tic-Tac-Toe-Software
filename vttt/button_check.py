"""Show raw GPIO levels and filtered events without initializing the LCDs."""

import argparse
import sys
import time

from .buttons import ButtonFilter
from .config import hardware_config


def main():
    """Run with the game service stopped, then tap and release the chosen switch."""
    parser = argparse.ArgumentParser(description='Raw tact-switch input diagnostic')
    parser.add_argument('--button', type=int, choices=range(1, 10), default=5)
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--hardware-config')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('--seconds must be between 1 and 300')
    import RPi.GPIO as GPIO
    cfg = hardware_config(args.hardware_config)
    pin = cfg['button_pins'][args.button - 1]
    active_high = cfg['button_active_high']
    filt = ButtonFilter(cfg['debounce_ms'], cfg['long_press_ms'])
    # The selected switch can be held for diagnostic purposes, including non-centre switches.
    filt.long_buttons = {args.button}
    started = time.monotonic()
    previous = None
    GPIO.setmode(GPIO.BCM)
    try:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN if active_high else GPIO.PUD_UP)
        print('Button %d / BCM %d / active_%s / hold %.1fs' % (
            args.button, pin, 'high' if active_high else 'low', cfg['long_press_ms'] / 1000), flush=True)
        print('Start with the switch RELEASED. Tap once, release, then wait 4 seconds.', flush=True)
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            raw = int(GPIO.input(pin))
            pressed = bool(raw) == active_high
            if raw != previous:
                print('%6.2fs RAW=%d interpreted=%s' % (
                    now - started, raw, 'PRESSED' if pressed else 'RELEASED'), flush=True)
                previous = raw
            for event in filt.feed(args.button, pressed, now):
                print('%6.2fs EVENT=%s' % (now - started, event.kind.upper()), flush=True)
            time.sleep(cfg['poll_ms'] / 1000)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup(pin)
    return 0


if __name__ == '__main__':
    sys.exit(main())

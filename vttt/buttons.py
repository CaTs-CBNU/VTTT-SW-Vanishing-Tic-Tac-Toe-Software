"""Debounce and release-based clicks: a long press never also places a piece."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonEvent:
    button: int
    kind: str = "short"
    timestamp: float = 0.0  # Start of the press, so a held button cannot cross a screen transition.


class ButtonFilter:
    def __init__(self, debounce_ms=40, long_press_ms=1300):
        self.debounce = debounce_ms / 1000
        self.long_press = long_press_ms / 1000
        self.buttons = {}

    def feed(self, button, pressed, now):
        events = []
        if button not in self.buttons:
            # A button already held at boot must first be released.
            self.buttons[button] = {"raw": pressed, "stable": pressed, "change": now,
                                    "down": None, "long": False}
            return events
        b = self.buttons[button]
        if pressed != b["raw"]:
            b["raw"], b["change"] = pressed, now
        if b["stable"] != b["raw"] and now - b["change"] >= self.debounce:
            b["stable"] = b["raw"]
            if b["stable"]:
                b["down"], b["long"] = now, False
            else:
                if b["down"] is not None and not b["long"]:
                    events.append(ButtonEvent(button, "short", b["down"]))
                b["down"] = None
        if b["stable"] and b["raw"] and b["down"] is not None and not b["long"]:
            if button == 5 and now - b["down"] >= self.long_press:
                b["long"] = True
                events.append(ButtonEvent(button, "long", b["down"]))
        return events

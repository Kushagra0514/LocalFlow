import threading
import time

import keyboard
import pyperclip


class OutputPublisher:
    def __init__(
        self,
        auto_paste: bool,
        shutdown_event: threading.Event,
        side_effect_lock: threading.Lock,
        copy=pyperclip.copy,
        paste=lambda: keyboard.send("ctrl+v"),
        delay=time.sleep,
    ):
        self.auto_paste = auto_paste
        self.shutdown_event = shutdown_event
        self.side_effect_lock = side_effect_lock
        self.copy = copy
        self.paste = paste
        self.delay = delay

    def publish(self, text: str) -> bool:
        try:
            with self.side_effect_lock:
                if self.shutdown_event.is_set():
                    print("Result not copied because LocalFlow is shutting down.")
                    return False
                self.copy(text)
        except Exception as error:
            print(f"Clipboard error: could not copy the result: {error}")
            return False

        if not self.auto_paste:
            return True
        self.delay(0.1)
        try:
            with self.side_effect_lock:
                if self.shutdown_event.is_set():
                    print("Automatic paste skipped because LocalFlow is shutting down.")
                    return True
                self.paste()
        except Exception as error:
            print(f"Automatic paste error: {error}. The result remains on the clipboard.")
        return True


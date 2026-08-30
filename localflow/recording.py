import threading
from collections.abc import Callable

import keyboard
import numpy as np
import sounddevice as sd

from localflow.types import JobPurpose, Recording
from localflow.whisper import CHANNELS, SAMPLE_RATE

MIN_RECORDING_SECONDS = 0.3
MAX_RECORDING_SECONDS = 60
MIN_RECORDING_SAMPLES = int(SAMPLE_RATE * MIN_RECORDING_SECONDS)
MAX_RECORDING_SAMPLES = SAMPLE_RATE * MAX_RECORDING_SECONDS


def parse_hotkey(hotkey: str, keyboard_module=keyboard):
    parts = tuple(part.strip() for part in hotkey.split("+"))
    if not parts or any(not part for part in parts):
        raise ValueError("HOTKEY must contain one or more key names.")
    parts = tuple(keyboard_module.normalize_name(part) for part in parts)
    if len(set(parts)) != len(parts):
        raise ValueError("HOTKEY cannot contain the same key more than once.")
    if len(parts) > 1 and (
        any(part not in keyboard_module.all_modifiers for part in parts[:-1])
        or parts[-1] in keyboard_module.all_modifiers
    ):
        raise ValueError(
            "HOTKEY combinations must list modifiers first and one "
            "non-modifier key last, for example ctrl+shift+space."
        )
    try:
        code_groups = tuple(
            frozenset(keyboard_module.key_to_scan_codes(part)) for part in parts
        )
    except ValueError as error:
        raise ValueError(f"Invalid HOTKEY {hotkey!r}: {error}") from error
    return "+".join(parts), code_groups[:-1], code_groups[-1]


class Recorder:
    def __init__(
        self,
        hotkey: str,
        claim: Callable[[JobPurpose], bool],
        complete: Callable[[Recording], None],
        discard: Callable[[], None],
        purpose: JobPurpose = JobPurpose.DICTATION,
        keyboard_module=keyboard,
        stream_factory=sd.InputStream,
        timer_factory=threading.Timer,
    ):
        self.keyboard = keyboard_module
        self.stream_factory = stream_factory
        self.timer_factory = timer_factory
        self.claim = claim
        self.complete = complete
        self.discard = discard
        self.purpose = purpose
        self.hotkey, self.modifier_codes, self.trigger_codes = parse_hotkey(
            hotkey, keyboard_module
        )
        self.pressed_codes = set()
        self.hotkey_is_down = False
        self.stream = None
        self.timer = None
        self.buffer = []
        self.recorded_samples = 0
        self.active_purpose = None
        self._lock = threading.Lock()

    def audio_callback(self, indata, frames, callback_time, status):
        if status:
            print(f"Microphone status: {status}")
        with self._lock:
            if self.active_purpose is None:
                return
            remaining = MAX_RECORDING_SAMPLES - self.recorded_samples
            if remaining > 0:
                chunk = indata[:remaining].copy()
                self.buffer.append(chunk)
                self.recorded_samples += len(chunk)

    @staticmethod
    def close_stream(audio_stream):
        if audio_stream is None:
            return
        try:
            audio_stream.stop()
        except Exception as error:
            print(f"Microphone error while stopping the stream: {error}")
        try:
            audio_stream.close()
        except Exception as error:
            print(f"Microphone error while closing the stream: {error}")

    def start(self):
        if not self.claim(self.purpose):
            return
        with self._lock:
            self.buffer.clear()
            self.recorded_samples = 0
            self.active_purpose = self.purpose

        audio_stream = None
        try:
            audio_stream = self.stream_factory(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=self.audio_callback,
            )
            audio_stream.start()
        except Exception as error:
            self.close_stream(audio_stream)
            with self._lock:
                self.active_purpose = None
            print(f"Microphone error: could not start recording: {error}")
            self.discard()
            return

        timer = self.timer_factory(MAX_RECORDING_SECONDS, self.on_timeout)
        timer.daemon = True
        with self._lock:
            if self.active_purpose is not None:
                self.stream = audio_stream
                self.timer = timer
                accepted = True
            else:
                accepted = False
        if not accepted:
            self.close_stream(audio_stream)
            return
        try:
            timer.start()
        except RuntimeError as error:
            print(f"Recording error: could not start the duration limit: {error}")
            self.stop()
            return
        print("\n[Recording started - speak now!]")

    def on_timeout(self):
        self.stop(
            f"Maximum recording length of {MAX_RECORDING_SECONDS} seconds reached."
        )

    def stop(self, reason=None):
        with self._lock:
            if self.active_purpose is None:
                return
            purpose = self.active_purpose
            self.active_purpose = None
            audio_stream, self.stream = self.stream, None
            timer, self.timer = self.timer, None
            chunks = list(self.buffer)
            self.buffer.clear()
            sample_count = self.recorded_samples
            self.recorded_samples = 0

        if timer is not None:
            timer.cancel()
        self.close_stream(audio_stream)
        print("[Recording stopped]")
        if reason:
            print(reason)
        if sample_count < MIN_RECORDING_SAMPLES:
            print(
                f"Recording too short; hold the hotkey for at least "
                f"{MIN_RECORDING_SECONDS:.1f} seconds."
            )
            self.discard()
            return
        try:
            samples = np.concatenate(chunks, axis=0).flatten()
        except Exception as error:
            print(f"Audio processing error: could not prepare the recording: {error}")
            self.discard()
            return
        self.complete(Recording(purpose, samples))

    def handle_hotkey_event(self, event):
        scan_code = event.scan_code
        if event.event_type == self.keyboard.KEY_DOWN:
            is_new_press = scan_code not in self.pressed_codes
            self.pressed_codes.add(scan_code)
            if (
                is_new_press
                and not self.hotkey_is_down
                and scan_code in self.trigger_codes
                and all(codes & self.pressed_codes for codes in self.modifier_codes)
            ):
                self.hotkey_is_down = True
                self.start()
        elif event.event_type == self.keyboard.KEY_UP:
            self.pressed_codes.discard(scan_code)
            if self.hotkey_is_down and (
                scan_code in self.trigger_codes
                or not all(codes & self.pressed_codes for codes in self.modifier_codes)
            ):
                self.hotkey_is_down = False
                self.stop()

    def hook(self):
        self.keyboard.hook(self.handle_hotkey_event, suppress=False)

    def wait(self):
        self.keyboard.wait()

    def shutdown(self):
        with self._lock:
            audio_stream, self.stream = self.stream, None
            timer, self.timer = self.timer, None
            self.active_purpose = None
            self.buffer.clear()
            self.recorded_samples = 0
            self.pressed_codes.clear()
            self.hotkey_is_down = False
        try:
            self.keyboard.unhook_all()
        except Exception as error:
            print(f"Keyboard cleanup error: {error}")
        if timer is not None:
            timer.cancel()
        self.close_stream(audio_stream)


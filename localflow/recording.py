import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

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


@dataclass(frozen=True)
class HotkeyBinding:
    purpose: JobPurpose
    hotkey: str
    modifier_codes: tuple[frozenset[int], ...]
    trigger_codes: frozenset[int]


def parse_binding(purpose: JobPurpose, hotkey: str, keyboard_module=keyboard):
    normalized, modifier_codes, trigger_codes = parse_hotkey(
        hotkey, keyboard_module
    )
    return HotkeyBinding(purpose, normalized, modifier_codes, trigger_codes)


def bindings_conflict(first: HotkeyBinding, second: HotkeyBinding) -> bool:
    if first.trigger_codes & second.trigger_codes:
        return True
    if any(first.trigger_codes & codes for codes in second.modifier_codes):
        return True
    return any(second.trigger_codes & codes for codes in first.modifier_codes)


class Recorder:
    def __init__(
        self,
        hotkeys: Mapping[JobPurpose, str],
        claim: Callable[[JobPurpose], bool],
        complete: Callable[[Recording], None],
        discard: Callable[[], None],
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
        self.bindings = tuple(
            parse_binding(purpose, hotkey, keyboard_module)
            for purpose, hotkey in hotkeys.items()
        )
        if not self.bindings:
            raise ValueError("At least one hotkey binding is required.")
        self.hotkeys = {
            binding.purpose: binding.hotkey for binding in self.bindings
        }
        self.pressed_codes = set()
        self.active_binding = None
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

    def start(self, purpose: JobPurpose) -> bool:
        if not self.claim(purpose):
            return False
        with self._lock:
            self.buffer.clear()
            self.recorded_samples = 0
            self.active_purpose = purpose

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
            return False

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
            return False
        try:
            timer.start()
        except RuntimeError as error:
            print(f"Recording error: could not start the duration limit: {error}")
            self.stop()
            return False
        print("\n[Recording started - speak now!]")
        return True

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
            if is_new_press and self.active_binding is None:
                for binding in self.bindings:
                    if (
                        scan_code in binding.trigger_codes
                        and all(
                            codes & self.pressed_codes
                            for codes in binding.modifier_codes
                        )
                    ):
                        if self.start(binding.purpose):
                            self.active_binding = binding
                        break
        elif event.event_type == self.keyboard.KEY_UP:
            self.pressed_codes.discard(scan_code)
            binding = self.active_binding
            if binding is not None and (
                scan_code in binding.trigger_codes
                or not all(
                    codes & self.pressed_codes for codes in binding.modifier_codes
                )
            ):
                self.active_binding = None
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
            self.active_binding = None
        try:
            self.keyboard.unhook_all()
        except Exception as error:
            print(f"Keyboard cleanup error: {error}")
        if timer is not None:
            timer.cancel()
        self.close_stream(audio_stream)

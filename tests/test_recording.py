import unittest
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import keyboard
import numpy as np

from localflow.recording import (
    MAX_RECORDING_SAMPLES,
    MIN_RECORDING_SAMPLES,
    Recorder,
    parse_hotkey,
)
from localflow.types import JobPurpose


class HotkeyTest(unittest.TestCase):
    @staticmethod
    def recorder():
        return Recorder(
            {JobPurpose.DICTATION: "ctrl+shift+space"},
            MagicMock(return_value=True),
            MagicMock(),
            MagicMock(),
        )

    @staticmethod
    def send(recorder, event_type, key):
        recorder.handle_hotkey_event(
            SimpleNamespace(
                event_type=event_type,
                scan_code=keyboard.key_to_scan_codes(key)[0],
            )
        )

    def test_single_and_combination_hotkeys_parse(self):
        self.assertEqual(parse_hotkey("f23")[0], "f23")
        self.assertEqual(parse_hotkey("ctrl+shift+space")[0], "ctrl+shift+space")

    def test_invalid_hotkeys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "one or more key names"):
            parse_hotkey("")
        with self.assertRaisesRegex(ValueError, "modifiers first"):
            parse_hotkey("ctrl+space+shift")

    def test_repeat_is_ignored_and_release_stops_once(self):
        recorder = self.recorder()
        recorder.start = MagicMock(return_value=True)
        recorder.stop = MagicMock()
        for key in ("ctrl", "shift", "space", "space"):
            self.send(recorder, keyboard.KEY_DOWN, key)
        self.send(recorder, keyboard.KEY_UP, "space")
        recorder.start.assert_called_once_with(JobPurpose.DICTATION)
        recorder.stop.assert_called_once_with()

    def test_single_key_repeat_is_ignored(self):
        recorder = Recorder(
            {JobPurpose.DICTATION: "f23"},
            MagicMock(return_value=True),
            MagicMock(),
            MagicMock(),
        )
        recorder.start = MagicMock(return_value=True)
        recorder.stop = MagicMock()
        self.send(recorder, keyboard.KEY_DOWN, "f23")
        self.send(recorder, keyboard.KEY_DOWN, "f23")
        self.send(recorder, keyboard.KEY_UP, "f23")
        recorder.start.assert_called_once_with(JobPurpose.DICTATION)
        recorder.stop.assert_called_once_with()

    def test_releasing_required_modifier_stops(self):
        recorder = self.recorder()
        recorder.start = MagicMock(return_value=True)
        recorder.stop = MagicMock()
        for key in ("ctrl", "shift", "space"):
            self.send(recorder, keyboard.KEY_DOWN, key)
        self.send(recorder, keyboard.KEY_UP, "shift")
        recorder.stop.assert_called_once_with()

    def test_each_binding_starts_its_fixed_purpose(self):
        recorder = Recorder(
            {
                JobPurpose.DICTATION: "f23",
                JobPurpose.COMMAND: "ctrl+shift+space",
            },
            MagicMock(return_value=True),
            MagicMock(),
            MagicMock(),
        )
        recorder.start = MagicMock(return_value=True)
        recorder.stop = MagicMock()
        for key in ("ctrl", "shift", "space"):
            self.send(recorder, keyboard.KEY_DOWN, key)
        recorder.start.assert_called_once_with(JobPurpose.COMMAND)

    def test_other_binding_and_its_release_cannot_stop_or_reroute_active_job(self):
        recorder = Recorder(
            {
                JobPurpose.DICTATION: "f23",
                JobPurpose.COMMAND: "ctrl+shift+space",
            },
            MagicMock(return_value=True),
            MagicMock(),
            MagicMock(),
        )
        recorder.start = MagicMock(return_value=True)
        recorder.stop = MagicMock()
        self.send(recorder, keyboard.KEY_DOWN, "f23")
        for key in ("ctrl", "shift", "space"):
            self.send(recorder, keyboard.KEY_DOWN, key)
        self.send(recorder, keyboard.KEY_UP, "space")
        recorder.start.assert_called_once_with(JobPurpose.DICTATION)
        recorder.stop.assert_not_called()
        self.send(recorder, keyboard.KEY_UP, "f23")
        recorder.stop.assert_called_once_with()


class RecorderTest(unittest.TestCase):
    def make_recorder(self, **kwargs):
        self.claim = MagicMock(return_value=True)
        self.complete = MagicMock()
        self.discard = MagicMock()
        self.stream = kwargs.pop("stream", MagicMock())
        self.timer = kwargs.pop("timer", MagicMock())
        return Recorder(
            {JobPurpose.DICTATION: "f23"},
            self.claim,
            self.complete,
            self.discard,
            stream_factory=kwargs.pop("stream_factory", MagicMock(return_value=self.stream)),
            timer_factory=kwargs.pop("timer_factory", MagicMock(return_value=self.timer)),
            **kwargs,
        )

    def test_resources_and_purpose_are_owned_together(self):
        recorder = self.make_recorder()
        recorder.start(JobPurpose.DICTATION)
        samples = np.ones((MIN_RECORDING_SAMPLES, 1), dtype=np.float32)
        recorder.audio_callback(samples, len(samples), None, None)
        recorder.stop()
        recording = self.complete.call_args.args[0]
        self.assertIs(recording.purpose, JobPurpose.DICTATION)
        self.assertEqual(len(recording.samples), MIN_RECORDING_SAMPLES)
        self.stream.stop.assert_called_once_with()
        self.stream.close.assert_called_once_with()
        self.timer.cancel.assert_called_once_with()

    def test_buffer_is_bounded(self):
        recorder = self.make_recorder()
        recorder.active_purpose = JobPurpose.DICTATION
        recorder.recorded_samples = MAX_RECORDING_SAMPLES - 5
        samples = np.ones((10, 1), dtype=np.float32)
        recorder.audio_callback(samples, len(samples), None, None)
        recorder.audio_callback(samples, len(samples), None, None)
        self.assertEqual(recorder.recorded_samples, MAX_RECORDING_SAMPLES)
        self.assertEqual(sum(len(chunk) for chunk in recorder.buffer), 5)

    def test_short_recording_is_discarded(self):
        recorder = self.make_recorder()
        recorder.start(JobPurpose.DICTATION)
        recorder.audio_callback(
            np.ones((MIN_RECORDING_SAMPLES - 1, 1), dtype=np.float32),
            MIN_RECORDING_SAMPLES - 1,
            None,
            None,
        )
        with patch("sys.stdout", new_callable=StringIO) as output:
            recorder.stop()
        self.complete.assert_not_called()
        self.discard.assert_called_once_with()
        self.assertIn("Recording too short", output.getvalue())

    def test_microphone_failure_discards_recording(self):
        recorder = self.make_recorder(
            stream_factory=MagicMock(side_effect=OSError("no input device"))
        )
        with patch("sys.stdout", new_callable=StringIO) as output:
            recorder.start(JobPurpose.DICTATION)
        self.discard.assert_called_once_with()
        self.assertIsNone(recorder.active_purpose)
        self.assertIn("Microphone error", output.getvalue())

    def test_shutdown_closes_owned_microphone_and_timer(self):
        recorder = self.make_recorder()
        recorder.start(JobPurpose.DICTATION)
        with patch.object(recorder.keyboard, "unhook_all"):
            recorder.shutdown()
        self.stream.stop.assert_called_once_with()
        self.stream.close.assert_called_once_with()
        self.timer.cancel.assert_called_once_with()
        self.assertIsNone(recorder.active_purpose)


if __name__ == "__main__":
    unittest.main()

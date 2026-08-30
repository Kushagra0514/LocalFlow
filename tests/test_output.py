import threading
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from localflow.output import OutputPublisher


class OutputPublisherTest(unittest.TestCase):
    def publisher(self, auto_paste=False):
        self.shutdown = threading.Event()
        self.copy = MagicMock()
        self.paste = MagicMock()
        self.delay = MagicMock()
        return OutputPublisher(
            auto_paste,
            self.shutdown,
            threading.Lock(),
            copy=self.copy,
            paste=self.paste,
            delay=self.delay,
        )

    def test_copy_without_automatic_paste(self):
        self.publisher().publish("raw")
        self.copy.assert_called_once_with("raw")
        self.paste.assert_not_called()

    def test_copy_and_opt_in_paste(self):
        self.publisher(auto_paste=True).publish("raw")
        self.copy.assert_called_once_with("raw")
        self.paste.assert_called_once_with()

    def test_clipboard_failure_is_reported(self):
        publisher = self.publisher()
        self.copy.side_effect = RuntimeError("clipboard busy")
        with patch("sys.stdout", new_callable=StringIO) as output:
            self.assertFalse(publisher.publish("raw"))
        self.assertIn("Clipboard error", output.getvalue())

    def test_shutdown_guard_prevents_copy(self):
        publisher = self.publisher(auto_paste=True)
        self.shutdown.set()
        publisher.publish("raw")
        self.copy.assert_not_called()
        self.paste.assert_not_called()

    def test_shutdown_between_copy_and_paste_prevents_paste(self):
        publisher = self.publisher(auto_paste=True)
        self.delay.side_effect = lambda _seconds: self.shutdown.set()
        publisher.publish("raw")
        self.copy.assert_called_once_with("raw")
        self.paste.assert_not_called()


if __name__ == "__main__":
    unittest.main()


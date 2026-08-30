import unittest

from localflow.pipeline import Pipeline, raw_dictation
from localflow.types import JobPurpose


class PipelineTest(unittest.TestCase):
    def test_routes_dictation_to_registered_handler(self):
        pipeline = Pipeline({JobPurpose.DICTATION: lambda text: text.upper()})
        result = pipeline.handle(JobPurpose.DICTATION, "hello")
        self.assertEqual(result.raw_text, "hello")
        self.assertEqual(result.text, "HELLO")

    def test_raw_dictation_is_identity(self):
        self.assertEqual(raw_dictation("raw transcript"), "raw transcript")

    def test_unregistered_purpose_is_rejected(self):
        pipeline = Pipeline({JobPurpose.DICTATION: raw_dictation})
        with self.assertRaisesRegex(ValueError, "No transcript handler"):
            pipeline.handle(JobPurpose.COMMAND, "open chrome")


if __name__ == "__main__":
    unittest.main()


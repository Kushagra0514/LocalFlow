import re
import tempfile
import tomllib
import unittest
from pathlib import Path

import main


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WHISPER_MODEL = "ggml-base.en-q5_1.bin"


class ReleaseConsistencyTest(unittest.TestCase):
    def test_whisper_model_is_consistent(self):
        package_test = (ROOT / "packaging" / "test_package.ps1").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        self.assertEqual(main.WHISPER_MODEL.name, EXPECTED_WHISPER_MODEL)
        self.assertEqual(main.MODEL_SPECS[0].filename, EXPECTED_WHISPER_MODEL)
        self.assertIn(EXPECTED_WHISPER_MODEL, package_test)
        self.assertIn(EXPECTED_WHISPER_MODEL, notices)
        self.assertIn("`base.en`", readme)
        self.assertNotIn("ggml-small.en-q5_1.bin", package_test + notices)
        self.assertNotIn("`small.en`", readme)

    def test_cleanup_defaults_are_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_config = Path(directory) / "missing-config.txt"
            defaults = main.load_config(missing_config)
        configured = main.load_config(ROOT / "config.txt")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertFalse(main.CLEANUP)
        self.assertEqual(defaults["CLEANUP"], "false")
        self.assertEqual(configured["CLEANUP"], "false")
        self.assertIn("CLEANUP=false", readme)
        self.assertEqual(defaults["AUTO_PASTE"], "false")
        self.assertEqual(configured["AUTO_PASTE"], "false")
        self.assertIn("AUTO_PASTE=false", readme)

    def test_application_version_is_consistent(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        expected = project["project"]["version"]
        files_and_patterns = (
            ("main.py", r'^APP_VERSION = "([^"]+)"$'),
            ("uv.lock", r'(?ms)^name = "localflow"\nversion = "([^"]+)"$'),
            ("packaging/build_windows.ps1", r'^    version = "([^"]+)"$'),
            ("packaging/LocalFlow.iss", r'^#define AppVersion "([^"]+)"$'),
        )

        self.assertEqual(main.APP_VERSION, expected)
        for relative_path, pattern in files_and_patterns:
            text = (ROOT / relative_path).read_text(encoding="utf-8-sig")
            match = re.search(pattern, text, re.MULTILINE)
            self.assertIsNotNone(match, f"Version not found in {relative_path}")
            self.assertEqual(match.group(1), expected, relative_path)


if __name__ == "__main__":
    unittest.main()

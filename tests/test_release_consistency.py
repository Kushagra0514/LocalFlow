import re
import tempfile
import tomllib
import unittest
from pathlib import Path

import main
from localflow import APP_VERSION
from localflow.cloud import PROVIDERS
from localflow.config import load_config
from localflow.whisper import WHISPER_MODEL_SPEC


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WHISPER_MODEL = "ggml-base.en-q5_1.bin"
EXPECTED_RELEASE_VERSION = "0.2.0"


class ReleaseConsistencyTest(unittest.TestCase):
    def test_whisper_model_is_consistent(self):
        package_test = (ROOT / "packaging" / "test_package.ps1").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        self.assertEqual(WHISPER_MODEL_SPEC.filename, EXPECTED_WHISPER_MODEL)
        self.assertIn(EXPECTED_WHISPER_MODEL, package_test)
        self.assertIn(EXPECTED_WHISPER_MODEL, notices)
        self.assertIn("`base.en`", readme)
        self.assertNotIn("ggml-small.en-q5_1.bin", package_test + notices)
        self.assertNotIn("`small.en`", readme)

    def test_raw_dictation_defaults_are_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = load_config(
                root / "config.ini", ROOT / "config.default.ini"
            )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertFalse(hasattr(main, "CLEANUP"))
        self.assertFalse(defaults.auto_paste)
        self.assertFalse(defaults.cleanup_enabled)
        self.assertFalse(defaults.commands_enabled)
        self.assertEqual(defaults.ai.model, PROVIDERS[defaults.ai.provider].default_model)
        self.assertIn("auto_paste = false", readme)
        self.assertIn("[cleanup]\nenabled = false", readme)

    def test_active_release_has_no_local_cleanup_stack(self):
        active_release = "\n".join(
            (ROOT / path).read_text(encoding="utf-8-sig")
            for path in (
                "localflow/whisper.py",
                "config.default.ini",
                "packaging/build_windows.ps1",
                "THIRD_PARTY_NOTICES.md",
            )
        ).lower()

        for obsolete in ("s1-mini", "llama.cpp", "llama-server", ".gguf"):
            self.assertNotIn(obsolete, active_release)

    def test_application_version_is_consistent(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        expected = project["project"]["version"]
        files_and_patterns = (
            ("localflow/__init__.py", r'^APP_VERSION = "([^"]+)"$'),
            ("uv.lock", r'(?ms)^name = "localflow"\nversion = "([^"]+)"$'),
            ("packaging/build_windows.ps1", r'^    version = "([^"]+)"$'),
            ("packaging/LocalFlow.iss", r'^#define AppVersion "([^"]+)"$'),
        )

        self.assertEqual(APP_VERSION, expected)
        self.assertEqual(expected, EXPECTED_RELEASE_VERSION)
        for relative_path, pattern in files_and_patterns:
            text = (ROOT / relative_path).read_text(encoding="utf-8-sig")
            match = re.search(pattern, text, re.MULTILINE)
            self.assertIsNotNone(match, f"Version not found in {relative_path}")
            self.assertEqual(match.group(1), expected, relative_path)

    def test_release_descriptions_are_local_first(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Local-first", project["project"]["description"])
        self.assertIn("LocalFlow is a local-first", readme)
        self.assertNotIn("Fully local", project["project"]["description"])

    def test_main_is_only_bootstrap(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        for forbidden in (
            "import keyboard",
            "import numpy",
            "import sounddevice",
            "import pyperclip",
            "def transcribe_audio",
            "def audio_callback",
            "def process_transcription",
        ):
            self.assertNotIn(forbidden, source)

    def test_provider_transport_details_stay_in_cloud_module(self):
        other_modules = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "localflow").glob("*.py")
            if path.name != "cloud.py"
        )
        for provider_detail in (
            "api.groq.com",
            "GROQ_API_KEY",
            '"Authorization"',
            "tool_calls",
        ):
            self.assertNotIn(provider_detail, other_modules)


if __name__ == "__main__":
    unittest.main()

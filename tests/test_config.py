import configparser
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import main
from localflow.config import load_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.default.ini"


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.live = self.root / "config.ini"
        self.legacy = self.root / "config.txt"

    def tearDown(self):
        self.temporary.cleanup()

    def parser(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(DEFAULT_CONFIG, encoding="utf-8")
        return parser

    def write_live(self, mutate=None):
        parser = self.parser()
        if mutate:
            mutate(parser)
        with self.live.open("w", encoding="utf-8") as file:
            parser.write(file)
        return self.live.read_bytes()

    def load(self):
        return load_config(self.live, DEFAULT_CONFIG, self.legacy)

    def test_safe_defaults_create_one_typed_immutable_config(self):
        config = self.load()
        self.assertEqual(config.path, self.live)
        self.assertEqual(config.hotkeys.dictation, "f23")
        self.assertEqual(config.hotkeys.command, "ctrl+shift+.")
        self.assertFalse(config.auto_paste)
        self.assertFalse(config.cleanup_enabled)
        self.assertFalse(config.commands_enabled)
        self.assertEqual(config.ai.provider, "groq")
        self.assertEqual(config.ai.timeout_seconds, 15)
        with self.assertRaises(FrozenInstanceError):
            config.auto_paste = True
        self.assertTrue(self.live.is_file())
        self.assertEqual(list(self.root.glob("*.ini")), [self.live])
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_valid_edits_are_typed(self):
        def mutate(parser):
            parser["hotkeys"]["dictation"] = "ctrl+shift+space"
            parser["output"]["auto_paste"] = "true"
            parser["cleanup"]["enabled"] = "true"
            parser["commands"]["enabled"] = "true"
            parser["ai"]["timeout_seconds"] = "30"

        self.write_live(mutate)
        config = self.load()
        self.assertEqual(config.hotkeys.dictation, "ctrl+shift+space")
        self.assertTrue(config.auto_paste)
        self.assertTrue(config.cleanup_enabled)
        self.assertTrue(config.commands_enabled)
        self.assertEqual(config.ai.timeout_seconds, 30)

    def test_legacy_import_is_first_run_only_and_privacy_safe(self):
        legacy = "HOTKEY=f12\nAUTO_PASTE=true\nCLEANUP=true\n"
        self.legacy.write_text(legacy, encoding="utf-8")
        config = self.load()
        self.assertEqual(config.hotkeys.dictation, "f12")
        self.assertTrue(config.auto_paste)
        self.assertFalse(config.cleanup_enabled)
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), legacy)

    def test_existing_ini_is_never_merged_or_overwritten(self):
        original = self.write_live(
            lambda parser: parser["hotkeys"].__setitem__("dictation", "f12")
        )
        self.legacy.write_text("HOTKEY=f11\nAUTO_PASTE=true\n", encoding="utf-8")
        config = self.load()
        self.assertEqual(config.hotkeys.dictation, "f12")
        self.assertFalse(config.auto_paste)
        self.assertEqual(self.live.read_bytes(), original)

    def test_invalid_existing_ini_is_not_overwritten(self):
        original = b"[hotkeys]\ndictation = f23\n"
        self.live.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "Missing configuration section"):
            self.load()
        self.assertEqual(self.live.read_bytes(), original)

    def test_invalid_legacy_value_does_not_create_ini(self):
        self.legacy.write_text("AUTO_PASTE=maybe\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "true or false"):
            self.load()
        self.assertFalse(self.live.exists())

    def test_unknown_sections_keys_and_secret_fields_are_rejected(self):
        mutations = (
            lambda parser: parser.add_section("network"),
            lambda parser: parser["ai"].__setitem__("endpoint", "https://example.com"),
            lambda parser: parser["ai"].__setitem__("api_key", "secret"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.live.unlink(missing_ok=True)
                self.write_live(mutate)
                with self.assertRaisesRegex(ValueError, "Unknown"):
                    self.load()

    def test_unknown_provider_is_rejected(self):
        self.write_live(
            lambda parser: parser["ai"].__setitem__("provider", "openai")
        )
        with self.assertRaisesRegex(ValueError, r"Unknown \[ai\] provider"):
            self.load()

    def test_missing_sections_and_keys_are_rejected(self):
        mutations = (
            lambda parser: parser.remove_section("commands"),
            lambda parser: parser["ai"].pop("model"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.live.unlink(missing_ok=True)
                self.write_live(mutate)
                with self.assertRaisesRegex(ValueError, "Missing"):
                    self.load()

    def test_malformed_ini_is_rejected_without_rewrite(self):
        original = b"this is not ini\n"
        self.live.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "Invalid configuration syntax"):
            self.load()
        self.assertEqual(self.live.read_bytes(), original)

    def test_invalid_booleans_and_timeouts_are_rejected(self):
        mutations = (
            (lambda parser: parser["output"].__setitem__("auto_paste", "maybe"), "true or false"),
            (lambda parser: parser["ai"].__setitem__("timeout_seconds", "slow"), "integer"),
            (lambda parser: parser["ai"].__setitem__("timeout_seconds", "0"), "1 to 120"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message):
                self.live.unlink(missing_ok=True)
                self.write_live(mutate)
                with self.assertRaisesRegex(ValueError, message):
                    self.load()

    def test_malformed_and_conflicting_hotkeys_are_rejected(self):
        mutations = (
            lambda parser: parser["hotkeys"].__setitem__("dictation", "ctrl+space+shift"),
            lambda parser: parser["hotkeys"].__setitem__("command", "f23"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.live.unlink(missing_ok=True)
                self.write_live(mutate)
                with self.assertRaisesRegex(ValueError, "hotkeys"):
                    self.load()

    def test_config_path_and_check_config_use_localflow_data_dir(self):
        with (
            patch.dict(os.environ, {"LOCALFLOW_DATA_DIR": str(self.root)}),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            self.assertEqual(main.main(["--config-path"]), 0)
        self.assertEqual(output.getvalue().strip(), str(self.live))

        with (
            patch.dict(os.environ, {"LOCALFLOW_DATA_DIR": str(self.root)}),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            self.assertEqual(main.main(["--check-config"]), 0)
        self.assertIn("Configuration is valid", output.getvalue())
        self.assertTrue(self.live.is_file())


if __name__ == "__main__":
    unittest.main()

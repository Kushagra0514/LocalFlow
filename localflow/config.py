from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    hotkey: str = "f23"
    auto_paste: bool = False


def load_config(path: Path) -> AppConfig:
    settings = {"HOTKEY": "f23", "AUTO_PASTE": "false"}
    if path.exists():
        with path.open(encoding="utf-8") as config_file:
            for line in config_file:
                key, separator, value = line.strip().partition("=")
                key = key.strip().upper()
                if separator and key in settings:
                    settings[key] = value.strip()

    auto_paste = settings["AUTO_PASTE"].lower()
    if auto_paste not in {"true", "false"}:
        raise ValueError("AUTO_PASTE must be either true or false.")
    return AppConfig(settings["HOTKEY"], auto_paste == "true")


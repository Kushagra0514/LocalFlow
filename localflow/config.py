import configparser
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from localflow.recording import parse_hotkey

LIVE_CONFIG_FILENAME = "config.ini"
ALLOWED_PROVIDERS = frozenset({"groq"})
SCHEMA = {
    "hotkeys": frozenset({"dictation", "command"}),
    "output": frozenset({"auto_paste"}),
    "cleanup": frozenset({"enabled"}),
    "commands": frozenset({"enabled"}),
    "ai": frozenset({"provider", "model", "timeout_seconds"}),
}


@dataclass(frozen=True)
class HotkeyConfig:
    dictation: str
    command: str


@dataclass(frozen=True)
class AiConfig:
    provider: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class AppConfig:
    path: Path
    hotkeys: HotkeyConfig
    auto_paste: bool
    cleanup_enabled: bool
    commands_enabled: bool
    ai: AiConfig


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8-sig") as config_file:
            parser.read_file(config_file)
    except configparser.Error as error:
        raise ValueError(f"Invalid configuration syntax in {path}: {error}") from error
    return parser


def _validate_shape(parser: configparser.ConfigParser, path: Path) -> None:
    if parser.defaults():
        keys = ", ".join(sorted(parser.defaults()))
        raise ValueError(f"Unknown keys in [DEFAULT] in {path}: {keys}")
    unknown_sections = set(parser.sections()) - set(SCHEMA)
    if unknown_sections:
        names = ", ".join(sorted(unknown_sections))
        raise ValueError(f"Unknown configuration section(s) in {path}: {names}")
    missing_sections = set(SCHEMA) - set(parser.sections())
    if missing_sections:
        names = ", ".join(sorted(missing_sections))
        raise ValueError(f"Missing configuration section(s) in {path}: {names}")
    for section, expected_keys in SCHEMA.items():
        actual_keys = set(parser[section])
        unknown_keys = actual_keys - expected_keys
        if unknown_keys:
            names = ", ".join(sorted(unknown_keys))
            raise ValueError(f"Unknown key(s) in [{section}] in {path}: {names}")
        missing_keys = expected_keys - actual_keys
        if missing_keys:
            names = ", ".join(sorted(missing_keys))
            raise ValueError(f"Missing key(s) in [{section}] in {path}: {names}")


def _boolean(parser, section: str, key: str, path: Path) -> bool:
    value = parser[section][key].strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(
            f"[{section}] {key} in {path} must be true or false."
        )
    return value == "true"


def validate_config(parser: configparser.ConfigParser, path: Path) -> AppConfig:
    _validate_shape(parser, path)
    try:
        dictation = parse_hotkey(parser["hotkeys"]["dictation"])[0]
    except ValueError as error:
        raise ValueError(f"Invalid [hotkeys] dictation in {path}: {error}") from error
    try:
        command = parse_hotkey(parser["hotkeys"]["command"])[0]
    except ValueError as error:
        raise ValueError(f"Invalid [hotkeys] command in {path}: {error}") from error
    if dictation == command:
        raise ValueError(
            f"[hotkeys] dictation and command in {path} must use different bindings."
        )

    provider = parser["ai"]["provider"].strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        allowed = ", ".join(sorted(ALLOWED_PROVIDERS))
        raise ValueError(f"Unknown [ai] provider {provider!r} in {path}; use: {allowed}.")
    model = parser["ai"]["model"].strip()
    if not model:
        raise ValueError(f"[ai] model in {path} cannot be empty.")
    try:
        timeout_seconds = parser.getint("ai", "timeout_seconds")
    except ValueError as error:
        raise ValueError(
            f"[ai] timeout_seconds in {path} must be an integer from 1 to 120."
        ) from error
    if not 1 <= timeout_seconds <= 120:
        raise ValueError(
            f"[ai] timeout_seconds in {path} must be from 1 to 120."
        )

    return AppConfig(
        path=path,
        hotkeys=HotkeyConfig(dictation, command),
        auto_paste=_boolean(parser, "output", "auto_paste", path),
        cleanup_enabled=_boolean(parser, "cleanup", "enabled", path),
        commands_enabled=_boolean(parser, "commands", "enabled", path),
        ai=AiConfig(provider, model, timeout_seconds),
    )


def _legacy_values(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    with path.open(encoding="utf-8-sig") as config_file:
        for line in config_file:
            key, separator, value = line.strip().partition("=")
            key = key.strip().upper()
            if separator and key in {"HOTKEY", "AUTO_PASTE"}:
                values[key] = value.strip()
    return values


def _write_atomic(parser: configparser.ConfigParser, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            parser.write(file)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def load_config(
    live_path: Path,
    default_path: Path,
    legacy_path: Path | None = None,
) -> AppConfig:
    live_path = Path(live_path)
    if live_path.exists():
        return validate_config(_read_ini(live_path), live_path)
    default_path = Path(default_path)
    if not default_path.is_file():
        raise FileNotFoundError(f"Default configuration is missing: {default_path}")

    parser = _read_ini(default_path)
    legacy = _legacy_values(Path(legacy_path)) if legacy_path else {}
    if "HOTKEY" in legacy:
        parser["hotkeys"]["dictation"] = legacy["HOTKEY"]
    if "AUTO_PASTE" in legacy:
        parser["output"]["auto_paste"] = legacy["AUTO_PASTE"]
    # Legacy CLEANUP meant local processing; never translate it into cloud consent.
    parser["cleanup"]["enabled"] = "false"
    validate_config(parser, live_path)
    _write_atomic(parser, live_path)
    return validate_config(_read_ini(live_path), live_path)

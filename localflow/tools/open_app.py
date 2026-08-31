import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from localflow.cloud import ToolDefinition

MAX_APP_NAME_LENGTH = 80
OPEN_APP_DEFINITION = ToolDefinition(
    name="open_app",
    description="Open one installed Windows application by its ordinary name.",
    parameters={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Application name, for example Chrome or Notepad.",
                "minLength": 1,
                "maxLength": MAX_APP_NAME_LENGTH,
            }
        },
        "required": ["app_name"],
        "additionalProperties": False,
    },
)


class OpenAppError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAppRequest:
    app_name: str


@dataclass(frozen=True)
class AppEntry:
    display_name: str
    target: Path
    aliases: frozenset[str]


def normalize_name(name: str) -> str:
    return " ".join(
        "".join(character if character.isalnum() else " " for character in name)
        .casefold()
        .split()
    )


def validate_open_app(arguments) -> OpenAppRequest:
    if not isinstance(arguments, dict) or set(arguments) != {"app_name"}:
        raise OpenAppError("open_app requires only one app_name field.")
    name = arguments["app_name"]
    if not isinstance(name, str):
        raise OpenAppError("open_app app_name must be text.")
    name = name.strip()
    if not name or len(name) > MAX_APP_NAME_LENGTH:
        raise OpenAppError(
            f"open_app app_name must contain 1 to {MAX_APP_NAME_LENGTH} characters."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise OpenAppError("open_app app_name contains a control character.")
    if any(character in name for character in "/\\:;&|<>^`\"'") or re.search(
        r"\$\(|%[A-Za-z_][A-Za-z0-9_]*%|--|\.(?:exe|lnk)\s*$|\bwww\.",
        name,
        re.IGNORECASE,
    ):
        raise OpenAppError(
            "open_app app_name must be an application name, not a command or path."
        )
    if not normalize_name(name):
        raise OpenAppError("open_app app_name is invalid.")
    return OpenAppRequest(name)


class AppCatalogue:
    def __init__(self, entries):
        self.entries = tuple(entries)

    @classmethod
    def discover(cls, start_menu_roots=None, registry_entries=None):
        if start_menu_roots is None:
            start_menu_roots = _start_menu_roots()
        entries = list(_shortcut_entries(start_menu_roots))
        entries.extend(
            _app_path_entries() if registry_entries is None else registry_entries
        )
        unique = {}
        for entry in entries:
            key = os.path.normcase(str(entry.target))
            if key in unique:
                previous = unique[key]
                unique[key] = AppEntry(
                    previous.display_name,
                    previous.target,
                    previous.aliases | entry.aliases,
                )
            else:
                unique[key] = entry
        return cls(unique.values())

    def resolve(self, requested_name: str) -> AppEntry:
        requested = normalize_name(requested_name)
        exact = [entry for entry in self.entries if requested in entry.aliases]
        if exact:
            return _one_match(requested_name, exact)
        partial = [
            entry
            for entry in self.entries
            if any(requested in alias for alias in entry.aliases)
        ]
        if not partial:
            raise OpenAppError(f"Application {requested_name!r} was not found.")
        return _one_match(requested_name, partial)


class OpenApp:
    def __init__(
        self,
        catalogue: AppCatalogue,
        shutdown_event: threading.Event,
        start=os.startfile,
    ):
        self.catalogue = catalogue
        self.shutdown_event = shutdown_event
        self.start = start

    def __call__(self, request: OpenAppRequest) -> str:
        if self.shutdown_event.is_set():
            raise OpenAppError("LocalFlow is shutting down; nothing was opened.")
        entry = self.catalogue.resolve(request.app_name)
        if self.shutdown_event.is_set():
            raise OpenAppError("LocalFlow is shutting down; nothing was opened.")
        try:
            self.start(str(entry.target))
        except OSError:
            raise OpenAppError(
                f"Windows could not open {entry.display_name!r}."
            ) from None
        return entry.display_name


def _one_match(requested_name: str, entries) -> AppEntry:
    if len(entries) != 1:
        names = ", ".join(sorted({entry.display_name for entry in entries})[:5])
        raise OpenAppError(
            f"Application name {requested_name!r} is ambiguous; matches: {names}."
        )
    return entries[0]


def _start_menu_roots():
    roots = []
    for variable in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(variable)
        if base:
            roots.append(
                Path(base)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            )
    return roots


def _shortcut_entries(roots):
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        trusted_root = root.resolve()
        for shortcut in root.rglob("*.lnk"):
            try:
                target = shortcut.resolve(strict=True)
                if not target.is_file() or not target.is_relative_to(trusted_root):
                    continue
            except OSError:
                continue
            display = shortcut.stem.strip()
            alias = normalize_name(display)
            if alias:
                yield AppEntry(display, target, frozenset({alias}))


def _app_path_entries():
    try:
        import winreg
    except ImportError:
        return []

    entries = []
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                root = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            raw_target = winreg.QueryValue(subkey, None)
                    except OSError:
                        continue
                    entry = _app_path_entry(subkey_name, raw_target)
                    if entry is not None:
                        entries.append(entry)
    return entries


def _app_path_entry(executable_name: str, raw_target) -> AppEntry | None:
    if not isinstance(raw_target, str):
        return None
    raw_target = os.path.expandvars(raw_target.strip())
    if len(raw_target) >= 2 and raw_target[0] == raw_target[-1] == '"':
        raw_target = raw_target[1:-1]
    target = Path(raw_target)
    if (
        not target.is_absolute()
        or target.suffix.casefold() != ".exe"
        or not target.is_file()
    ):
        return None
    display = Path(executable_name).stem.strip()
    aliases = {normalize_name(display), normalize_name(target.stem)}
    aliases.discard("")
    return AppEntry(display, target.resolve(), frozenset(aliases))

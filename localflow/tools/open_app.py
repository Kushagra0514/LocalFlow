import os
import re
import threading
import unicodedata
import uuid
from collections import Counter
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
    executable_aliases: frozenset[str] = frozenset()
    launch_identity: tuple[str, ...] | None = None


def normalize_name(name: str) -> str:
    return " ".join(
        "".join(
            character if character.isalnum() else " "
            for character in unicodedata.normalize("NFKC", name)
        )
        .casefold()
        .split()
    )


def validate_open_app(arguments) -> OpenAppRequest:
    if not isinstance(arguments, dict) or set(arguments) != {"app_name"}:
        raise OpenAppError("open_app requires only one app_name field.")
    name = validate_app_name(arguments["app_name"], "open_app app_name")
    return OpenAppRequest(name)


class AppCatalogue:
    def __init__(self, entries, app_aliases=()):
        self.entries = tuple(entries)
        self.user_aliases, self.alias_errors = self._prepare_aliases(app_aliases)

    @classmethod
    def discover(cls, start_menu_roots=None, registry_entries=None, app_aliases=()):
        if start_menu_roots is None:
            start_menu_roots = _start_menu_roots()
        shortcuts = list(_shortcut_entries(start_menu_roots))
        alias_counts = Counter(alias for entry in shortcuts for alias in entry.aliases)
        entries = [
            AppEntry(
                entry.display_name,
                entry.target,
                entry.aliases,
                launch_identity=_shortcut_launch_identity(
                    entry.target, next(iter(entry.aliases))
                ),
            )
            if any(alias_counts[alias] > 1 for alias in entry.aliases)
            else entry
            for entry in shortcuts
        ]
        entries.extend(
            _app_path_entries() if registry_entries is None else registry_entries
        )
        unique = {}
        for entry in entries:
            key = entry.launch_identity or ("path", os.path.normcase(str(entry.target)))
            if key in unique:
                previous = unique[key]
                unique[key] = AppEntry(
                    previous.display_name,
                    previous.target,
                    previous.aliases | entry.aliases,
                    previous.executable_aliases | entry.executable_aliases,
                    previous.launch_identity,
                )
            else:
                unique[key] = entry
        return cls(unique.values(), app_aliases)

    def _prepare_aliases(self, app_aliases):
        aliases = {}
        errors = []
        normalized_pairs = []
        for alias, target in app_aliases:
            try:
                alias = validate_app_name(alias, "alias")
                target = validate_app_name(target, "alias target")
            except OpenAppError as error:
                errors.append(str(error))
                continue
            normalized_pairs.append(
                (alias, target, normalize_name(alias), normalize_name(target))
            )
        alias_names = [item[2] for item in normalized_pairs]
        duplicate_names = {
            name for name, count in Counter(alias_names).items() if name and count > 1
        }
        for alias, target, normalized_alias, normalized_target in normalized_pairs:
            try:
                if normalized_alias in duplicate_names:
                    raise OpenAppError(f"duplicate alias {alias!r}")
                if (
                    normalized_alias == normalized_target
                    or normalized_target in alias_names
                ):
                    raise OpenAppError(f"recursive alias {alias!r}")
                aliases[normalized_alias] = self._resolve_exact(target)
            except OpenAppError as error:
                errors.append(str(error))
        return aliases, tuple(errors)

    def resolve(self, requested_name: str) -> AppEntry:
        requested_name = validate_app_name(requested_name, "Application name")
        requested = normalize_name(requested_name)
        if requested in self.user_aliases:
            return self.user_aliases[requested]
        return self._resolve_catalogue(requested_name, requested, allow_partial=True)

    def _resolve_exact(self, requested_name: str) -> AppEntry:
        return self._resolve_catalogue(
            requested_name, normalize_name(requested_name), allow_partial=False
        )

    def _resolve_catalogue(
        self, requested_name: str, requested: str, allow_partial: bool
    ) -> AppEntry:
        exact = [entry for entry in self.entries if requested in entry.aliases]
        if exact:
            return _one_match(requested_name, exact)
        executable = [
            entry for entry in self.entries if requested in entry.executable_aliases
        ]
        if executable:
            return _one_match(requested_name, executable)
        if not allow_partial:
            raise OpenAppError(f"Application {requested_name!r} was not found.")
        partial = [
            entry
            for entry in self.entries
            if any(
                requested in alias
                for alias in entry.aliases | entry.executable_aliases
            )
        ]
        if not partial:
            raise OpenAppError(f"Application {requested_name!r} was not found.")
        return _one_match(requested_name, partial)


def validate_app_name(name, label: str) -> str:
    if not isinstance(name, str):
        raise OpenAppError(f"{label} must be text")
    name = name.strip()
    if not name or len(name) > MAX_APP_NAME_LENGTH:
        raise OpenAppError(
            f"{label} must contain 1 to {MAX_APP_NAME_LENGTH} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise OpenAppError(f"{label} contains a control character")
    if any(character in name for character in "/\\:;&|<>^`\"'") or re.search(
        r"\$\(|%[A-Za-z_][A-Za-z0-9_]*%|--|\.(?:exe|lnk)\s*$|\bwww\.",
        name,
        re.IGNORECASE,
    ):
        raise OpenAppError(f"{label} must be an application name")
    if not normalize_name(name):
        raise OpenAppError(f"{label} is invalid")
    return name


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
        display_names = sorted({entry.display_name for entry in entries})
        if len(display_names) == 1:
            raise OpenAppError(
                f"Application name {requested_name!r} has {len(entries)} distinct "
                f"installed entries named {display_names[0]!r}."
            )
        names = ", ".join(display_names[:5])
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
                yield AppEntry(
                    display,
                    target,
                    frozenset({alias}),
                )


def _shortcut_launch_identity(shortcut: Path, normalized_name: str):
    properties = _read_windows_shortcut(shortcut)
    if properties is None:
        return None
    target, arguments, working_directory = properties
    if target:
        return (
            "target",
            os.path.normcase(os.path.normpath(target)),
            arguments.casefold(),
        )
    if working_directory:
        # ponytail: Working directory plus name is a conservative fallback for
        # AppUserModel shortcuts; use the property store if a collision appears.
        return (
            "app-shortcut",
            normalized_name,
            os.path.normcase(os.path.normpath(working_directory)),
            arguments.casefold(),
        )
    return None


def _read_windows_shortcut(shortcut: Path):
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = (
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        )

        @classmethod
        def parse(cls, value):
            raw = uuid.UUID(value).bytes_le
            return cls.from_buffer_copy(raw)

    def method(pointer, index, result, *arguments):
        address = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents[index]
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(address)

    ole32 = ctypes.OleDLL("ole32")
    initialized = ole32.CoInitializeEx(None, 2) in (0, 1)
    shell_link = ctypes.c_void_p()
    persist_file = ctypes.c_void_p()
    try:
        class_id = GUID.parse("00021401-0000-0000-C000-000000000046")
        shell_link_id = GUID.parse("000214F9-0000-0000-C000-000000000046")
        persist_file_id = GUID.parse("0000010B-0000-0000-C000-000000000046")
        if ole32.CoCreateInstance(
            ctypes.byref(class_id),
            None,
            1,
            ctypes.byref(shell_link_id),
            ctypes.byref(shell_link),
        ) < 0:
            return None
        query_interface = method(
            shell_link,
            0,
            ctypes.c_long,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        )
        if query_interface(
            shell_link, ctypes.byref(persist_file_id), ctypes.byref(persist_file)
        ) < 0:
            return None
        load = method(persist_file, 5, ctypes.c_long, wintypes.LPCWSTR, wintypes.DWORD)
        if load(persist_file, str(shortcut), 0) < 0:
            return None

        size = 32768
        target = ctypes.create_unicode_buffer(size)
        arguments = ctypes.create_unicode_buffer(size)
        working_directory = ctypes.create_unicode_buffer(size)
        get_path = method(
            shell_link,
            3,
            ctypes.c_long,
            wintypes.LPWSTR,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        get_arguments = method(
            shell_link, 10, ctypes.c_long, wintypes.LPWSTR, ctypes.c_int
        )
        get_working_directory = method(
            shell_link, 8, ctypes.c_long, wintypes.LPWSTR, ctypes.c_int
        )
        get_path(shell_link, target, size, None, 0)
        get_arguments(shell_link, arguments, size)
        get_working_directory(shell_link, working_directory, size)
        return target.value, arguments.value.strip(), working_directory.value
    except (OSError, ValueError):
        return None
    finally:
        if persist_file:
            method(persist_file, 2, wintypes.ULONG)(persist_file)
        if shell_link:
            method(shell_link, 2, wintypes.ULONG)(shell_link)
        if initialized:
            ole32.CoUninitialize()


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
    executable_aliases = {normalize_name(display), normalize_name(target.stem)}
    executable_aliases.discard("")
    return AppEntry(
        display,
        target.resolve(),
        frozenset(),
        frozenset(executable_aliases),
        ("target", os.path.normcase(os.path.normpath(str(target.resolve()))), ""),
    )

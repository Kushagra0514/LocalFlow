# Phase 4 hotkey and output results

Date: 2026-08-28

## Outcome

LocalFlow now accepts a single push-to-talk key or a modifier-first key
combination from `config.txt`. The default remains `f23` for the Windows
Copilot key. Automatic paste is now opt-in and disabled by default.

## Configuration

Single-key examples:

```text
HOTKEY=f23
HOTKEY=f12
HOTKEY=right shift
```

Combination example:

```text
HOTKEY=ctrl+shift+space
```

A combination must contain zero or more modifiers followed by exactly one
non-modifier trigger key. Key names are normalized and resolved through the
existing `keyboard` package at startup. Unknown keys, empty values, duplicate
keys, and combinations in the wrong order produce a clear startup error.

Output behavior is controlled separately:

```text
AUTO_PASTE=false
```

A successful result is always copied to the clipboard. When `AUTO_PASTE=true`,
LocalFlow waits until processing is finished and then sends `Ctrl+V` to
whichever application is focused at that moment. The default `false` setting
never sends a paste shortcut.

## Hold behavior

One global keyboard hook tracks physical scan codes:

1. Modifiers alone do not start recording.
2. The first press of the configured trigger starts recording if every
   required modifier is held.
3. Repeated key-down events while the trigger is held are ignored.
4. Releasing the trigger stops recording.
5. Releasing a required modifier early also stops recording.
6. Re-pressing a modifier while the original trigger remains held cannot start
   another recording from a repeated key event.

Generic modifiers such as `ctrl` accept either side. Side-specific names such
as `right shift` remain available.

## Verification

Eighteen tests pass. The Phase 4 checks cover:

- `f23` single-key start, repeat suppression, and release;
- `ctrl+shift+space` modifier ordering and trigger behavior;
- early modifier release without an accidental restart;
- invalid-combination rejection and startup error reporting;
- clipboard copy with automatic paste disabled; and
- clipboard copy plus `Ctrl+V` when automatic paste is explicitly enabled.

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

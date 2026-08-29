"""Copy license material for Python components included in the package."""

import importlib.metadata
import shutil
import sys
from pathlib import Path


PACKAGE_DISTRIBUTIONS = (
    "altgraph",
    "certifi",
    "cffi",
    "keyboard",
    "numpy",
    "packaging",
    "pefile",
    "pycparser",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pyperclip",
    "pywin32-ctypes",
    "sounddevice",
)


def copy_distribution_licenses(distribution_name, output_dir):
    distribution = importlib.metadata.distribution(distribution_name)
    destination = output_dir / f"{distribution.metadata['Name']}-{distribution.version}"
    copied = 0
    for relative_path in distribution.files or ():
        filename = Path(relative_path).name.lower()
        if not filename.startswith(("license", "copying", "notice")):
            continue
        source = Path(distribution.locate_file(relative_path))
        if source.is_file():
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / Path(relative_path).name
            if target.exists():
                target = destination / f"{copied}-{target.name}"
            shutil.copy2(source, target)
            copied += 1
    if not copied:
        raise RuntimeError(f"No license file found for {distribution_name}")


def main(argv):
    if len(argv) != 1:
        raise SystemExit("Usage: export_licenses.py OUTPUT_DIRECTORY")
    output_dir = Path(argv[0])
    output_dir.mkdir(parents=True, exist_ok=True)

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python license not found at {python_license}")
    shutil.copy2(python_license, output_dir / "PYTHON_LICENSE.txt")

    for distribution_name in PACKAGE_DISTRIBUTIONS:
        copy_distribution_licenses(distribution_name, output_dir)


if __name__ == "__main__":
    main(sys.argv[1:])

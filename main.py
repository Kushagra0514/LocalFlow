import os
import sys
from pathlib import Path

from localflow import APP_VERSION
from localflow.application import Application
from localflow.config import LIVE_CONFIG_FILENAME, load_config
from localflow.pipeline import Pipeline, raw_dictation
from localflow.types import JobPurpose
from localflow.whisper import WhisperTranscriber


def application_paths():
    app_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    runtime_dir = (
        app_dir / "runtime"
        if getattr(sys, "frozen", False)
        else app_dir / ".local" / "phase1"
    )
    data_dir = Path(
        os.environ.get("LOCALFLOW_DATA_DIR")
        or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        / "LocalFlow"
    )
    return app_dir, runtime_dir, data_dir


def build_application():
    app_dir, runtime_dir, data_dir = application_paths()
    config_path = data_dir / LIVE_CONFIG_FILENAME
    config = load_config(
        config_path,
        app_dir / "config.default.ini",
        app_dir / "config.txt",
    )
    transcriber = WhisperTranscriber(
        runtime_dir / "whisper" / "Release" / "whisper-cli.exe",
        data_dir / "models",
    )
    pipeline = Pipeline({JobPurpose.DICTATION: raw_dictation})
    return Application(
        transcriber,
        pipeline,
        hotkey=config.hotkeys.dictation,
        auto_paste=config.auto_paste,
    ), data_dir / "models", config


def main(argv=None):
    argv = list(argv or ())
    if argv == ["--version"]:
        print(f"LocalFlow {APP_VERSION}")
        return 0
    if argv == ["--config-path"]:
        print(application_paths()[2] / LIVE_CONFIG_FILENAME)
        return 0
    smoke_test = len(argv) == 2 and argv[0] == "--smoke-test"
    if not (
        not argv
        or argv in (["--setup-models"], ["--verify-installation"], ["--check-config"])
        or smoke_test
    ):
        print(
            "Usage: LocalFlow [--config-path | --check-config | --setup-models | "
            "--verify-installation | --smoke-test AUDIO.wav | --version]"
        )
        return 2

    try:
        application, model_dir, config = build_application()
        if argv == ["--check-config"]:
            print(f"Configuration is valid: {config.path}")
            return 0
        if not argv:
            print(f"Configuration: {config.path}")
        application.prepare()
        if argv == ["--verify-installation"]:
            application.verify_installation()
        elif smoke_test:
            application.run_smoke_test(argv[1])
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}")
        if getattr(sys, "frozen", False) and not argv:
            try:
                input("Press Enter to close LocalFlow.")
            except EOFError:
                pass
        return 1

    if smoke_test:
        print("LocalFlow release smoke test passed.")
        return 0
    if argv:
        action = "verified" if argv == ["--verify-installation"] else "installed"
        print(f"LocalFlow models are {action} in {model_dir}.")
        print("LocalFlow is ready to run.")
        return 0
    return application.run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

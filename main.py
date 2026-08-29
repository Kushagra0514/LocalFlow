import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import keyboard
import numpy as np
import pyperclip
import sounddevice as sd

APP_VERSION = "0.1.0"
APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
RUNTIME_DIR = (
    APP_DIR / "runtime"
    if getattr(sys, "frozen", False)
    else APP_DIR / ".local" / "phase1"
)
LOCAL_APP_DATA = Path(
    os.environ.get("LOCALFLOW_DATA_DIR")
    or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "LocalFlow"
)
MODEL_DIR = LOCAL_APP_DATA / "models"
SAMPLE_RATE = 16_000
CHANNELS = 1
MIN_AUDIO_RMS = 0.002
MIN_RECORDING_SECONDS = 0.3
MAX_RECORDING_SECONDS = 60
MIN_RECORDING_SAMPLES = int(SAMPLE_RATE * MIN_RECORDING_SECONDS)
MAX_RECORDING_SAMPLES = SAMPLE_RATE * MAX_RECORDING_SECONDS
WHISPER_THREADS = min(4, os.cpu_count() or 1)
WHISPER_CLI = RUNTIME_DIR / "whisper" / "Release" / "whisper-cli.exe"
WHISPER_MODEL = MODEL_DIR / "ggml-base.en-q5_1.bin"
LLAMA_SERVER = RUNTIME_DIR / "llama" / "llama-server.exe"
S1_MODEL = MODEL_DIR / "s1-mini-q4_k_m.gguf"
S1_THREADS = WHISPER_THREADS
S1_CONTEXT_SIZE = 2_048
S1_SYSTEM_PROMPT = (
    "You are a text normalizer for speech-to-text transcripts. The input begins "
    "with a control line specifying the styling, structure, and context settings; "
    "clean the transcript to match those settings and output only the cleaned text."
)
S1_CONTROL_LINE = (
    "[Styling: semi-formal] [Structure: prose] [Context: general]"
)


class ModelSpec(NamedTuple):
    name: str
    filename: str
    url: str
    size: int
    sha256: str


MODEL_SPECS = (
    ModelSpec(
        "Whisper base.en Q5",
        "ggml-base.en-q5_1.bin",
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
        "5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.en-q5_1.bin",
        59_721_011,
        "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f",
    ),
    ModelSpec(
        "S1-mini by Superwhisper Q4_K_M",
        "s1-mini-q4_k_m.gguf",
        "https://huggingface.co/superwhisper/s1-mini-GGUF/resolve/"
        "34add00a48a2e5d24e5a4ee5405a99620a3a240c/s1-mini-q4_k_m.gguf",
        484_219_808,
        "3b41ebe2502cbd03e811d5d16b022f5ab551eda58d62597d152f89535003c634",
    ),
)

HOTKEY = "f23"
AUTO_PASTE = False
hotkey_modifier_codes = ()
hotkey_trigger_codes = frozenset()
pressed_key_codes = set()
hotkey_is_down = False


class ApplicationState(Enum):
    READY = "ready"
    RECORDING = "recording"
    PROCESSING = "processing"
    SHUTTING_DOWN = "shutting_down"


app_state = ApplicationState.READY
state_lock = threading.Lock()
audio_buffer = []
recorded_samples = 0
stream = None
recording_timer = None
worker_thread = None
active_native_process = None


def load_config(config_path=None):
    settings = {"HOTKEY": "f23", "AUTO_PASTE": "false"}
    config_path = config_path or APP_DIR / "config.txt"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as config_file:
            for line in config_file:
                key, separator, value = line.strip().partition("=")
                key = key.strip().upper()
                if separator and key in settings:
                    settings[key] = value.strip()
    return settings


def parse_hotkey(hotkey):
    parts = tuple(part.strip() for part in hotkey.split("+"))
    if not parts or any(not part for part in parts):
        raise ValueError("HOTKEY must contain one or more key names.")
    parts = tuple(keyboard.normalize_name(part) for part in parts)
    if len(set(parts)) != len(parts):
        raise ValueError("HOTKEY cannot contain the same key more than once.")
    if len(parts) > 1 and (
        any(part not in keyboard.all_modifiers for part in parts[:-1])
        or parts[-1] in keyboard.all_modifiers
    ):
        raise ValueError(
            "HOTKEY combinations must list modifiers first and one "
            "non-modifier key last, for example ctrl+shift+space."
        )

    try:
        code_groups = tuple(
            frozenset(keyboard.key_to_scan_codes(part)) for part in parts
        )
    except ValueError as error:
        raise ValueError(f"Invalid HOTKEY {hotkey!r}: {error}") from error
    return "+".join(parts), code_groups[:-1], code_groups[-1]


def configure():
    global HOTKEY, AUTO_PASTE, hotkey_is_down, app_state
    global hotkey_modifier_codes, hotkey_trigger_codes

    settings = load_config()
    HOTKEY, hotkey_modifier_codes, hotkey_trigger_codes = parse_hotkey(
        settings["HOTKEY"]
    )
    auto_paste = settings["AUTO_PASTE"].lower()
    if auto_paste not in {"true", "false"}:
        raise ValueError("AUTO_PASTE must be either true or false.")
    AUTO_PASTE = auto_paste == "true"
    pressed_key_codes.clear()
    hotkey_is_down = False
    app_state = ApplicationState.READY


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(spec, model_dir=None):
    """Download one pinned model atomically and reject unexpected bytes."""
    model_dir = Path(model_dir or MODEL_DIR)
    destination = model_dir / spec.filename
    partial = destination.with_suffix(destination.suffix + ".part")
    model_dir.mkdir(parents=True, exist_ok=True)

    if destination.is_file():
        print(f"Verifying {spec.name}...")
        if destination.stat().st_size == spec.size and file_sha256(destination) == spec.sha256:
            print(f"Verified {spec.name}.")
            return destination
        print(f"Rejected corrupted or unrecognized model: {destination}")
        destination.unlink()

    if partial.exists():
        print(f"Found an interrupted {spec.name} download at {partial}.")
        print("Restarting it from the beginning; rerun LocalFlow if this is interrupted again.")
        partial.unlink()

    print(f"Downloading {spec.name} ({spec.size / 1024 / 1024:.1f} MiB)...")
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": f"LocalFlow/{APP_VERSION}"},
    )
    downloaded = 0
    next_progress = 0
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as file:
            while chunk := response.read(1024 * 1024):
                file.write(chunk)
                downloaded += len(chunk)
                percent = min(100, downloaded * 100 // spec.size)
                if percent >= next_progress:
                    print(
                        f"  {percent:3d}% ({downloaded / 1024 / 1024:.1f} / "
                        f"{spec.size / 1024 / 1024:.1f} MiB)"
                    )
                    next_progress = percent + 10
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(
            f"Download interrupted for {spec.name}: {error}\n"
            f"Partial data remains at {partial}. Rerun LocalFlow to restart the download."
        ) from error

    actual_size = partial.stat().st_size
    actual_sha256 = file_sha256(partial)
    if actual_size != spec.size or actual_sha256 != spec.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Rejected downloaded {spec.name}: expected {spec.size} bytes and SHA-256 "
            f"{spec.sha256}, got {actual_size} bytes and {actual_sha256}. "
            "Nothing was installed; rerun LocalFlow to try again."
        )

    partial.replace(destination)
    print(f"Installed and verified {spec.name} at {destination}.")
    return destination


def ensure_models():
    for spec in MODEL_SPECS:
        ensure_model(spec)


def validate_native_runtimes():
    missing = [path for path in (WHISPER_CLI, LLAMA_SERVER) if not path.is_file()]
    if missing:
        paths = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "LocalFlow's packaged native runtimes are incomplete. Missing:\n" + paths
        )


def validate_whisper_installation():
    missing = [path for path in (WHISPER_CLI, WHISPER_MODEL) if not path.is_file()]
    if missing:
        paths = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "Local whisper.cpp installation is incomplete. Missing:\n" + paths
        )


def validate_s1_installation():
    missing = [path for path in (LLAMA_SERVER, S1_MODEL) if not path.is_file()]
    if missing:
        paths = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "Local S1-mini by Superwhisper/llama.cpp installation is incomplete. "
            "Missing:\n" + paths
        )


def verify_native_runtimes():
    for name, executable in (
        ("whisper.cpp", WHISPER_CLI),
        ("llama.cpp", LLAMA_SERVER),
    ):
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Could not launch packaged {name}: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or result.returncode
            raise RuntimeError(f"Packaged {name} failed its version check: {detail}")


def start_native_process(command, **kwargs):
    global active_native_process

    process = subprocess.Popen(command, **kwargs)
    with state_lock:
        if app_state is ApplicationState.SHUTTING_DOWN:
            should_stop = True
        elif active_native_process is not None:
            should_stop = True
        else:
            active_native_process = process
            should_stop = False

    if should_stop:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise RuntimeError("Local inference cannot start while the application is busy or shutting down.")
    return process


def clear_native_process(process):
    global active_native_process

    with state_lock:
        if active_native_process is process:
            active_native_process = None


def write_whisper_wav(path, audio_data):
    samples = np.asarray(audio_data, dtype=np.float32).reshape(-1)
    pcm = (np.clip(samples, -1.0, 1.0) * 32_767).astype("<i2")
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())


def read_pcm16_wav(path):
    with wave.open(str(path), "rb") as wav_file:
        if (
            wav_file.getframerate(),
            wav_file.getnchannels(),
            wav_file.getsampwidth(),
        ) != (SAMPLE_RATE, CHANNELS, 2):
            raise ValueError("Smoke-test audio must be 16 kHz, mono, 16-bit PCM WAV.")
        frames = wav_file.readframes(wav_file.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32_768


def transcribe_audio(audio_data):
    validate_whisper_installation()
    samples = np.asarray(audio_data, dtype=np.float32).reshape(-1)
    # ponytail: simple energy gate; use whisper.cpp VAD if noisy rooms defeat it.
    if not samples.size or np.sqrt(np.mean(np.square(samples))) < MIN_AUDIO_RMS:
        return ""

    with tempfile.TemporaryDirectory(prefix="localflow-") as temp_dir:
        temp_dir = Path(temp_dir)
        audio_path = temp_dir / "recording.wav"
        output_base = temp_dir / "transcript"
        output_path = output_base.with_suffix(".txt")
        write_whisper_wav(audio_path, samples)

        command = [
            str(WHISPER_CLI),
            "-m",
            str(WHISPER_MODEL),
            "-f",
            str(audio_path),
            "-l",
            "en",
            "-t",
            str(WHISPER_THREADS),
            "-ng",
            "-nt",
            "-otxt",
            "-of",
            str(output_base),
        ]
        try:
            process = start_native_process(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as error:
            raise RuntimeError(f"Could not start whisper.cpp: {error}") from error

        try:
            try:
                _stdout, stderr = process.communicate(timeout=120)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.communicate()
                raise RuntimeError("whisper.cpp timed out after 120 seconds.") from error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            clear_native_process(process)

        if process.returncode != 0:
            detail = stderr.strip() or f"exit code {process.returncode}"
            raise RuntimeError(f"whisper.cpp failed: {detail}")
        if not output_path.is_file():
            raise RuntimeError("whisper.cpp completed without creating a transcript.")

        return output_path.read_text(encoding="utf-8").strip()


def audio_callback(indata, frames, callback_time, status):
    """Collect microphone chunks while the push-to-talk key is held."""
    global recorded_samples

    if status:
        print(f"Microphone status: {status}")
    with state_lock:
        if app_state is not ApplicationState.RECORDING:
            return
        remaining = MAX_RECORDING_SAMPLES - recorded_samples
        if remaining > 0:
            chunk = indata[:remaining].copy()
            audio_buffer.append(chunk)
            recorded_samples += len(chunk)


def cleanup_token_limit(raw_text):
    """Approximate S1's recommended 1.3 * input tokens + 32 output budget."""
    input_tokens = max(1, (len(raw_text) + 3) // 4)
    return min(1_024, (input_tokens * 13 + 9) // 10 + 32)


def clean_text_locally(raw_text):
    """Clean text with S1-mini by Superwhisper through a local llama.cpp server."""
    validate_s1_installation()
    max_tokens = cleanup_token_limit(raw_text)

    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]

    command = [
        str(LLAMA_SERVER),
        "-m",
        str(S1_MODEL),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--jinja",
        "--chat-template-kwargs",
        '{"enable_thinking":false}',
        "-t",
        str(S1_THREADS),
        "-c",
        str(S1_CONTEXT_SIZE),
        "--log-disable",
    ]

    print("Cleaning text locally with S1-mini by Superwhisper...")
    try:
        server = start_native_process(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as error:
        raise RuntimeError(f"Could not start llama.cpp: {error}") from error

    try:
        health_url = f"http://127.0.0.1:{port}/health"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                detail = server.stderr.read().strip()
                raise RuntimeError(
                    "llama.cpp stopped while loading S1-mini by Superwhisper: "
                    + (detail or f"exit code {server.returncode}")
                )
            try:
                with urllib.request.urlopen(health_url, timeout=0.5):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError(
                "llama.cpp did not load S1-mini by Superwhisper within 30 seconds."
            )

        payload = json.dumps(
            {
                "model": "s1-mini",
                "messages": [
                    {"role": "system", "content": S1_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"{S1_CONTROL_LINE}\n{raw_text}",
                    },
                ],
                "temperature": 0,
                "top_k": 1,
                "seed": 0,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Local S1-mini by Superwhisper request failed: {error}"
            ) from error

        try:
            return result["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise RuntimeError(
                "Local S1-mini by Superwhisper returned an invalid response."
            ) from error
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if server.stderr:
            server.stderr.close()
        clear_native_process(server)


def print_ready():
    print(f"\nReady! Hold [{HOTKEY.upper()}] to record. (Press Ctrl+C to exit)")


def finish_processing():
    global app_state, worker_thread

    with state_lock:
        if worker_thread is threading.current_thread():
            worker_thread = None
        if app_state is ApplicationState.PROCESSING:
            app_state = ApplicationState.READY
        ready = app_state is ApplicationState.READY
    if ready:
        print_ready()


def process_transcription(audio_data):
    """Transcribe in the single reserved worker and publish unless shutting down."""
    print("\nTranscribing locally with whisper.cpp...")
    try:
        full_text = transcribe_audio(audio_data)
        if not full_text:
            print("No speech detected.")
            return

        print(f"\n[Raw Transcript]: {full_text}")
        try:
            final_text = clean_text_locally(full_text)
        except Exception as error:
            print(f"Cleanup error: {error}")
            print("Using the raw transcript instead.")
            final_text = full_text

        print("-" * 20)
        print(final_text)
        print("-" * 20)

        try:
            with state_lock:
                if app_state is ApplicationState.SHUTTING_DOWN:
                    print("Result not copied because LocalFlow is shutting down.")
                    return
                pyperclip.copy(final_text)
        except Exception as error:
            print(f"Clipboard error: could not copy the result: {error}")
            return

        if AUTO_PASTE:
            time.sleep(0.1)
            try:
                with state_lock:
                    if app_state is ApplicationState.SHUTTING_DOWN:
                        print("Automatic paste skipped because LocalFlow is shutting down.")
                        return
                    keyboard.send("ctrl+v")
            except Exception as error:
                print(f"Automatic paste error: {error}. The result remains on the clipboard.")
    except Exception as error:
        print(f"Transcription error: {error}")
    finally:
        finish_processing()


def close_microphone(audio_stream):
    if audio_stream is None:
        return
    try:
        audio_stream.stop()
    except Exception as error:
        print(f"Microphone error while stopping the stream: {error}")
    try:
        audio_stream.close()
    except Exception as error:
        print(f"Microphone error while closing the stream: {error}")


def on_key_press(event=None):
    global app_state, recorded_samples, stream, recording_timer

    with state_lock:
        if app_state is ApplicationState.PROCESSING:
            busy = True
        elif app_state is ApplicationState.READY:
            busy = False
            app_state = ApplicationState.RECORDING
            audio_buffer.clear()
            recorded_samples = 0
        else:
            return
    if busy:
        print("Still processing; recording ignored.")
        return

    audio_stream = None
    try:
        audio_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=audio_callback,
        )
        audio_stream.start()
    except Exception as error:
        close_microphone(audio_stream)
        with state_lock:
            if app_state is ApplicationState.RECORDING:
                app_state = ApplicationState.READY
                ready = True
            else:
                ready = False
        print(f"Microphone error: could not start recording: {error}")
        if ready:
            print_ready()
        return

    timer = threading.Timer(MAX_RECORDING_SECONDS, on_recording_timeout)
    timer.daemon = True
    with state_lock:
        if app_state is ApplicationState.RECORDING:
            stream = audio_stream
            recording_timer = timer
            accepted = True
        else:
            accepted = False
    if not accepted:
        close_microphone(audio_stream)
        return

    try:
        timer.start()
    except RuntimeError as error:
        print(f"Recording error: could not start the duration limit: {error}")
        stop_recording()
        return
    print("\n[Recording started - speak now!]")


def on_recording_timeout():
    stop_recording(f"Maximum recording length of {MAX_RECORDING_SECONDS} seconds reached.")


def stop_recording(reason=None):
    global app_state, recorded_samples, stream, recording_timer, worker_thread

    with state_lock:
        if app_state is not ApplicationState.RECORDING:
            return
        app_state = ApplicationState.PROCESSING
        audio_stream = stream
        stream = None
        timer = recording_timer
        recording_timer = None
        chunks = list(audio_buffer)
        audio_buffer.clear()
        sample_count = recorded_samples
        recorded_samples = 0

    if timer is not None:
        timer.cancel()
    close_microphone(audio_stream)
    print("[Recording stopped]")
    if reason:
        print(reason)

    if sample_count < MIN_RECORDING_SAMPLES:
        print(
            f"Recording too short; hold the hotkey for at least "
            f"{MIN_RECORDING_SECONDS:.1f} seconds."
        )
        finish_processing()
        return

    try:
        audio_data = np.concatenate(chunks, axis=0).flatten()
    except Exception as error:
        print(f"Audio processing error: could not prepare the recording: {error}")
        finish_processing()
        return

    worker = threading.Thread(
        target=process_transcription,
        args=(audio_data,),
        daemon=True,
        name="LocalFlow-worker",
    )
    with state_lock:
        if app_state is ApplicationState.SHUTTING_DOWN:
            return
        worker_thread = worker
        try:
            worker.start()
        except RuntimeError as error:
            worker_thread = None
            app_state = ApplicationState.READY
            start_error = error
        else:
            start_error = None
    if start_error:
        print(f"Processing error: could not start the worker: {start_error}")
        print_ready()


def on_key_release(event=None):
    stop_recording()


def handle_hotkey_event(event):
    """Drive hold-to-record from one trigger key and optional modifiers."""
    global hotkey_is_down

    scan_code = event.scan_code
    if event.event_type == keyboard.KEY_DOWN:
        is_new_press = scan_code not in pressed_key_codes
        pressed_key_codes.add(scan_code)
        if (
            is_new_press
            and not hotkey_is_down
            and scan_code in hotkey_trigger_codes
            and all(codes & pressed_key_codes for codes in hotkey_modifier_codes)
        ):
            hotkey_is_down = True
            on_key_press()
    elif event.event_type == keyboard.KEY_UP:
        pressed_key_codes.discard(scan_code)
        if hotkey_is_down and (
            scan_code in hotkey_trigger_codes
            or not all(codes & pressed_key_codes for codes in hotkey_modifier_codes)
        ):
            hotkey_is_down = False
            on_key_release()


def shutdown_application():
    global app_state, hotkey_is_down, recorded_samples
    global stream, recording_timer

    with state_lock:
        if app_state is ApplicationState.SHUTTING_DOWN:
            return
        app_state = ApplicationState.SHUTTING_DOWN
        audio_stream = stream
        stream = None
        timer = recording_timer
        recording_timer = None
        process = active_native_process
        worker = worker_thread
        audio_buffer.clear()
        recorded_samples = 0
        pressed_key_codes.clear()
        hotkey_is_down = False

    try:
        keyboard.unhook_all()
    except Exception as error:
        print(f"Keyboard cleanup error: {error}")
    if timer is not None:
        timer.cancel()
    close_microphone(audio_stream)

    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    if worker is not None and worker.is_alive():
        worker.join(timeout=5)

    with state_lock:
        process = active_native_process
    if process is not None and process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    if worker is not None and worker.is_alive():
        worker.join(timeout=1)


def process_working_set(pid):
    """Return one Windows process's current working set, or zero after exit."""
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return 0
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return 0
        return counters.WorkingSetSize
    finally:
        kernel32.CloseHandle(handle)


def run_release_smoke_test(audio_path):
    """Run the real local pipeline while sampling the complete process tree."""
    audio_data = read_pcm16_wav(audio_path)
    stop_sampling = threading.Event()
    peak_bytes = [0]

    def sample_memory():
        while not stop_sampling.is_set():
            with state_lock:
                child = active_native_process
            pids = [os.getpid()]
            if child is not None:
                pids.append(child.pid)
            peak_bytes[0] = max(
                peak_bytes[0], sum(process_working_set(pid) for pid in pids)
            )
            stop_sampling.wait(0.025)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        raw_text = transcribe_audio(audio_data)
        whisper_seconds = time.perf_counter() - started
        if not raw_text:
            raise RuntimeError("Release smoke test produced an empty transcript.")
        cleanup_started = time.perf_counter()
        cleaned_text = clean_text_locally(raw_text)
        cleanup_seconds = time.perf_counter() - cleanup_started
    finally:
        stop_sampling.set()
        sampler.join()

    total_seconds = time.perf_counter() - started
    print(f"[Smoke Raw]: {raw_text}")
    print(f"[Smoke Clean]: {cleaned_text}")
    print(f"[Smoke Whisper Seconds]: {whisper_seconds:.3f}")
    print(f"[Smoke Cleanup Seconds]: {cleanup_seconds:.3f}")
    print(f"[Smoke Pipeline Seconds]: {total_seconds:.3f}")
    print(f"[Smoke Peak MiB]: {peak_bytes[0] / 1024 / 1024:.1f}")
    return raw_text, cleaned_text


def main(argv=None):
    argv = list(argv or ())
    if argv == ["--version"]:
        print(f"LocalFlow {APP_VERSION}")
        return 0
    smoke_test = len(argv) == 2 and argv[0] == "--smoke-test"
    if not (
        not argv
        or argv in (["--setup-models"], ["--verify-installation"])
        or smoke_test
    ):
        print(
            "Usage: LocalFlow [--setup-models | --verify-installation | "
            "--smoke-test AUDIO.wav | --version]"
        )
        return 2

    try:
        configure()
        validate_native_runtimes()
        ensure_models()
        validate_whisper_installation()
        validate_s1_installation()
        if argv == ["--verify-installation"]:
            verify_native_runtimes()
        elif smoke_test:
            run_release_smoke_test(argv[1])
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    if smoke_test:
        print("LocalFlow release smoke test passed.")
        return 0
    if argv:
        action = "verified" if argv == ["--verify-installation"] else "installed"
        print(f"LocalFlow models are {action} in {MODEL_DIR}.")
        print("LocalFlow is ready to run.")
        return 0

    print(
        f"Using local whisper.cpp base.en Q5 model with {WHISPER_THREADS} CPU threads."
    )
    print(
        f"Using local S1-mini by Superwhisper Q4_K_M cleanup with "
        f"{S1_THREADS} CPU threads."
    )
    print(f"Automatic paste is {'on' if AUTO_PASTE else 'off'}.")
    try:
        keyboard.hook(handle_hotkey_event, suppress=False)
    except Exception as error:
        print(f"ERROR: Could not register the hotkey: {error}")
        shutdown_application()
        return 1

    print(f"\nReady! Hold [{HOTKEY.upper()}] to record, release to transcribe.")
    print("Press Ctrl+C in this terminal to safely exit.")

    try:
        keyboard.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down safely... releasing keyboard hooks.")
        shutdown_application()
        print("Done. Goodbye!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

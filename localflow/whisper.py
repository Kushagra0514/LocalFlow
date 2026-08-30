import hashlib
import os
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

import certifi
import numpy as np

from localflow import APP_VERSION

SAMPLE_RATE = 16_000
CHANNELS = 1
MIN_AUDIO_RMS = 0.002
WHISPER_MODEL_FILENAME = "ggml-base.en-q5_1.bin"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    filename: str
    url: str
    size: int
    sha256: str


WHISPER_MODEL_SPEC = ModelSpec(
    "Whisper base.en Q5",
    WHISPER_MODEL_FILENAME,
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
    "5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.en-q5_1.bin",
    59_721_011,
    "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_ssl_context():
    """Trust current public roots plus certificates managed by Windows."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs()
    return context


def ensure_model(spec: ModelSpec, model_dir: Path) -> Path:
    """Download one pinned model atomically and reject unexpected bytes."""
    model_dir = Path(model_dir)
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
        with urllib.request.urlopen(
            request, timeout=30, context=download_ssl_context()
        ) as response, partial.open("wb") as file:
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


def write_whisper_wav(path: Path, audio_data) -> None:
    samples = np.asarray(audio_data, dtype=np.float32).reshape(-1)
    pcm = (np.clip(samples, -1.0, 1.0) * 32_767).astype("<i2")
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())


def read_pcm16_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav_file:
        if (
            wav_file.getframerate(),
            wav_file.getnchannels(),
            wav_file.getsampwidth(),
        ) != (SAMPLE_RATE, CHANNELS, 2):
            raise ValueError("Smoke-test audio must be 16 kHz, mono, 16-bit PCM WAV.")
        frames = wav_file.readframes(wav_file.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32_768


class WhisperTranscriber:
    def __init__(self, executable: Path, model_dir: Path, threads: int | None = None):
        self.executable = Path(executable)
        self.model_dir = Path(model_dir)
        self.model_path = self.model_dir / WHISPER_MODEL_FILENAME
        self.threads = threads or min(4, os.cpu_count() or 1)
        self._process = None
        self._lock = threading.Lock()
        self._cancelled = threading.Event()

    @property
    def active_process(self):
        with self._lock:
            return self._process

    def ensure_model(self) -> Path:
        return ensure_model(WHISPER_MODEL_SPEC, self.model_dir)

    def validate_runtime(self) -> None:
        if not self.executable.is_file():
            raise FileNotFoundError(
                "LocalFlow's packaged native runtimes are incomplete. Missing:\n"
                f"  - {self.executable}"
            )

    def validate_installation(self) -> None:
        missing = [
            path for path in (self.executable, self.model_path) if not path.is_file()
        ]
        if missing:
            paths = "\n".join(f"  - {path}" for path in missing)
            raise FileNotFoundError(
                "Local whisper.cpp installation is incomplete. Missing:\n" + paths
            )

    def verify_runtime(self) -> None:
        try:
            result = subprocess.run(
                [str(self.executable), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Could not launch packaged whisper.cpp: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or result.returncode
            raise RuntimeError(f"Packaged whisper.cpp failed its version check: {detail}")

    def _start_process(self, command):
        if self._cancelled.is_set():
            raise RuntimeError("Local inference cannot start while shutting down.")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        with self._lock:
            if self._cancelled.is_set() or self._process is not None:
                should_stop = True
            else:
                self._process = process
                should_stop = False
        if should_stop:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise RuntimeError("Local inference cannot start while busy or shutting down.")
        return process

    def transcribe(self, audio_data) -> str:
        samples = np.asarray(audio_data, dtype=np.float32).reshape(-1)
        # ponytail: simple energy gate; use whisper.cpp VAD if noisy rooms defeat it.
        if not samples.size or np.sqrt(np.mean(np.square(samples))) < MIN_AUDIO_RMS:
            return ""
        self.validate_installation()

        with tempfile.TemporaryDirectory(prefix="localflow-") as temp_dir:
            temp_dir = Path(temp_dir)
            audio_path = temp_dir / "recording.wav"
            output_base = temp_dir / "transcript"
            output_path = output_base.with_suffix(".txt")
            write_whisper_wav(audio_path, samples)
            command = [
                str(self.executable), "-m", str(self.model_path),
                "-f", str(audio_path), "-l", "en", "-t", str(self.threads),
                "-ng", "-nt", "-otxt", "-of", str(output_base),
            ]
            try:
                process = self._start_process(command)
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
                with self._lock:
                    if self._process is process:
                        self._process = None

            if process.returncode != 0:
                detail = stderr.strip() or f"exit code {process.returncode}"
                raise RuntimeError(f"whisper.cpp failed: {detail}")
            if not output_path.is_file():
                raise RuntimeError("whisper.cpp completed without creating a transcript.")
            return output_path.read_text(encoding="utf-8").strip()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def kill(self) -> None:
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass


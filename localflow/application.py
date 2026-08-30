import os
import threading
import time

from localflow.output import OutputPublisher
from localflow.recording import Recorder
from localflow.types import ApplicationState, JobPurpose, Recording
from localflow.whisper import read_pcm16_wav


class Application:
    def __init__(
        self,
        transcriber,
        pipeline,
        hotkey: str,
        auto_paste: bool,
        publisher=None,
        thread_factory=threading.Thread,
    ):
        self.transcriber = transcriber
        self.pipeline = pipeline
        self.thread_factory = thread_factory
        self.state = ApplicationState.READY
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.worker = None
        self.publisher = publisher or OutputPublisher(
            auto_paste, self.shutdown_event, self.lock
        )
        self.recorder = Recorder(
            hotkey,
            self._claim_recording,
            self._accept_recording,
            self._discard_recording,
        )

    @property
    def active_native_process(self):
        return self.transcriber.active_process

    def _claim_recording(self, purpose: JobPurpose) -> bool:
        with self.lock:
            if self.state is ApplicationState.PROCESSING:
                busy = True
            elif self.state is ApplicationState.READY:
                busy = False
                self.state = ApplicationState.RECORDING
            else:
                return False
        if busy:
            print("Still processing; recording ignored.")
            return False
        return True

    def _discard_recording(self):
        with self.lock:
            if self.state is ApplicationState.RECORDING:
                self.state = ApplicationState.READY
                ready = True
            else:
                ready = False
        if ready:
            self.print_ready()

    def _accept_recording(self, recording: Recording):
        with self.lock:
            if self.state is not ApplicationState.RECORDING:
                return
            self.state = ApplicationState.PROCESSING
            worker = self.thread_factory(
                target=self._process_recording,
                args=(recording,),
                daemon=True,
                name="LocalFlow-worker",
            )
            self.worker = worker
            try:
                worker.start()
            except RuntimeError as error:
                self.worker = None
                self.state = ApplicationState.READY
                start_error = error
            else:
                start_error = None
        if start_error:
            print(f"Processing error: could not start the worker: {start_error}")
            self.print_ready()

    def _process_recording(self, recording: Recording):
        print("\nTranscribing locally with whisper.cpp...")
        try:
            raw_text = self.transcriber.transcribe(recording.samples)
            if not raw_text:
                print("No speech detected.")
                return
            result = self.pipeline.handle(recording.purpose, raw_text)
            print("-" * 20)
            print(result.text)
            print("-" * 20)
            self.publisher.publish(result.text)
        except Exception as error:
            print(f"Transcription error: {error}")
        finally:
            self._finish_processing()

    def _finish_processing(self):
        with self.lock:
            if self.worker is threading.current_thread():
                self.worker = None
            if self.state is ApplicationState.PROCESSING:
                self.state = ApplicationState.READY
            ready = self.state is ApplicationState.READY
        if ready:
            self.print_ready()

    def print_ready(self):
        print(
            f"\nReady! Hold [{self.recorder.hotkey.upper()}] to record. "
            "(Press Ctrl+C to exit)"
        )

    def prepare(self):
        self.transcriber.validate_runtime()
        self.transcriber.ensure_model()
        self.transcriber.validate_installation()

    def verify_installation(self):
        self.transcriber.verify_runtime()

    def run(self) -> int:
        print(
            f"Using local whisper.cpp base.en Q5 model with "
            f"{self.transcriber.threads} CPU threads."
        )
        print("Raw Whisper transcripts will be used.")
        print(
            f"Automatic paste is "
            f"{'on' if self.publisher.auto_paste else 'off'}."
        )
        try:
            self.recorder.hook()
        except Exception as error:
            print(f"ERROR: Could not register the hotkey: {error}")
            self.shutdown()
            return 1

        print(
            f"\nReady! Hold [{self.recorder.hotkey.upper()}] to record, "
            "release to transcribe."
        )
        print("Press Ctrl+C in this terminal to safely exit.")
        try:
            self.recorder.wait()
        except KeyboardInterrupt:
            pass
        finally:
            print("\nShutting down safely... releasing keyboard hooks.")
            self.shutdown()
            print("Done. Goodbye!")
        return 0

    def shutdown(self):
        with self.lock:
            if self.state is ApplicationState.SHUTTING_DOWN:
                return
            self.state = ApplicationState.SHUTTING_DOWN
            self.shutdown_event.set()
            worker = self.worker
        self.recorder.shutdown()
        self.transcriber.cancel()
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        self.transcriber.kill()
        if worker is not None and worker.is_alive():
            worker.join(timeout=1)

    def run_smoke_test(self, audio_path):
        audio_data = read_pcm16_wav(audio_path)
        stop_sampling = threading.Event()
        peak_bytes = [0]

        def sample_memory():
            while not stop_sampling.is_set():
                child = self.active_native_process
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
            transcript = self.transcriber.transcribe(audio_data)
            whisper_seconds = time.perf_counter() - started
            if not transcript:
                raise RuntimeError("Release smoke test produced an empty transcript.")
        finally:
            stop_sampling.set()
            sampler.join()
        total_seconds = time.perf_counter() - started
        print(f"[Smoke Transcript]: {transcript}")
        print(f"[Smoke Whisper Seconds]: {whisper_seconds:.3f}")
        print(f"[Smoke Pipeline Seconds]: {total_seconds:.3f}")
        print(f"[Smoke Peak MiB]: {peak_bytes[0] / 1024 / 1024:.1f}")
        return transcript


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

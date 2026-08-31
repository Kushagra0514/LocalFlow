from dataclasses import dataclass
from enum import Enum

import numpy as np


class ApplicationState(Enum):
    READY = "ready"
    RECORDING = "recording"
    PROCESSING = "processing"
    SHUTTING_DOWN = "shutting_down"


class JobPurpose(Enum):
    DICTATION = "dictation"
    COMMAND = "command"


@dataclass(frozen=True)
class Recording:
    purpose: JobPurpose
    samples: np.ndarray


@dataclass(frozen=True)
class TranscriptResult:
    purpose: JobPurpose
    raw_text: str
    text: str
    copy_to_clipboard: bool = True
    allow_auto_paste: bool = True


@dataclass(frozen=True)
class HandlerResult:
    text: str
    copy_to_clipboard: bool = True
    allow_auto_paste: bool = True

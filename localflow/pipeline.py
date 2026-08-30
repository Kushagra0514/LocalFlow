from collections.abc import Callable, Mapping

from localflow.types import JobPurpose, TranscriptResult


def raw_dictation(text: str) -> str:
    return text


class Pipeline:
    def __init__(self, handlers: Mapping[JobPurpose, Callable[[str], str]]):
        self.handlers = dict(handlers)

    def handle(self, purpose: JobPurpose, raw_text: str) -> TranscriptResult:
        try:
            handler = self.handlers[purpose]
        except KeyError as error:
            raise ValueError(f"No transcript handler registered for {purpose.value}.") from error
        return TranscriptResult(purpose, raw_text, handler(raw_text))


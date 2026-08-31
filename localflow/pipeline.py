from collections.abc import Callable, Mapping

from localflow.types import HandlerResult, JobPurpose, TranscriptResult


def raw_dictation(text: str) -> str:
    return text


class Pipeline:
    def __init__(
        self,
        handlers: Mapping[JobPurpose, Callable[[str], str | HandlerResult]],
    ):
        self.handlers = dict(handlers)

    def handle(self, purpose: JobPurpose, raw_text: str) -> TranscriptResult:
        try:
            handler = self.handlers[purpose]
        except KeyError as error:
            raise ValueError(f"No transcript handler registered for {purpose.value}.") from error
        handled = handler(raw_text)
        if isinstance(handled, str):
            handled = HandlerResult(handled)
        if not isinstance(handled, HandlerResult):
            raise TypeError("Transcript handlers must return text or HandlerResult.")
        return TranscriptResult(
            purpose,
            raw_text,
            handled.text,
            handled.copy_to_clipboard,
            handled.allow_auto_paste,
        )

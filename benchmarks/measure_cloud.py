"""Manually measure a real, billable Groq cleanup round trip."""

import argparse
import time

from localflow.cloud import CompletionRequest, Message, create_client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-billable", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if not args.confirm_billable:
        raise SystemExit("Refusing to call Groq without --confirm-billable.")
    if not 1 <= args.runs <= 10:
        raise SystemExit("--runs must be from 1 to 10.")

    client = create_client("groq")
    request = CompletionRequest(
        (
            Message("system", "Return only the corrected English transcript."),
            Message("user", "um hello there"),
        ),
        temperature=0,
        max_tokens=32,
    )
    for run in range(1, args.runs + 1):
        started = time.perf_counter()
        response = client.complete(request)
        elapsed = time.perf_counter() - started
        if response.tool_call is not None or not response.text:
            raise SystemExit("Groq returned no usable cleanup text.")
        print(f"Run {run}: {elapsed:.3f} seconds")


if __name__ == "__main__":
    main()

"""Shared stream collection, trimming, and transport error translation."""

from collections.abc import Iterator

from tux.helpers import collect_stream, iter_stream

from .transport import Transport


class ModelClientError(Exception):
    """Raised when the model endpoint cannot be reached or its reply is unusable."""


def stream_text(
    endpoint: str,
    payload: dict,
    timeout: float,
    transport: Transport,
) -> str:
    """Stream a chat request and return its accumulated text content."""
    url = f"{endpoint}/v1/chat/completions"
    try:
        return collect_stream(transport(url, payload, timeout))
    except OSError as exc:
        raise ModelClientError(
            f"could not reach the model endpoint at {endpoint} ({exc})"
        ) from exc


def stream_prose(
    endpoint: str,
    payload: dict,
    timeout: float,
    transport: Transport,
) -> Iterator[str]:
    """Yield a grammar-free reply with buffered-path whitespace semantics."""
    url = f"{endpoint}/v1/chat/completions"
    started = False
    pending = ""
    try:
        for content in iter_stream(transport(url, payload, timeout)):
            if not started:
                content = content.lstrip()
                if not content:
                    continue
                started = True
            combined = pending + content
            visible = combined.rstrip()
            pending = combined[len(visible):]
            if visible:
                yield visible
    except OSError as exc:
        raise ModelClientError(
            f"could not reach the model endpoint at {endpoint} ({exc})"
        ) from exc
    if not started:
        raise ModelClientError("the model returned an empty response")

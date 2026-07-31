"""HTTP transport seam for OpenAI-compatible streaming requests."""

import json
import urllib.request
from collections.abc import Callable, Iterable, Iterator

Transport = Callable[[str, dict, float], Iterable[str]]


def http_stream(url: str, payload: dict, timeout: float) -> Iterator[str]:
    """Yield decoded lines from a streaming POST to ``url``."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            yield raw.decode("utf-8")

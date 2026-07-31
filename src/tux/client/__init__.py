"""HTTP client for an OpenAI-compatible model endpoint."""

from .config import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM,
    DEFAULT_TIMEOUT,
    DEFAULT_VARIANT,
    DEFAULTS,
)
from .model import ModelClient
from .streaming import ModelClientError
from .transport import Transport, http_stream

__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_MODEL",
    "DEFAULT_SYSTEM",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VARIANT",
    "DEFAULTS",
    "ModelClient",
    "ModelClientError",
    "Transport",
    "http_stream",
]

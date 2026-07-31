"""Defaults and configuration helpers for the model client."""

from tux.config import load_config

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:3b"
DEFAULT_TIMEOUT = 90.0
DEFAULT_VARIANT = "full"
DEFAULT_SYSTEM = "linux"

DEFAULTS = {
    "endpoint": DEFAULT_ENDPOINT,
    "model": DEFAULT_MODEL,
    "variant": DEFAULT_VARIANT,
    "system": DEFAULT_SYSTEM,
}


def load_client_options() -> dict[str, str]:
    """Return configured client options overlaid on the built-in defaults."""
    overrides = load_config()
    return {
        "endpoint": overrides.get("endpoint", DEFAULT_ENDPOINT),
        "model": overrides.get("model", DEFAULT_MODEL),
        "system": overrides.get("system", DEFAULT_SYSTEM),
    }

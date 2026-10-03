"""Persistent paths for Tux-managed state."""

from .paths import log_path, ollama_pid_path, state_dir

__all__ = [
    "state_dir",
    "log_path",
    "ollama_pid_path",
]

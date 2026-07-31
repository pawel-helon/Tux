"""Persistent state paths and per-terminal conversation threads.

This package preserves the public API of the former :mod:`tux.state` module.
"""

from .paths import log_path, ollama_pid_path, state_dir, thread_path
from .threads import (
    THREAD_TTL,
    _is_stale,
    _read,
    _shell_start,
    _valid_history,
    clear_thread,
    load_thread,
    save_thread,
)

__all__ = [
    "THREAD_TTL",
    "state_dir",
    "thread_path",
    "log_path",
    "ollama_pid_path",
    "load_thread",
    "save_thread",
    "clear_thread",
]

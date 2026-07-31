"""Filesystem paths for tux's persistent state."""

import os
from pathlib import Path


def state_dir() -> Path:
    """Return tux's state directory, honoring ``XDG_STATE_HOME``.

    The directory is returned whether or not it currently exists.
    """
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "tux"


def thread_path(ppid: int) -> Path:
    """Return the thread file path for the shell identified by ``ppid``."""
    return state_dir() / "threads" / f"{ppid}.json"


def log_path() -> Path:
    """Return the path of tux's command run log under the state directory."""
    return state_dir() / "history.log"


def ollama_pid_path() -> Path:
    """Return the PID-file path for an Ollama server started by tux on Linux."""
    return state_dir() / "ollama.pid"

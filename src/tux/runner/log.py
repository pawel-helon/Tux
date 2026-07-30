"""Persistent run-log reading, appending, clearing, and rotation."""

import time
from pathlib import Path

from tux.state import log_path

from .records import RunRecord, _TIMESTAMP_FORMAT, format_run, parse_run

MAX_LOG_BYTES = 1_000_000


def read_runs() -> list[RunRecord]:
    """Return records in the active run log, oldest first."""
    try:
        text = log_path().read_text(encoding="utf-8")
    except OSError:
        return []
    records = [parse_run(line) for line in text.splitlines()]
    return [record for record in records if record is not None]


def clear_runs() -> None:
    """Delete the active run log and its rotated backup."""
    path = log_path()
    path.unlink(missing_ok=True)
    _backup_path(path).unlink(missing_ok=True)


def append_run(command: str, status: int, description: str) -> None:
    """Append one command execution to the bounded run log."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime(_TIMESTAMP_FORMAT)
    line = format_run(RunRecord(timestamp, status, description, command)) + "\n"
    _rotate_if_full(path, len(line.encode("utf-8")))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _rotate_if_full(path: Path, incoming_bytes: int) -> None:
    """Rotate the active log when the next complete record would overflow it."""
    try:
        current = path.stat().st_size
    except OSError:
        return
    if current == 0 or current + incoming_bytes <= MAX_LOG_BYTES:
        return
    path.replace(_backup_path(path))


def _backup_path(path: Path) -> Path:
    """Return the single rotated-backup path for an active log."""
    return path.with_name(f"{path.name}.1")

"""Per-terminal conversation thread persistence."""

import json
import time
from pathlib import Path

from .paths import thread_path

#: Conversation messages older than this many seconds are treated as a fresh
#: thread. Eight hours comfortably spans a working session while keeping a
#: long-idle terminal — or a PID the OS has since reused — from resurrecting an
#: unrelated conversation.
THREAD_TTL = 8 * 60 * 60


def load_thread(ppid: int) -> list[dict[str, str]]:
    """Return the stored conversation history for ``ppid``, oldest turn first.

    A missing, empty, corrupt, or stale thread yields an empty list so the
    caller simply starts a fresh conversation instead of crashing or carrying
    context onto an unrelated shell.
    """
    data = _read(thread_path(ppid))
    if data is None or _is_stale(data, ppid):
        return []
    history = data.get("history")
    if not _valid_history(history):
        return []
    return history


def save_thread(ppid: int, history: list[dict[str, str]]) -> None:
    """Persist ``history`` for ``ppid``, stamping shell start time and clock.

    The write is atomic (write a temp file, then replace) so a process killed
    mid-write cannot leave a half-written thread behind.
    """
    path = thread_path(ppid)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ppid": ppid,
        "shell_start": _shell_start(ppid),
        "updated_at": time.time(),
        "history": history,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def clear_thread(ppid: int) -> None:
    """Discard the stored thread for ``ppid``; a no-op when none exists."""
    thread_path(ppid).unlink(missing_ok=True)


def _read(path: Path) -> dict | None:
    """Return the parsed thread object, or ``None`` if absent/empty/corrupt."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _is_stale(data: dict, ppid: int) -> bool:
    """Return whether a stored thread is too old or bound to a reused PID."""
    updated = data.get("updated_at")
    if not isinstance(updated, (int, float)) or time.time() - updated > THREAD_TTL:
        return True
    recorded = data.get("shell_start")
    current = _shell_start(ppid)
    return recorded is not None and current is not None and recorded != current


def _valid_history(history: object) -> bool:
    """Return whether ``history`` is a list of well-formed chat messages."""
    if not isinstance(history, list):
        return False
    return all(
        isinstance(turn, dict)
        and isinstance(turn.get("role"), str)
        and isinstance(turn.get("content"), str)
        for turn in history
    )


def _shell_start(pid: int) -> str | None:
    """Return the process start time of ``pid`` from ``/proc``, or ``None``."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        after_comm = stat[stat.rindex(")") + 1:].split()
        return after_comm[19]
    except (ValueError, IndexError):
        return None

"""Temporary raw conversation memory shared by independent Tux sessions."""

import fcntl
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tux.cli.session.state import Session

MEMORY_PATH = Path("/tmp/tux/memory.json")
DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
RETENTION_ENV = "TUX_SHORT_TERM_MEMORY_RETENTION_SECONDS"
MAX_CONTEXT_SESSIONS = 3
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_RECENT_REFERENCE_RE = re.compile(
    r"\b(?:last\s+time|last\s+conversation|previous(?:ly)?|earlier|before)\b",
    re.IGNORECASE,
)
_STOP_WORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has "
    "have he her here him his how i if in is it its me my of on or our she so "
    "that the their them then there these they this those to up us was we were "
    "what when where which who why will with would you your again tell remind "
    "remember previous earlier conversation talk discussed said".split()
)


def save_session(session: "Session", path: Path = MEMORY_PATH) -> None:
    """Upsert this session's raw turns, pruning expired sessions when possible."""
    if not session.history or not _valid_session(session):
        return

    try:
        retention = _retention_seconds()
        now = time.time()
        with _locked_directory(path.parent):
            sessions = _load(path)
            sessions = [
                item
                for item in sessions
                if now - item["updated_at"] <= retention
            ]
            saved = {
                "id": session.id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "conversation": list(session.history),
            }
            for index, item in enumerate(sessions):
                if item["id"] == session.id:
                    sessions[index] = saved
                    break
            else:
                sessions.append(saved)
            _write(path, sessions)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # Memory is optional; persistence errors must not stop a response.
        return


def retrieve(question: str, path: Path = MEMORY_PATH) -> list[list[dict[str, str]]]:
    """Return raw conversations from the most relevant unexpired sessions."""
    query = _keywords(question)
    if not query:
        return []

    try:
        now = time.time()
        retention = _retention_seconds()
        with _locked_directory(path.parent):
            sessions = _load(path)
            active = [
                item
                for item in sessions
                if now - item["updated_at"] <= retention
            ]
            if len(active) != len(sessions):
                try:
                    _write(path, active)
                except OSError:
                    pass
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []

    if _RECENT_REFERENCE_RE.search(question):
        recent = sorted(active, key=lambda item: item["updated_at"], reverse=True)
        return [item["conversation"] for item in recent[:MAX_CONTEXT_SESSIONS]]

    ranked: list[tuple[int, float, list[dict[str, str]]]] = []
    for item in active:
        conversation = item["conversation"]
        text = " ".join(turn["content"] for turn in conversation)
        terms = _keywords(text)
        score = len(query & terms)
        if score:
            ranked.append((score, item["updated_at"], conversation))
    ranked.sort(key=lambda result: (result[0], result[1]), reverse=True)
    selected = ranked[:MAX_CONTEXT_SESSIONS]
    selected.sort(key=lambda result: result[1], reverse=True)
    return [conversation for _, _, conversation in selected]


def references_recent_session(question: str) -> bool:
    """Return whether the question explicitly asks about recent conversation history."""
    return bool(_RECENT_REFERENCE_RE.search(question))


def retrieved_context(
    conversations: list[list[dict[str, str]]],
) -> dict[str, str] | None:
    """Represent retrieved turns as an explicitly labeled, separate context item."""
    if not conversations:
        return None
    lines = ["Previous conversation retrieved from short-term memory:"]
    for index, conversation in enumerate(conversations, start=1):
        recency = " (most recent)" if index == 1 else ""
        lines.append(f"\nPrevious session {index}{recency}:")
        for turn in conversation:
            speaker = "User" if turn["role"] == "user" else "Tux"
            lines.append(f"{speaker}: {turn['content']}")
    lines.append("Use this only as previous context; it is not this session's history.")
    return {"role": "system", "content": "\n".join(lines)}


def _valid_session(session: "Session") -> bool:
    return bool(session.id) and all(
        isinstance(turn, dict)
        and isinstance(turn.get("role"), str)
        and turn["role"] in {"user", "assistant"}
        and isinstance(turn.get("content"), str)
        for turn in session.history
    )


def _valid_entry(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and isinstance(entry.get("created_at"), (int, float))
        and isinstance(entry.get("updated_at"), (int, float))
        and isinstance(entry.get("conversation"), list)
        and all(
            isinstance(turn, dict)
            and isinstance(turn.get("role"), str)
            and turn["role"] in {"user", "assistant"}
            and isinstance(turn.get("content"), str)
            for turn in entry["conversation"]
        )
    )


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), list):
        return []
    return [entry for entry in raw["sessions"] if _valid_entry(entry)]


def _write(path: Path, sessions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".memory-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump({"sessions": sessions}, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class _locked_directory:
    """Serialize memory operations using an advisory lock on the parent directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.descriptor: int | None = None

    def __enter__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX)
        except OSError:
            os.close(self.descriptor)
            self.descriptor = None
            raise

    def __exit__(self, *_: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)


def _retention_seconds() -> float:
    configured = os.environ.get(RETENTION_ENV)
    if configured is None:
        return DEFAULT_RETENTION_SECONDS
    try:
        value = float(configured)
    except ValueError:
        return DEFAULT_RETENTION_SECONDS
    return max(0.0, value)


def _keywords(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 1 and token.casefold() not in _STOP_WORDS
    }

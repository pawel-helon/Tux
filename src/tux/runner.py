"""Execute a staged command in tux's own subprocess and record it to the run log.

tux proposes a command and the user must explicitly choose to run it; only then
is the command executed here, in a subshell that inherits tux's
stdin/stdout/stderr so the command's own output reaches the user and interactive
commands keep working. Because tux — not the user's shell — runs the command, it
never lands in the shell's history, so each command tux actually runs is
appended to an on-disk log for traceability.

Execution is a small callable seam (:data:`CommandRunner`) mirroring the model
client's injectable transport, so tests can assert run and log behavior without
spawning real processes. A run *tees* its output: the command's combined output
is shown to the user as it arrives while a bounded copy is captured and returned,
so a discovery step's result can be fed back to the model to resolve a later
step. The captured copy is deliberately never written to the run log (size and
secret-leakage risk).
"""

import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tux.state import log_path

#: Upper bound on captured output characters. The capture exists to feed the
#: model and is bounded so a large output cannot blow the model context or bloat
#: the conversation thread; the value is a sane cap, not a hard contract.
MAX_CAPTURED_CHARS = 4000

#: Upper bound on the *active* run log in bytes. Once a fresh record would push
#: the log past this cap, the whole active log is rotated into a single backup
#: and a new active log is started, so the log a user reads with ``tux history``
#: cannot grow without bound. A run record is short (timestamp, status,
#: description, one command line), so this holds a long history while still being
#: a hard ceiling.
MAX_LOG_BYTES = 1_000_000

#: ``strftime`` pattern for a run record's timestamp field.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

#: Field separator between a record's fields. The command is the final field, so
#: a command containing this character survives the round-trip — the reader splits
#: off only the leading fields and keeps the remainder verbatim.
_FIELD_SEP = "\t"

#: Leading marker on every record written by this (and later) versions, telling
#: the reader the line carries a stored description. It is deliberately not a
#: valid timestamp prefix (a timestamp starts with a 4-digit year), so a
#: pre-change line — which has no marker and leads with its timestamp — is never
#: mistaken for a new one, and vice versa. This is how :func:`parse_run` branches
#: deterministically instead of guessing from the tab-field count (a pre-change
#: command may itself contain a tab).
_RECORD_MARKER = "v2"

#: Description stored for a pre-change log line — one written before the
#: description field existed, so it has no recorded description. The reader fills
#: this placeholder in rather than dropping the entry or mis-reading part of the
#: command as a description; the listing shows it in the description position.
NO_DESCRIPTION = "(no description recorded)"

#: A command runner executes a shell command and returns ``(status, output)`` —
#: its exit status and a bounded copy of what it printed. The default runs it in
#: a subshell, teeing output to the terminal; tests inject a fake so the walk is
#: exercised without spawning a real process.
CommandRunner = Callable[[str], tuple[int, str]]


def run_command(command: str) -> tuple[int, str]:
    """Run ``command`` in a subshell, teeing output, and return ``(status, output)``.

    The command's combined stdout/stderr is streamed straight to the user's
    terminal as it arrives — so progressive output stays live — while a bounded
    copy (capped at :data:`MAX_CAPTURED_CHARS`) is buffered and returned so a
    discovery step's result can be fed back to the model. The captured copy is
    for the model and the user only; it is never written to the run log.
    """
    captured: list[str] = []
    remaining = MAX_CAPTURED_CHARS
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    stream = process.stdout
    if stream is not None:
        for line in stream:
            sys.stdout.write(line)
            sys.stdout.flush()
            if remaining > 0:
                kept = line[:remaining]
                captured.append(kept)
                remaining -= len(kept)
    status = process.wait()
    return status, "".join(captured)


@dataclass(frozen=True)
class RunRecord:
    """One recorded run: when it ran, the exit status, the command's one-line
    description, and the command run.

    The timestamp and status are stored for the record and the re-run/record
    paths; the description is the teaching payload the listing shows. A record
    read back from a pre-change line carries :data:`NO_DESCRIPTION` in
    ``description`` (it had none stored).
    """

    timestamp: str
    status: int
    description: str
    command: str


def _one_line(text: str) -> str:
    """Collapse any tab, carriage return, or newline in ``text`` to a single space.

    The command must stay the tab-safe *final* field, so a middle field (the
    description) may not carry the field separator — nor a newline that would
    split the single-line record. Flattening those to spaces keeps the record one
    line and keeps the command's round-trip intact.
    """
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def format_run(record: RunRecord) -> str:
    """Format a run record as its single tab-separated log line (no trailing newline).

    This is the one place the on-disk format is spelled out; :func:`append_run`
    writes it and :func:`parse_run` reads it, so the writer and reader cannot
    drift apart. The line leads with :data:`_RECORD_MARKER` so the reader can tell
    a description-carrying record from a pre-change line, and the command stays the
    final field so a tab within it survives; the description is flattened to one
    line first so it can never break either invariant.
    """
    description = _one_line(record.description)
    return _FIELD_SEP.join(
        (_RECORD_MARKER, record.timestamp, str(record.status), description, record.command)
    )


def parse_run(line: str) -> RunRecord | None:
    """Parse one log line into a :class:`RunRecord`, or ``None`` if it is malformed.

    A line bearing :data:`_RECORD_MARKER` is a new record: the marker, timestamp,
    status, and description are split off and everything after them is the command
    verbatim, so a command containing a tab is preserved whole. Any other line is
    treated as a pre-change record (timestamp, status, command) and parses with its
    description set to :data:`NO_DESCRIPTION`. A line missing a field, or whose
    status is not an integer, yields ``None`` so the reader can skip it.
    """
    text = line.rstrip("\n")
    if text.startswith(_RECORD_MARKER + _FIELD_SEP):
        fields = text.split(_FIELD_SEP, 4)
        if len(fields) < 5:
            return None
        _, timestamp, status_text, description, command = fields
    else:
        fields = text.split(_FIELD_SEP, 2)
        if len(fields) < 3:
            return None
        timestamp, status_text, command = fields
        description = NO_DESCRIPTION
    try:
        status = int(status_text)
    except ValueError:
        return None
    return RunRecord(
        timestamp=timestamp, status=status, description=description, command=command
    )


def read_runs() -> list[RunRecord]:
    """Return the records in the active run log, oldest first.

    A missing or unreadable log yields an empty list. Lines that do not match the
    recorded format are skipped rather than raising, so one bad line never hides
    the well-formed records around it.
    """
    try:
        text = log_path().read_text(encoding="utf-8")
    except OSError:
        return []
    records = [parse_run(line) for line in text.splitlines()]
    return [record for record in records if record is not None]


def clear_runs() -> None:
    """Delete the run log and its rotated backup; a no-op when neither exists.

    Only the run log is touched — config and conversation threads live elsewhere
    and are left intact.
    """
    path = log_path()
    path.unlink(missing_ok=True)
    _backup_path(path).unlink(missing_ok=True)


def append_run(command: str, status: int, description: str) -> None:
    """Append one run record — timestamp, exit status, description, command — to the log.

    The parent directory is created if absent. Before writing, the active log is
    rotated if this record would push it past :data:`MAX_LOG_BYTES`. The
    ``description`` is the one-line description of the proposal that produced the
    run, stored so ``tux history`` can show *why* the command ran. Only the
    command tux actually ran is recorded; the command's own output is never
    written here.
    """
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime(_TIMESTAMP_FORMAT)
    line = format_run(RunRecord(timestamp, status, description, command)) + "\n"
    _rotate_if_full(path, len(line.encode("utf-8")))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _rotate_if_full(path: Path, incoming_bytes: int) -> None:
    """Rotate the active log into a single backup when the next record would overflow.

    When the existing log plus the incoming record would exceed
    :data:`MAX_LOG_BYTES`, the whole active log is moved onto the backup
    (overwriting any prior backup) and a fresh active log is started. Moving the
    file whole keeps every record intact — none is split mid-line, dropped, or
    duplicated — and at most one backup is ever kept.
    """
    try:
        current = path.stat().st_size
    except OSError:
        return
    if current == 0 or current + incoming_bytes <= MAX_LOG_BYTES:
        return
    path.replace(_backup_path(path))


def _backup_path(path: Path) -> Path:
    """Return the single rotated-backup path for the active log (``history.log.1``)."""
    return path.with_name(f"{path.name}.1")

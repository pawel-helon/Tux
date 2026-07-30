"""Implementation of the ``tux history`` command."""

import argparse
import sys

from tux.chooser import Chooser, select
from tux.modes.command import CommandSuggestion
from tux.runner import (
    CommandRunner, RunRecord, clear_runs, read_runs, run_command,
)

HISTORY_EMPTY = "tux has not recorded any runs yet."
_RESET = "\x1b[0m"
_LABEL_STYLE = "\x1b[2m"
_COMMAND_STYLE = "\x1b[1;36m"

def run_history(
    args: argparse.Namespace,
    *,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
) -> int:
    """Dispatch a ``tux history`` invocation: clear, re-run an entry, or list.

    ``--clear`` empties the log and wins over the others; otherwise an ``entry``
    reference re-stages that recorded command, and with neither the active log is
    listed (optionally limited to the most recent ``-n`` runs).

    Returns:
        ``0`` on a successful list or clear, ``0`` when a re-run dismisses or runs
        cleanly (or the run's own exit status), and ``1`` for a bad re-run
        reference.
    """
    if args.clear:
        clear_runs()
        return 0
    if args.entry is not None:
        return _history_rerun(args.entry, runner, chooser)
    return _history_list(args.limit)

def _history_list(limit: int | None) -> int:
    """Print the active run log, numbered chronologically; honor a recent-N limit.

    Numbers are positional within the active log (entry 1 is the oldest record),
    so a ``-n`` limit shows a tail with those same numbers preserved — the number
    a user reads is the number ``tux history <n>`` re-runs. An empty or missing
    log prints a friendly note and still exits 0.
    """
    records = read_runs()
    if not records:
        print(HISTORY_EMPTY)
        return 0
    numbered = list(enumerate(records, start=1))
    if limit is not None:
        numbered = numbered[-limit:] if limit > 0 else []
    from tux.cli.session import _interactive

    styled = _interactive()
    for number, record in numbered:
        _print_history_entry(number, record, styled=styled)
    return 0

def _print_history_entry(number: int, record: RunRecord, *, styled: bool) -> None:
    """Render one numbered run entry: ``N. <command> — <description>``.

    For a learning tool the *why* — the command's one-line description — is the
    teaching payload, so the entry pairs the command with its description and
    drops the timestamp and exit status from the display (both stay stored and
    still drive re-run). A pre-change entry with no stored description shows the
    :data:`NO_DESCRIPTION` placeholder in the description position. At a terminal
    the line carries the established styling — a dim number, the command in the
    command style, and the description dimmed — so the listing matches tux's other
    output; piped or redirected it is plain text with no escape sequences so it
    stays script-friendly.
    """
    if not styled:
        print(f"{number}. {record.command} — {record.description}")
        return
    print(
        f"{_LABEL_STYLE}{number}.{_RESET} "
        f"{_COMMAND_STYLE}{record.command}{_RESET} "
        f"{_LABEL_STYLE}— {record.description}{_RESET}"
    )

def _history_rerun(reference: str, runner: CommandRunner, chooser: Chooser) -> int:
    """Re-stage the recorded command named by ``reference`` through the normal run path.

    The reference is a 1-based number (optionally ``!``-prefixed) into the active
    log. The recorded command is wrapped in a single-command proposal and run
    through the same staging tail as a fresh suggestion — destructive flagging,
    the run/dismiss chooser, the command runner, and the run-log append — with no
    model call, so the command text is exactly what was logged. The re-staged
    proposal inherits the source entry's description, so the re-logged run carries
    that real description (never a synthesized string) and lists with it. A
    reference that is non-numeric, out of range, or used against an empty log
    prints a friendly
    error, runs nothing, and exits non-zero.
    """
    records = read_runs()
    index = _parse_reference(reference)
    if index is None or not (1 <= index <= len(records)):
        print(f"tux: no recorded run #{reference}", file=sys.stderr)
        return 1
    record = records[index - 1]
    suggestion = CommandSuggestion(
        title=f"Re-running #{index}",
        command=record.command,
        description=record.description,
    )
    from tux.cli.session import _present_single_command

    status, _ = _present_single_command([suggestion], runner, chooser)
    return status

def _parse_reference(reference: str) -> int | None:
    """Parse a re-run reference into a positive 1-based index, or ``None``.

    A single optional leading ``!`` is stripped (so ``3`` and ``!3`` are the same
    reference); the remainder must be a plain positive integer. Anything else —
    empty, non-numeric, zero, or negative — yields ``None`` for the caller to
    reject.
    """
    text = reference[1:] if reference.startswith("!") else reference
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


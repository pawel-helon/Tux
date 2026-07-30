"""Terminal input seams shared by interactive CLI flows."""

import readline
import sys
from collections.abc import Callable

from tux.chooser import read_line

CLARIFY_PROMPT = "clarify: "
EXPLAIN_PROMPT = "ask: "
EDIT_PROMPT = "edit: "

ClarifyReader = Callable[[str], str]
EditReader = Callable[[str], str]


def interactive() -> bool:
    """Return whether stdin and stdout are both attached to a terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def default_reader(prompt: str) -> str:
    """Read one line, supporting Escape and Ctrl-D cancellation on a terminal."""
    if interactive():
        return read_line(prompt)
    return input(prompt)


def default_edit_reader(command: str) -> str:
    """Read an edited command from a line pre-filled with ``command``."""
    if interactive():
        return read_line(EDIT_PROMPT, prefill=command)
    readline.set_startup_hook(lambda: readline.insert_text(command))
    try:
        return input(EDIT_PROMPT)
    finally:
        readline.set_startup_hook()


def read_clarification(reader: ClarifyReader) -> str | None:
    """Read clarification text, returning ``None`` when the user backs out."""
    return _read_optional(reader, CLARIFY_PROMPT)


def read_follow_up(reader: ClarifyReader) -> str | None:
    """Read an explanation follow-up, returning ``None`` when leaving."""
    return _read_optional(reader, EXPLAIN_PROMPT)


def read_edit(editor: EditReader, command: str) -> str | None:
    """Read edited command text, returning ``None`` when cancelled."""
    try:
        edited = editor(command).strip()
    except EOFError:
        print()
        return None
    return edited or None


def _read_optional(reader: ClarifyReader, prompt: str) -> str | None:
    try:
        text = reader(prompt).strip()
    except EOFError:
        print()
        return None
    return text or None

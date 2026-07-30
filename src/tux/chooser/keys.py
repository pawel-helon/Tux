"""Decode logical keypresses from terminal input."""

import select as _select
import sys

#: Bytes that confirm the highlighted option.
ENTER = ("\r", "\n")
#: End-of-transmission (Ctrl-D) byte; in cbreak mode it arrives as data, not EOF.
EOT = "\x04"
#: Escape, both on its own and as the lead byte of an arrow-key CSI sequence.
ESC = "\x1b"
#: Rub-out bytes that delete the last character while editing a line.
BACKSPACE = ("\x7f", "\x08")
#: Keys that stop an in-flight stream.
STOP_KEYS = (ESC, EOT)
#: Internal sentinel for a complete but unsupported terminal escape sequence.
IGNORED = "ignored"


def read_key() -> str | None:
    """Read one logical keypress from the terminal.

    Returns ``"left"``/``"right"`` for normal CSI arrows, application-mode
    arrows, and modified CSI arrows. A complete but unsupported escape sequence
    returns :data:`IGNORED` so the chooser keeps running instead of treating it
    as a bare Escape. Returns ``None`` only on end-of-input/Ctrl-D.
    """
    fd = sys.stdin.fileno()
    char = sys.stdin.read(1)

    if char in ("", EOT):
        return None

    if char != ESC:
        if char in ("h", "j"):
            return "left"
        if char in ("l", "k"):
            return "right"
        return char

    ready, _, _ = _select.select([fd], [], [], 0.05)
    if not ready:
        return ESC

    prefix = sys.stdin.read(1)

    if prefix == "O":
        ready, _, _ = _select.select([fd], [], [], 0.05)
        if not ready:
            return IGNORED
        final = sys.stdin.read(1)
        return {
            "A": "left",
            "B": "right",
            "C": "right",
            "D": "left",
        }.get(final, IGNORED)

    if prefix != "[":
        return IGNORED

    sequence = ""
    while len(sequence) < 64:
        ready, _, _ = _select.select([fd], [], [], 0.05)
        if not ready:
            return IGNORED
        byte = sys.stdin.read(1)
        if byte == "":
            return None
        sequence += byte
        if "@" <= byte <= "~":
            break
    else:
        return IGNORED

    final = sequence[-1]
    return {
        "A": "left",
        "B": "right",
        "C": "right",
        "D": "left",
    }.get(final, IGNORED)

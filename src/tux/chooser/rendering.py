"""Render terminal choice controls."""

import shutil
import sys
from collections.abc import Sequence

_INVERSE = "\x1b[7m"
_RESET = "\x1b[0m"


def draw(
    options: Sequence[str],
    index: int,
    *,
    previous_lines: int = 0,
) -> int:
    """Render the button row in place and return its physical line count."""
    plain_buttons = [f"[ {option} ]" for option in options]
    rendered_buttons = [
        f"{_INVERSE}{button}{_RESET}" if i == index else button
        for i, button in enumerate(plain_buttons)
    ]
    plain_row = " ".join(plain_buttons)
    rendered_row = " ".join(rendered_buttons)

    if previous_lines:
        sys.stdout.write("\r" + "\x1b[1A" * (previous_lines - 1))
        for line in range(previous_lines):
            sys.stdout.write("\x1b[2K")
            if line < previous_lines - 1:
                sys.stdout.write("\x1b[1B\r")
        sys.stdout.write("\x1b[1A" * (previous_lines - 1) + "\r")

    sys.stdout.write(rendered_row)
    sys.stdout.flush()

    columns = max(1, shutil.get_terminal_size(fallback=(80, 24)).columns)
    return max(1, (len(plain_row) - 1) // columns + 1)

"""Interactive single-choice terminal menu."""

import sys
import termios
import tty
from collections.abc import Callable, Sequence

from tux.chooser.keys import ENTER, ESC, IGNORED, read_key
from tux.chooser.rendering import draw

#: A chooser shows option labels and returns the chosen index.
Chooser = Callable[[Sequence[str]], int]


def select(options: Sequence[str], *, default: int = 0) -> int:
    """Show ``options`` as an arrow-navigable row and return the chosen index.

    ``default`` is highlighted first and returned on Ctrl-D, Escape, or Ctrl-C,
    so callers can keep the safe choice first.
    """
    index = default
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        drawn_lines = draw(options, index)
        while True:
            key = read_key()
            if key in ENTER:
                return index
            if key is None or key == ESC:
                return default
            if key == IGNORED:
                continue
            if key == "left":
                index = (index - 1) % len(options)
            elif key == "right":
                index = (index + 1) % len(options)
            else:
                continue
            drawn_lines = draw(options, index, previous_lines=drawn_lines)
    except KeyboardInterrupt:
        return default
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        print()

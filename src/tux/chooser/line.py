"""Single-line terminal editing."""

import sys
import termios
import tty

from tux.chooser.keys import BACKSPACE, ENTER, EOT, ESC


def read_line(prompt: str, *, prefill: str = "") -> str:
    """Read one edited line; return ``""`` when the user backs out."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    buffer = list(prefill)
    try:
        tty.setcbreak(fd)
        sys.stdout.write(prompt + prefill)
        sys.stdout.flush()
        while True:
            char = sys.stdin.read(1)
            if char in ("", EOT):
                return ""
            if char in ENTER:
                return "".join(buffer)
            if char == ESC:
                if sys.stdin.read(1) == "[":
                    sys.stdin.read(1)
                    continue
                return ""
            if char in BACKSPACE:
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if char < " ":
                continue
            buffer.append(char)
            sys.stdout.write(char)
            sys.stdout.flush()
    except KeyboardInterrupt:
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        print()

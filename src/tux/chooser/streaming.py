"""Non-blocking terminal stop-key monitoring."""

import contextlib
import select as _select
import sys
import termios
import tty
from collections.abc import Callable, Iterator

from tux.chooser.keys import STOP_KEYS


@contextlib.contextmanager
def stop_watch() -> Iterator[Callable[[], bool]]:
    """Yield a non-blocking poll for a stop keypress while a reply streams."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        yield lambda: False
        return

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    def pressed() -> bool:
        ready, _, _ = _select.select([fd], [], [], 0)
        if not ready:
            return False
        return sys.stdin.read(1) in STOP_KEYS

    try:
        tty.setcbreak(fd)
        yield pressed
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

"""Lifecycle management for the terminal thinking indicator."""

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

from .animation import _spin
from .constants import _CLEAR_LINE, _HIDE_CURSOR, _SHOW_CURSOR


@contextmanager
def thinking(stream: TextIO | None = None) -> Iterator[None]:
    """Animate the thinking indicator for the duration of the wrapped block."""
    out = sys.stdout if stream is None else stream
    if not out.isatty():
        yield
        return

    stop = threading.Event()
    out.write(_HIDE_CURSOR)
    out.flush()
    thread = threading.Thread(target=_spin, args=(out, stop), daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        out.write(_CLEAR_LINE)
        out.write(_SHOW_CURSOR)
        out.flush()

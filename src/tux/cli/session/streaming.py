"""Streaming output helpers for conversational and explanatory replies."""

import sys
from collections.abc import Iterator

from tux.chooser import stop_watch
from tux.client import ModelClientError
from tux.thinking import thinking


def stream_reply(pieces: Iterator[str]) -> str:
    """Stream reply pieces to stdout and return the accumulated text."""
    collected: list[str] = []
    printed = False
    try:
        with thinking():
            first = next(pieces)
        sys.stdout.write(first)
        sys.stdout.flush()
        printed = True
        collected.append(first)
        with stop_watch() as stop_requested:
            for piece in pieces:
                sys.stdout.write(piece)
                sys.stdout.flush()
                collected.append(piece)
                if stop_requested():
                    break
    except ModelClientError:
        if printed:
            sys.stdout.write("\n")
            sys.stdout.flush()
        raise
    finally:
        pieces.close()
    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(collected)

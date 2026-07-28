"""Animated "tux is thinking" indicator shown during a blocking model wait.

While tux is blocked on the model — draining the whole reply before the call
returns — this puts an animated indicator on its own line so the user can see
tux is working rather than hung. It is presentation-only: it changes nothing
about what is proposed, run, logged, or stored, and never touches the model
client, so the client stays pure and injectable.

Standard-library only, raw ANSI — no ``rich`` or any new dependency — matching
the style of :mod:`tux.cli`. Because the blocking call returns only once the
reply is fully drained, the animation is driven on a separate daemon thread so
it keeps ticking through time-to-first-token, the longest silent stretch on a
local model. The live thread is kept behind a seam — the way the chooser's raw
key reader is — so it is never exercised under pytest: the gating decision, the
frame sequence, and the spin loop are testable as pure pieces against an
injected stream, while real threads and a real terminal stay out of the tests.

The indicator appears only when stdout is a terminal. That is intentionally
narrower than :func:`tux.cli._interactive` (which also requires stdin): the
indicator is an stdout-side affordance that reads no input, so it still shows
when only stdin is piped, while staying silent whenever stdout is not a TTY —
keeping piped or redirected output byte-for-byte identical to today's.
"""

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol, TextIO

#: Dim style and reset. These mirror :mod:`tux.cli`'s de-emphasised
#: ``_LABEL_STYLE``/``_RESET`` so the indicator label reads in the same dim tone
#: as the proposal overview rather than competing with it.
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"

#: Hide the cursor while spinning and restore it on exit, so a blinking caret
#: does not flicker over the glyph during the wait.
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"

#: Per-frame: return to the start of the line and erase to its end before
#: writing the current frame, mirroring ``chooser._draw``'s in-place redraw.
_ERASE_TO_END = "\x1b[K"

#: On exit: return to the start of the line and erase the whole line, so the
#: indicator leaves no glyph or label residue and the next output starts clean.
_CLEAR_LINE = "\r\x1b[2K"

#: Spinner glyphs, cycled one per tick to animate the wait.
_GLYPHS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

#: The de-emphasised label shown beside the spinner glyph.
_LABEL = "tux is thinking"

#: Seconds between frames; short enough to read as motion, long enough to stay
#: cheap. Used as the wait the spin loop blocks on between frames.
_INTERVAL = 0.1


class _StopSignal(Protocol):
    """A stop signal the spin loop waits on between frames.

    :class:`threading.Event` satisfies this: :meth:`wait` blocks for ``timeout``
    seconds and returns ``True`` the moment the signal is set, so the loop both
    paces itself and stops promptly when the model call returns.
    """

    def wait(self, timeout: float | None = None) -> bool:
        """Block up to ``timeout`` seconds; return whether the signal is set."""


def frames() -> Iterator[str]:
    """Yield successive indicator frames, cycling the glyphs indefinitely.

    Each frame returns to the start of the line, erases to its end, then writes
    the dim glyph and label — the same in-place redraw idiom the chooser uses,
    so repeated frames repaint one line rather than scrolling.
    """
    index = 0
    while True:
        glyph = _GLYPHS[index % len(_GLYPHS)]
        yield f"\r{_ERASE_TO_END}{_DIM}{glyph} {_LABEL}{_RESET}"
        index += 1


def _spin(stream: TextIO, stop: _StopSignal) -> None:
    """Write frames to ``stream`` until ``stop`` is signalled (the thread target).

    Each frame is written and flushed, then the loop waits the inter-frame
    interval on ``stop``; the wait returns ``True`` the instant ``stop`` is set,
    so the spinner halts as soon as the wait it is blocked on is signalled.
    """
    for frame in frames():
        stream.write(frame)
        stream.flush()
        if stop.wait(_INTERVAL):
            return


@contextmanager
def thinking(stream: TextIO | None = None) -> Iterator[None]:
    """Animate the "tux is thinking" indicator for the duration of the block.

    Wrap a blocking model call in ``with thinking():`` and the indicator spins
    on its own line while the call waits, then erases itself before control
    returns so the next output starts on a clean line. When ``stream`` (default
    :data:`sys.stdout`) is not a terminal, this is a no-op: nothing is emitted
    and the body runs unchanged, so piped output is identical to today's.

    The indicator is always torn down — line cleared, cursor restored — on
    normal return, on exception, and on interrupt (Ctrl-C), so a wait that ends
    any way leaves the terminal clean.

    Args:
        stream: Output stream the indicator is written to; defaults to
            :data:`sys.stdout`. Injected in tests so the gate and teardown can
            be asserted against a fake stream.
    """
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

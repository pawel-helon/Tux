"""Frame generation and the blocking spinner loop."""

from collections.abc import Iterator
from typing import Protocol, TextIO

from .constants import _DIM, _ERASE_TO_END, _GLYPHS, _INTERVAL, _LABEL, _RESET


class _StopSignal(Protocol):
    """A signal the spin loop waits on between frames."""

    def wait(self, timeout: float | None = None) -> bool:
        """Block up to ``timeout`` seconds; return whether the signal is set."""


def frames() -> Iterator[str]:
    """Yield successive indicator frames, cycling the glyphs indefinitely."""
    index = 0
    while True:
        glyph = _GLYPHS[index % len(_GLYPHS)]
        yield f"\r{_ERASE_TO_END}{_DIM}{glyph} {_LABEL}{_RESET}"
        index += 1


def _spin(stream: TextIO, stop: _StopSignal) -> None:
    """Write frames to ``stream`` until ``stop`` is signalled."""
    for frame in frames():
        stream.write(frame)
        stream.flush()
        if stop.wait(_INTERVAL):
            return

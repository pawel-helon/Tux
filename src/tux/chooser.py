"""Interactive single-choice menu driven by the arrow keys, standard-library only.

This is the run/dismiss selection surface: tux prints the options as a single row
of bracketed buttons and the user moves the highlight with the left/right arrow
keys (or ``h``/``l``, with up/down and ``j``/``k`` kept as aliases) and presses
Enter to choose. It puts the terminal into cbreak mode with :mod:`termios` and
:mod:`tty`, reads one keypress at a time, and always restores the terminal state,
so it is terminal-only by design and lives behind the injectable :data:`Chooser`
seam in :mod:`tux.cli` — tests supply a fake, so this raw reader is never
exercised under pytest.

The safe option is the default: it starts highlighted, and any abort —
end-of-input (Ctrl-D), Escape, or interrupt — resolves to it rather than to an
action, so a caller that lists the safe choice first never runs anything on a
stray keystroke.
"""

import contextlib
import select as _select
import shutil
import sys
import termios
import tty
from collections.abc import Callable, Iterator, Sequence

#: A chooser shows the given option labels and returns the chosen index. The
#: default highlights — and falls back to — index ``0``, so callers list the
#: safe option first; tests inject a fake to drive the run/dismiss flow.
Chooser = Callable[[Sequence[str]], int]

#: Bytes that confirm the highlighted option.
_ENTER = ("\r", "\n")
#: End-of-transmission (Ctrl-D) byte; in cbreak mode it arrives as data, not EOF.
_EOT = "\x04"
#: Escape, both on its own and as the lead byte of an arrow-key CSI sequence.
_ESC = "\x1b"
#: Rub-out bytes that delete the last character while editing a line.
_BACKSPACE = ("\x7f", "\x08")

#: Keys that stop an in-flight stream. A bare Escape or a Ctrl-D reuses the
#: back-out vocabulary :func:`select` and :func:`read_line` already speak (item
#: 14 treats both as "get me out"), so the same keypress that backs out of a
#: menu also ends a streaming reply.
_STOP_KEYS = (_ESC, _EOT)
#: Internal sentinel for a complete but unsupported terminal escape sequence.
_IGNORED = "ignored"

#: Inverse-video on/off, used to highlight the currently-selected option.
_INVERSE = "\x1b[7m"
_RESET = "\x1b[0m"


def select(options: Sequence[str], *, default: int = 0) -> int:
    """Show ``options`` as an arrow-navigable button row and return the chosen index.

    ``default`` is highlighted first and returned on any abort (Ctrl-D, Escape,
    or Ctrl-C), so the caller's safe choice stays the default.
    """
    index = default
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        drawn_lines = _draw(options, index)
        while True:
            key = _read_key()
            if key in _ENTER:
                return index
            if key is None or key == _ESC:
                return default
            if key == _IGNORED:
                continue
            if key == "left":
                index = (index - 1) % len(options)
            elif key == "right":
                index = (index + 1) % len(options)
            else:
                continue
            drawn_lines = _draw(options, index, previous_lines=drawn_lines)
    except KeyboardInterrupt:
        return default
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        # Leave the cursor on a fresh line below the button row we drew.
        print()


def read_line(prompt: str, *, prefill: str = "") -> str:
    """Read one edited line at the terminal; return ``""`` when the user backs out.

    This is the free-text counterpart to :func:`select`: the clarify, explain
    follow-up, and inline-edit prompts read through it so a bare Escape or a
    Ctrl-D backs the user out to the caller's button row rather than committing
    the action. The line starts seeded with ``prefill`` — the edit prompt offers
    the current command for tweaking — printable keys extend it, Backspace trims
    it, and Enter submits it. A bare Escape, a Ctrl-D, or an interrupt discards
    the buffer and returns ``""`` — the same "blank line means back out" signal
    the callers already treat as a no-op — so a stray keystroke never turns into a
    submitted line, and Ctrl-D works even while the pre-filled command still fills
    the line (readline would have rung the bell instead). Arrow-key CSI sequences
    are swallowed: this is a single-line editor, with no cursor movement.

    Like :func:`select` it drives the terminal in cbreak mode via :mod:`termios`
    and :mod:`tty`, echoes each keypress itself (cbreak disables echo), always
    restores the saved terminal state, and leaves the cursor on a fresh line. It
    is terminal-only by design and lives behind the injectable reader seams in
    :mod:`tux.cli`, so tests drive back-out through a fake and never reach here.
    """
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    buffer = list(prefill)
    try:
        tty.setcbreak(fd)
        sys.stdout.write(prompt + prefill)
        sys.stdout.flush()
        while True:
            char = sys.stdin.read(1)
            if char in ("", _EOT):
                return ""  # Ctrl-D or a closed stream: back out
            if char in _ENTER:
                return "".join(buffer)
            if char == _ESC:
                # A CSI arrow sequence is ESC [ …; a bare Escape backs out.
                if sys.stdin.read(1) == "[":
                    sys.stdin.read(1)
                    continue
                return ""
            if char in _BACKSPACE:
                if buffer:
                    buffer.pop()
                    # Rub out the last glyph: back up, overwrite with a space, back up.
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if char < " ":
                # Other control bytes (Tab, stray sequence finals) never enter the
                # buffer, so only visible text is ever submitted.
                continue
            buffer.append(char)
            sys.stdout.write(char)
            sys.stdout.flush()
    except KeyboardInterrupt:
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        # Leave the cursor on a fresh line below the prompt we drew.
        print()


@contextlib.contextmanager
def stop_watch() -> Iterator[Callable[[], bool]]:
    """Yield a non-blocking poll for a stop keypress while a reply streams.

    The yielded callable returns ``True`` once the user has pressed a stop key (a
    bare Escape or a Ctrl-D — the same back-out vocabulary :func:`select` and
    :func:`read_line` speak) and ``False`` otherwise, checking stdin without
    blocking so it can be called between streamed pieces without stalling the
    stream. Like :func:`select` it drives the terminal in cbreak mode via
    :mod:`termios` and :mod:`tty` so a single keypress is available without Enter,
    and always restores the saved terminal state on exit.

    Off a terminal (stdin or stdout not a tty) it engages no key handling at all
    and yields a poll that never reports a stop, so a piped or redirected stream
    runs uninterrupted. It is terminal-only by design and lives behind the
    injectable seam in :mod:`tux.cli`, so tests drive a stop through a fake and
    never reach this raw reader.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        yield lambda: False
        return
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    def pressed() -> bool:
        # Zero timeout: poll the tty and return at once whether or not a byte is
        # waiting, so the stream keeps flowing when no key has been pressed.
        ready, _, _ = _select.select([fd], [], [], 0)
        if not ready:
            return False
        return sys.stdin.read(1) in _STOP_KEYS

    try:
        tty.setcbreak(fd)
        yield pressed
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _draw(
    options: Sequence[str],
    index: int,
    *,
    previous_lines: int = 0,
) -> int:
    """Render the button row in place and return its physical line count.

    A long row can wrap across several terminal lines. Before repainting, clear
    every physical line occupied by the previous rendering; clearing only from
    the cursor to the end of its current line leaves wrapped copies behind.
    """
    plain_buttons = [f"[ {option} ]" for option in options]
    rendered_buttons = [
        f"{_INVERSE}{button}{_RESET}" if i == index else button
        for i, button in enumerate(plain_buttons)
    ]
    plain_row = " ".join(plain_buttons)
    rendered_row = " ".join(rendered_buttons)

    if previous_lines:
        # The cursor is at the end of the previous rendering. Clear its complete
        # wrapped block, then return to the block's first physical line.
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


def _read_key() -> str | None:
    """Read one logical keypress from the terminal.

    Returns ``"left"``/``"right"`` for normal CSI arrows, application-mode
    arrows, and modified CSI arrows. A complete but unsupported escape sequence
    returns :data:`_IGNORED` so the chooser keeps running instead of treating it
    as a bare Escape. Returns ``None`` only on end-of-input/Ctrl-D.
    """
    fd = sys.stdin.fileno()
    char = sys.stdin.read(1)

    if char in ("", _EOT):
        return None

    if char != _ESC:
        if char in ("h", "j"):
            return "left"
        if char in ("l", "k"):
            return "right"
        return char

    # A real bare Escape has no following byte. Arrow and other terminal keys
    # begin with Escape and then immediately provide the rest of the sequence.
    ready, _, _ = _select.select([fd], [], [], 0.05)
    if not ready:
        return _ESC

    prefix = sys.stdin.read(1)

    # Application cursor mode: ESC O A/B/C/D.
    if prefix == "O":
        ready, _, _ = _select.select([fd], [], [], 0.05)
        if not ready:
            return _IGNORED
        final = sys.stdin.read(1)
        return {
            "A": "left",
            "B": "right",
            "C": "right",
            "D": "left",
        }.get(final, _IGNORED)

    if prefix != "[":
        return _IGNORED

    # CSI sequences end with a final byte in the ASCII range @ through ~.
    # Reading the whole sequence also handles modified arrows such as
    # ESC [ 1 ; 2 D, which some Android keyboards emit.
    sequence = ""
    while len(sequence) < 64:
        ready, _, _ = _select.select([fd], [], [], 0.05)
        if not ready:
            return _IGNORED
        byte = sys.stdin.read(1)
        if byte == "":
            return None
        sequence += byte
        if "@" <= byte <= "~":
            break
    else:
        return _IGNORED

    final = sequence[-1]
    return {
        "A": "left",
        "B": "right",
        "C": "right",
        "D": "left",
    }.get(final, _IGNORED)

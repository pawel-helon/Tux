"""Terminal interaction primitives used by the CLI.

The package preserves the public surface of the former :mod:`tux.chooser`
module while separating menu selection, line editing, key decoding, rendering,
and stream interruption.
"""

from tux.chooser.keys import (
    BACKSPACE as _BACKSPACE,
    ENTER as _ENTER,
    EOT as _EOT,
    ESC as _ESC,
    IGNORED as _IGNORED,
    STOP_KEYS as _STOP_KEYS,
    read_key as _read_key,
)
from tux.chooser.line import read_line
from tux.chooser.menu import Chooser, select
from tux.chooser.rendering import draw as _draw
from tux.chooser.streaming import stop_watch

__all__ = ["Chooser", "read_line", "select", "stop_watch"]

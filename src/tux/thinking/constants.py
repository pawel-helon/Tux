"""Terminal control sequences and spinner defaults for the thinking indicator."""

_DIM = "\x1b[2m"
_RESET = "\x1b[0m"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_ERASE_TO_END = "\x1b[K"
_CLEAR_LINE = "\r\x1b[2K"
_GLYPHS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_LABEL = "tux is thinking"
_INTERVAL = 0.1

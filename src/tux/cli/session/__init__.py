"""Interactive CLI session helpers."""

from .interaction import interactive
from .plan import present_single_command

# Compatibility aliases used by the history command.
_interactive = interactive
_present_single_command = present_single_command

__all__ = ["interactive", "present_single_command"]

"""Public destructive-command inspection orchestration."""

from .parsing import segments, tokenise
from .rules import _FORK_BOMB_REASON, is_fork_bomb, segment_reason


def destructive_reason(command: str) -> str | None:
    """Return why a command is potentially destructive, or ``None``."""
    text = command.strip()
    if not text:
        return None
    if is_fork_bomb(text):
        return _FORK_BOMB_REASON
    for segment in segments(tokenise(text)):
        reason = segment_reason(segment)
        if reason is not None:
            return reason
    return None

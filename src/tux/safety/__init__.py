"""Static, local inspection of proposed commands for destructive patterns."""

from .inspection import destructive_reason
from .parsing import (
    _PRIVILEGE_COMMANDS,
    _SEPARATORS,
    _command_name,
    _has_flag,
    _segments,
    _strip_privilege_prefix,
    _tokenise,
    command_name,
    has_flag,
    segments,
    strip_privilege_prefix,
    tokenise,
)
from .rules import (
    _BLOCK_DEVICE,
    _BLOCK_DEVICE_REASON,
    _BROAD_PATH,
    _DD_REASON,
    _FORK_BOMB_REASON,
    _MKFS_REASON,
    _OWNERSHIP_COMMANDS,
    _OWNERSHIP_REASONS,
    _RECURSIVE_LONG,
    _RECURSIVE_SHORT,
    _RM_FLAGS_LONG,
    _RM_FLAGS_SHORT,
    _RM_REASON,
    _SHRED_REASON,
    _WIPEFS_REASON,
    _is_fork_bomb,
    _segment_reason,
    _writes_block_device,
    is_fork_bomb,
    segment_reason,
    writes_block_device,
)

__all__ = ["destructive_reason"]

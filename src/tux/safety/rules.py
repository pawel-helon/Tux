"""Destructive-command rules used by the safety inspector."""

import re

from .parsing import command_name, has_flag, strip_privilege_prefix

_RM_FLAGS_SHORT = frozenset({"r", "R", "f"})
_RM_FLAGS_LONG = frozenset({"--recursive", "--force", "--no-preserve-root"})
_RECURSIVE_SHORT = frozenset({"R"})
_RECURSIVE_LONG = frozenset({"--recursive"})
_OWNERSHIP_COMMANDS = frozenset({"chmod", "chown", "chgrp"})

_BLOCK_DEVICE = re.compile(r"^/dev/(sd[a-z]|nvme\d|hd[a-z]|vd[a-z]|mmcblk\d)")
_BROAD_PATH = re.compile(
    r"^(/|/\*|\*|~|/(bin|boot|etc|home|lib|opt|proc|root|sbin|sys|usr|var)/?|/sdcard/?|/storage/emulated/0/?|/data/data/com\.termux/files/?)$"
)

_RM_REASON = "recursively or forcibly deletes files and directories"
_DD_REASON = "writes raw data directly to a device, bypassing the filesystem"
_MKFS_REASON = "formats a filesystem, erasing any data already on the device"
_SHRED_REASON = "overwrites files to destroy their contents irrecoverably"
_WIPEFS_REASON = "erases the filesystem signature from a device"
_BLOCK_DEVICE_REASON = "writes straight to a raw disk device, overwriting whatever is on it"
_FORK_BOMB_REASON = "is a fork bomb that spawns processes until the system is starved"
_OWNERSHIP_REASONS = {
    "chmod": "recursively changes permissions across a broad system path",
    "chown": "recursively changes ownership across a broad system path",
    "chgrp": "recursively changes group ownership across a broad system path",
}


def is_fork_bomb(text: str) -> bool:
    """Return whether text contains the classic shell fork bomb."""
    return ":(){:|:&};:" in re.sub(r"\s+", "", text)


def segment_reason(segment: list[str]) -> str | None:
    """Return the destructive reason for one command segment."""
    if writes_block_device(segment):
        return _BLOCK_DEVICE_REASON
    body = strip_privilege_prefix(segment)
    if not body:
        return None
    name = command_name(body[0])
    args = body[1:]
    if name == "rm" and has_flag(args, _RM_FLAGS_SHORT, _RM_FLAGS_LONG):
        return _RM_REASON
    if name == "dd":
        return _DD_REASON
    if name.startswith("mkfs"):
        return _MKFS_REASON
    if name == "shred":
        return _SHRED_REASON
    if name == "wipefs":
        return _WIPEFS_REASON
    if (
        name in _OWNERSHIP_COMMANDS
        and has_flag(args, _RECURSIVE_SHORT, _RECURSIVE_LONG)
        and any(_BROAD_PATH.match(arg) for arg in args)
    ):
        return _OWNERSHIP_REASONS[name]
    return None


def writes_block_device(segment: list[str]) -> bool:
    """Return whether a segment redirects output onto a raw block device."""
    for index, token in enumerate(segment):
        if token in (">", ">>"):
            target = segment[index + 1] if index + 1 < len(segment) else ""
        elif token.startswith(">>"):
            target = token[2:]
        elif token.startswith(">"):
            target = token[1:]
        else:
            continue
        if _BLOCK_DEVICE.match(target):
            return True
    return False


_is_fork_bomb = is_fork_bomb
_segment_reason = segment_reason
_writes_block_device = writes_block_device

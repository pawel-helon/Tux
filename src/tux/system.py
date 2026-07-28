"""Linux environment profiles used to shape tux prompts and provisioning."""

from __future__ import annotations

import os

LINUX = "linux"
TERMUX = "termux"
SUPPORTED_SYSTEMS = (LINUX, TERMUX)


def detect_system() -> str:
    """Return the current supported Linux environment profile."""
    prefix = os.environ.get("PREFIX", "")
    if os.environ.get("TERMUX_VERSION") or prefix.startswith("/data/data/com.termux/"):
        return TERMUX
    return LINUX


def validate_system(value: str) -> str:
    """Return a normalized supported system name or raise ``ValueError``."""
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_SYSTEMS:
        allowed = ", ".join(SUPPORTED_SYSTEMS)
        raise ValueError(f"unknown system {value!r}; allowed systems are: {allowed}")
    return normalized


def command_context(system: str) -> str:
    if system == TERMUX:
        return (
            "The command runs locally in Termux on Android. Use pkg for Termux "
            "packages and $PREFIX for the Termux installation prefix. Do not assume "
            "sudo, systemd, systemctl, snap, a desktop session, root access, or "
            "conventional /usr paths. Android shared storage may require "
            "termux-setup-storage. Unless the user explicitly identifies a remote "
            "machine reached over SSH, generate commands for the local Termux shell."
        )
    return (
        "The command runs on a conventional Linux system. Do not assume a specific "
        "distribution, package manager, init system, or privilege tool when the user "
        "has not identified one; add a discovery step when that distinction matters."
    )


def chat_context(system: str) -> str:
    if system == TERMUX:
        return (
            "The user is working in Termux on Android unless they explicitly say they "
            "are connected to another Linux machine. Distinguish the phone from a "
            "remote SSH target. Use Termux concepts such as pkg, $PREFIX, Android "
            "storage permissions, and the absence of systemd or sudo when relevant."
        )
    return (
        "The user is working on Linux. Avoid assuming a particular distribution or "
        "service manager unless the conversation establishes it."
    )


def explain_context(system: str) -> str:
    if system == TERMUX:
        return (
            "Explain any Termux-specific choices, including pkg, $PREFIX, Android "
            "storage boundaries, and why conventional sudo/systemctl advice may not "
            "apply. Clearly distinguish local-phone commands from remote-host commands."
        )
    return (
        "Explain distribution-sensitive choices and identify assumptions about package "
        "management, privileges, paths, or services when they matter."
    )

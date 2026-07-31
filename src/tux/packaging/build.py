"""Invoke Debian package build tools."""

import subprocess
from collections.abc import Callable
from pathlib import Path

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def host_architecture(*, runner: Runner = subprocess.run) -> str:
    """Return the build host's Debian architecture."""
    result = runner(
        ["dpkg", "--print-architecture"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_deb(tree: Path, output: Path, *, runner: Runner = subprocess.run) -> Path:
    """Build a ``.deb`` from a laid-out tree and return ``output``."""
    runner(
        ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(output)],
        check=True,
    )
    return output

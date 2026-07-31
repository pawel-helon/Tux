"""Render Debian package metadata and filenames."""

import os
from datetime import datetime, timezone
from email.utils import format_datetime

from tux import __version__

from .constants import (
    DEPENDS,
    DESCRIPTION_BODY,
    MAINTAINER,
    PACKAGE_NAME,
    PRIORITY,
    RECOMMENDS,
    SECTION,
    SYNOPSIS,
)


def package_version() -> str:
    """Return the package version, derived from tux's single source of truth."""
    return __version__


def package_name(variant: str | None = None) -> str:
    """Return the Debian package name for a variant."""
    return PACKAGE_NAME if variant is None else f"{PACKAGE_NAME}-{variant}"


def changelog_filename(version: str) -> str:
    """Return the Debian changelog filename for ``version``."""
    return "changelog.Debian.gz" if "-" in version else "changelog.gz"


def changelog(
    *, version: str, date: str, distribution: str = "unstable", variant: str | None = None
) -> str:
    """Return a Debian changelog entry for ``version`` dated ``date``."""
    return (
        f"{package_name(variant)} ({version}) {distribution}; urgency=medium\n"
        "\n"
        "  * Package tux as a self-contained .deb that bundles its own Python\n"
        "    interpreter, so tux installs with no pre-existing Python toolchain.\n"
        "  * postinst provisions tux's local model interactively when run at a\n"
        "    terminal (tux asks its own consent questions directly); an\n"
        "    unattended install instead defers, or acts on preseeded debconf\n"
        "    consent.\n"
        "\n"
        f" -- {MAINTAINER}  {date}\n"
    )


def build_date() -> str:
    """Return the changelog build date as an RFC 2822 timestamp."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = (
        datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        if epoch
        else datetime.now(timezone.utc)
    )
    return format_datetime(moment)


def deb_filename(version: str, architecture: str, variant: str | None = None) -> str:
    """Return the conventional ``.deb`` filename."""
    return f"{package_name(variant)}_{version}_{architecture}.deb"


def control_file(
    *,
    version: str,
    architecture: str,
    installed_size: int | None = None,
    variant: str | None = None,
) -> str:
    """Return the ``DEBIAN/control`` contents."""
    lines = [
        f"Package: {package_name(variant)}",
        f"Version: {version}",
        f"Section: {SECTION}",
        f"Priority: {PRIORITY}",
        f"Architecture: {architecture}",
        f"Maintainer: {MAINTAINER}",
        f"Depends: {DEPENDS}",
        f"Recommends: {RECOMMENDS}",
    ]
    if installed_size is not None:
        lines.append(f"Installed-Size: {installed_size}")
    lines.append(f"Description: {SYNOPSIS}")
    lines.extend(f" {body}" for body in DESCRIPTION_BODY)
    return "\n".join(lines) + "\n"

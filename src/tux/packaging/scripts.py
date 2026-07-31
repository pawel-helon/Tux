"""Render Debian maintainer scripts."""

from .constants import POSTINST_TEMPLATE


def _provision_command(variant: str | None) -> str:
    """Return the unattended provisioning command for a variant."""
    if variant is None:
        return "tux provision --yes </dev/null"
    return f"tux provision --yes --variant {variant} </dev/null"


def _interactive_provision_command(variant: str | None) -> str:
    """Return the interactive provisioning command for a variant."""
    if variant is None:
        return "tux provision"
    return f"tux provision --variant {variant}"


def postinst(variant: str | None = None) -> str:
    """Return the ``postinst`` maintainer script for a variant."""
    return POSTINST_TEMPLATE.format(
        provision_command=_provision_command(variant),
        interactive_provision_command=_interactive_provision_command(variant),
    )

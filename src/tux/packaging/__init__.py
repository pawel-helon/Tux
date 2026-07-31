"""Debian package metadata, layout, and build helpers."""

from .build import Runner, build_deb, host_architecture
from .constants import (
    BINARY_NAME,
    CONFIG,
    COPYRIGHT,
    DEPENDS,
    DESCRIPTION_BODY,
    MAINTAINER,
    PACKAGE_NAME,
    POSTINST_TEMPLATE,
    POSTRM,
    PRIORITY,
    PROVISION_QUESTION,
    RECOMMENDS,
    SECTION,
    SYNOPSIS,
    TEMPLATES,
)
from .layout import _normalize_dir_perms, _write, _write_gz, lay_out_package
from .metadata import (
    build_date,
    changelog,
    changelog_filename,
    control_file,
    deb_filename,
    package_name,
    package_version,
)
from .scripts import (
    _interactive_provision_command,
    _provision_command,
    postinst,
)

__all__ = [
    "Runner", "PACKAGE_NAME", "BINARY_NAME", "MAINTAINER", "SECTION",
    "PRIORITY", "SYNOPSIS", "DESCRIPTION_BODY", "DEPENDS", "RECOMMENDS",
    "PROVISION_QUESTION", "POSTINST_TEMPLATE", "CONFIG", "TEMPLATES",
    "POSTRM", "COPYRIGHT", "package_version", "package_name", "postinst",
    "changelog_filename", "changelog", "build_date", "deb_filename",
    "control_file", "lay_out_package", "host_architecture", "build_deb",
]

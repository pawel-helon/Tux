"""Render the Debian package metadata and maintainer scripts for tux.

This module is the *testable* half of the ``.deb`` build: every artifact that
goes into the package — the ``control`` metadata, the debconf ``templates`` and
``config`` script, and the ``postinst`` / ``postrm`` maintainer scripts — is
produced here as a pure string, and :func:`lay_out_package` assembles them into a
``dpkg-deb``-ready tree around a pre-built, interpreter-bundling binary. The
heavy interpreter bundling and the final ``dpkg-deb --build`` run live in the
build script (``packaging/build_deb.py``); that build is the one step the offline
test suite does not run.

The package version is derived from :data:`tux.__version__` so the build never
hardcodes a version string. The maintainer scripts follow Debian practice for
consent: the ``postinst`` never installs the Ollama runtime or pulls a model
without it. Run at a real terminal, it lets ``tux provision`` ask its own two
consent questions directly, so a plain interactive ``dpkg -i`` finishes with a
working ``tux ask``; an unattended run (no TTY, or
``DEBIAN_FRONTEND=noninteractive``) never prompts on its own and only acts on
a debconf answer preseeded ahead of time, otherwise deferring everything to a
later ``tux provision`` run — it never hangs on a prompt. A plain ``remove``
drops only the package's own files; the user's per-user config and state and
the separately-installed Ollama runtime and its pulled models survive, and
even ``purge`` only clears the package's own debconf answers.
"""

import gzip
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from tux import __version__

#: A subprocess runner seam (mirrors :func:`subprocess.run`); injected in tests
#: so the build invocations run without a real ``dpkg`` / ``dpkg-deb``.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]

#: Base Debian package name and the ``.deb`` filename stem for the plain (8b)
#: package. A variant package suffixes it (see :func:`package_name`).
PACKAGE_NAME = "tux"

#: The installed command (and PyInstaller binary) name. The same for every
#: variant: lite and full are one codebase gated at runtime, so each variant
#: package still ships ``/usr/bin/tux``.
BINARY_NAME = "tux"

#: Package maintainer in Debian ``Name <email>`` form. A placeholder address on
#: the reserved ``example.com`` domain — replace before any public distribution.
MAINTAINER = "tux developers <dev@tux.example.com>"

#: Debian archive section and priority for a general-purpose user utility.
SECTION = "utils"
PRIORITY = "optional"

#: One-line ``Description`` synopsis (no trailing period, kept under 80 chars).
SYNOPSIS = "Local-first AI helper for working with your Linux system"

#: Extended ``Description`` body lines. ``dpkg`` indents each by one space; a lone
#: ``"."`` renders as a paragraph break.
DESCRIPTION_BODY = (
    "tux turns a plain-English question into the shell command that answers it,",
    "proposing the command for you to run rather than running it for you.",
    ".",
    "This package bundles its own Python interpreter, so tux installs and runs on",
    "a machine with no Python toolchain. Installing at a terminal walks you",
    "through detecting the Linux environment and setting up a local model sized",
    "to your hardware via Ollama; an unattended install defers that setup to a later \"tux provision\" run.",
)

#: Runtime dependencies. The PyInstaller-bundled executable links the system
#: libc; the maintainer scripts source debconf's ``confmodule`` and call
#: ``db_input`` / ``db_get``, so the package must depend on debconf — the
#: ``debconf-2.0`` alternative is the standard form dh_installdebconf emits and
#: keeps the package installable where cdebconf provides the interface.
DEPENDS = "libc6, debconf (>= 0.5) | debconf-2.0"

#: Soft dependency: provisioning's Ollama install fetches its script with curl.
RECOMMENDS = "curl"

#: debconf question key asked (at low priority) by the ``config`` script. Only
#: consulted for an *unattended* install (see :data:`POSTINST_TEMPLATE`) — an
#: interactive one never touches debconf at all, since ``tux provision`` asks
#: its own two consent questions directly at the terminal.
PROVISION_QUESTION = "tux/provision-now"

#: ``postinst`` template. An install attached to a real terminal (both stdin and
#: stdout are TTYs, and the frontend hasn't asked for silence) runs
#: ``{interactive_provision_command}`` directly: tux asks its own two consent
#: questions right there — first to install the Ollama runtime if it's missing,
#: then to pull the sized model — so a plain interactive ``dpkg -i`` finishes
#: with a working ``tux ask``. Anything else (no TTY, a pipe, or
#: ``DEBIAN_FRONTEND=noninteractive``) never prompts on its own: it only acts on
#: a debconf answer preseeded ahead of time (the low-priority escape hatch for
#: unattended/CI installs), running ``{provision_command}`` with consent already
#: recorded, and otherwise defers everything to a later ``tux provision`` run.
#: Neither branch ever installs or downloads anything without consent, and
#: neither ever hangs an unattended install on a prompt.
POSTINST_TEMPLATE = """\
#!/bin/sh
# Provision tux's local model. Debian practice: never hang an unattended
# install on a prompt, and never install the Ollama runtime or pull a model
# silently.
set -e

. /usr/share/debconf/confmodule

case "$1" in
    configure)
        if [ -t 0 ] && [ -t 1 ] && [ "$DEBIAN_FRONTEND" != "noninteractive" ]; then
            # A human is at the console: let tux ask its own two consent
            # questions (install Ollama, then pull a model) right here, so a
            # plain `dpkg -i` alone can finish with a working `tux ask`.
            if ! {interactive_provision_command}; then
                echo "tux: provisioning did not complete; run 'tux provision' later." >&2
            fi
        else
            # Unattended (no TTY, or DEBIAN_FRONTEND=noninteractive): never
            # prompt. Only proceed if consent was preseeded ahead of time.
            db_get tux/provision-now || RET=false
            if [ "$RET" = "true" ]; then
                # Consent was preseeded, so invoke 8a's provisioning brain with
                # it recorded (--yes), reading from /dev/null so this never
                # blocks on input.
                if ! {provision_command}; then
                    echo "tux: provisioning did not complete; run 'tux provision' later." >&2
                fi
            else
                # Lowest-risk path: defer the consent and setup to first run.
                echo "tux: installed. Run 'tux provision' to set up your local model." >&2
            fi
        fi
        ;;
esac

exit 0
"""

#: ``config``: ask the provision-now question at *low* priority so it is only
#: ever seen (or preseeded) by the unattended-install fallback in
#: :data:`POSTINST_TEMPLATE` — an interactive install never reaches it, since it
#: takes tux's own direct-prompt branch instead. Low priority also means an
#: unattended install with no preseed just takes the default (defer) and never
#: waits on a TTY of its own.
CONFIG = """\
#!/bin/sh
# Ask, at low priority, whether to provision now. Only reached by an
# unattended install (see postinst); low priority means one with no preseeded
# answer just takes the default (defer) and never waits on a TTY.
set -e

. /usr/share/debconf/confmodule

db_input low tux/provision-now || true
db_go || true

exit 0
"""

#: debconf ``templates``: the boolean provision-now question, defaulting to
#: defer. Only relevant to an unattended install preseeding consent ahead of
#: time; an interactive install is asked directly by ``tux provision`` instead.
TEMPLATES = """\
Template: tux/provision-now
Type: boolean
Default: false
Description: Provision tux's local model now?
 For an unattended install only (an interactive one is asked directly): tux
 can set up a local model sized to this machine's hardware at install time,
 installing the Ollama runtime (via its official install script) if it isn't
 already present, then pulling a model through it. The model download may be
 several gigabytes.
 .
 Decline to defer it: tux is still installed, and you can run "tux provision"
 yourself at any time.
"""

#: ``postrm``: on purge, clear only the package's debconf answers. The user's
#: per-user config/state and the Ollama runtime and models are left untouched.
POSTRM = """\
#!/bin/sh
# Clean removal. dpkg removes the package's own files; this script only clears
# the package's debconf answers on purge. tux's per-user config and state (under
# each user's XDG config dir) and the separately-installed Ollama runtime and its
# pulled models are deliberately left untouched.
set -e

case "$1" in
    purge)
        if [ -e /usr/share/debconf/confmodule ]; then
            . /usr/share/debconf/confmodule
            db_purge
        fi
        ;;
esac

exit 0
"""


#: ``usr/share/doc/tux/copyright``: a plain (non-DEP-5) copyright file, which
#: satisfies Debian's "every package ships a copyright file" rule (lintian's
#: ``no-copyright-file``) and carries an explicit copyright notice. It is kept
#: free-form deliberately — declaring a ``Format:`` header would invoke the
#: machine-readable DEP-5 structural checks for no benefit here.
COPYRIGHT = """\
tux
Upstream contact: tux developers <dev@tux.example.com>

Copyright (C) 2026 tux developers <dev@tux.example.com>

tux does not yet ship a published license file; it is distributed by the tux
developers. Contact the upstream maintainer above for licensing terms.

This package additionally bundles, via PyInstaller, an unmodified CPython
interpreter and its standard library, which are distributed under the Python
Software Foundation License Agreement: https://docs.python.org/3/license.html
"""


def package_version() -> str:
    """Return the package version, derived from tux's single source of truth."""
    return __version__


def package_name(variant: str | None = None) -> str:
    """Return the Debian package name for a variant.

    ``None`` is the base ``tux`` package (8b); a variant yields ``tux-<variant>``
    (e.g. ``tux-lite``) so the variants are distinct, separately-installable
    packages while each still ships the same ``/usr/bin/tux`` command.
    """
    return PACKAGE_NAME if variant is None else f"{PACKAGE_NAME}-{variant}"


def _provision_command(variant: str | None) -> str:
    """Return the unattended ``postinst`` ``tux provision`` invocation for a variant.

    Used only on the debconf-preseeded, unattended-install branch of
    :data:`POSTINST_TEMPLATE`. The base package provisions with hardware-probed
    tiering; a variant package pins its tier (``--variant``) so the install
    cannot be upgraded past the variant by the hardware probe. Either way the
    call reads ``</dev/null`` and passes ``--yes`` since consent was already
    preseeded, so an unattended install never blocks on input.
    """
    if variant is None:
        return "tux provision --yes </dev/null"
    return f"tux provision --yes --variant {variant} </dev/null"


def _interactive_provision_command(variant: str | None) -> str:
    """Return the interactive ``postinst`` ``tux provision`` invocation for a variant.

    Used on the TTY branch of :data:`POSTINST_TEMPLATE`: no ``--yes`` and no
    input redirection, so ``tux provision`` asks its own two consent questions
    (install Ollama, then pull the sized model) directly at the terminal a human
    is running ``dpkg -i`` from. A variant package still pins its tier via
    ``--variant`` so the probe cannot upgrade it past that tier.
    """
    if variant is None:
        return "tux provision"
    return f"tux provision --variant {variant}"


def postinst(variant: str | None = None) -> str:
    """Return the ``postinst`` maintainer script for a variant."""
    return POSTINST_TEMPLATE.format(
        provision_command=_provision_command(variant),
        interactive_provision_command=_interactive_provision_command(variant),
    )


def changelog_filename(version: str) -> str:
    """Return the Debian changelog filename for ``version``.

    A native package (a version with no ``-`` Debian revision, as tux's is)
    ships ``changelog.gz``; a non-native one ships ``changelog.Debian.gz``.
    lintian flags the wrong name for the package type, so derive it.
    """
    return "changelog.Debian.gz" if "-" in version else "changelog.gz"


def changelog(
    *, version: str, date: str, distribution: str = "unstable", variant: str | None = None
) -> str:
    """Return a Debian changelog entry for ``version`` dated ``date``.

    ``date`` must be an RFC 2822 timestamp (``date -R`` form); the trailer
    maintainer matches :data:`MAINTAINER` so the changelog and ``control`` agree.
    ``variant`` selects the package name in the header.
    """
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
    """Return the changelog build date as an RFC 2822 timestamp.

    Honours ``SOURCE_DATE_EPOCH`` when set so a build can be made reproducible;
    otherwise uses the current UTC time.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = (
        datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        if epoch
        else datetime.now(timezone.utc)
    )
    return format_datetime(moment)


def deb_filename(version: str, architecture: str, variant: str | None = None) -> str:
    """Return the conventional ``.deb`` filename for a version and architecture."""
    return f"{package_name(variant)}_{version}_{architecture}.deb"


def control_file(
    *,
    version: str,
    architecture: str,
    installed_size: int | None = None,
    variant: str | None = None,
) -> str:
    """Return the ``DEBIAN/control`` contents for a version and architecture.

    ``installed_size`` (in KiB, as Debian expects) is included only when given so
    the field can be computed from the real binary at lay-out time and omitted in
    pure metadata tests. ``variant`` selects the package name (see
    :func:`package_name`); the rest of the metadata is shared across variants.
    """
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


def lay_out_package(
    dest: Path,
    binary: Path,
    *,
    version: str,
    architecture: str,
    date: str | None = None,
    variant: str | None = None,
) -> Path:
    """Assemble a ``dpkg-deb``-ready tree at ``dest`` around the bundled ``binary``.

    Writes the package's installed payload — the interpreter-bundling executable
    at ``/usr/bin/tux`` and the Debian documentation (``copyright`` and a
    gzipped ``changelog``) under ``/usr/share/doc/<package>`` — and its ``DEBIAN``
    control area: the ``control`` metadata (with the binary's installed size),
    the debconf ``templates`` and ``config`` script, and the ``postinst`` /
    ``postrm`` maintainer scripts. The maintainer scripts and the installed
    binary are made executable; every packaged directory is forced to 0755 so a
    group-writable build umask does not leave lintian-flagged 0775 dirs.
    ``variant`` selects the package name, doc directory, and the variant-pinning
    ``postinst`` provisioning call; the installed command stays ``/usr/bin/tux``.
    ``date`` defaults to :func:`build_date`. Returns ``dest`` for chaining.
    """
    debian_dir = dest / "DEBIAN"
    bin_dir = dest / "usr" / "bin"
    doc_dir = dest / "usr" / "share" / "doc" / package_name(variant)
    for directory in (debian_dir, bin_dir, doc_dir):
        directory.mkdir(parents=True, exist_ok=True)

    installed_binary = bin_dir / BINARY_NAME
    shutil.copy2(binary, installed_binary)
    installed_binary.chmod(0o755)

    installed_size = max(1, installed_binary.stat().st_size // 1024)
    _write(
        debian_dir / "control",
        control_file(
            version=version,
            architecture=architecture,
            installed_size=installed_size,
            variant=variant,
        ),
        0o644,
    )
    _write(debian_dir / "templates", TEMPLATES, 0o644)
    _write(debian_dir / "config", CONFIG, 0o755)
    _write(debian_dir / "postinst", postinst(variant), 0o755)
    _write(debian_dir / "postrm", POSTRM, 0o755)

    _write(doc_dir / "copyright", COPYRIGHT, 0o644)
    _write_gz(
        doc_dir / changelog_filename(version),
        changelog(version=version, date=date or build_date(), variant=variant),
        0o644,
    )

    _normalize_dir_perms(dest)
    return dest


def host_architecture(*, runner: Runner = subprocess.run) -> str:
    """Return the build host's Debian architecture via ``dpkg --print-architecture``."""
    result = runner(
        ["dpkg", "--print-architecture"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_deb(tree: Path, output: Path, *, runner: Runner = subprocess.run) -> Path:
    """Build a ``.deb`` from a laid-out ``tree`` via ``dpkg-deb``; return ``output``.

    ``--root-owner-group`` forces root ownership of the packaged files so a
    non-root, reproducible build does not embed the builder's uid/gid (which
    ``lintian`` flags). The ``dpkg-deb`` call is injectable so the build wiring is
    exercised offline without producing a real archive.
    """
    runner(
        ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(output)],
        check=True,
    )
    return output


def _write(path: Path, content: str, mode: int) -> None:
    """Write ``content`` to ``path`` as UTF-8 and set its permission ``mode``."""
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _write_gz(path: Path, content: str, mode: int) -> None:
    """Write ``content`` gzip-compressed to ``path`` and set permission ``mode``.

    Uses maximum compression with a zeroed mtime so the changelog meets lintian's
    ``changelog-not-compressed-with-max-compression`` bar and stays reproducible.
    """
    path.write_bytes(gzip.compress(content.encode("utf-8"), compresslevel=9, mtime=0))
    path.chmod(mode)


def _normalize_dir_perms(dest: Path) -> None:
    """Force every directory in the package tree to 0755.

    ``dpkg-deb`` packages directories with their on-disk mode; a group-writable
    build umask yields 0775, which lintian flags as ``non-standard-dir-perm``.
    """
    for directory in (dest, *dest.rglob("*")):
        if directory.is_dir():
            directory.chmod(0o755)

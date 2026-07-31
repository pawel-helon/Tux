"""Shared Debian package metadata constants."""

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
            # Unattended (no TTY, or DEBIAN_FRONTEND=noninteractive): provision
            # without prompting. --yes records consent, and /dev/null guarantees
            # the command cannot block waiting for input.
            if ! {provision_command}; then
                echo "tux: automatic provisioning failed; run 'tux provision --yes' later." >&2
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

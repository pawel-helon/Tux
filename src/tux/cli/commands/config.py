"""Implementation of the ``tux config`` command."""

import argparse
import sys

from tux.client import DEFAULTS
from tux.config import ConfigError, config_path, resolved_settings, set_value

def run_config(args: argparse.Namespace) -> int:
    """Dispatch a ``tux config`` action and report the result.

    Args:
        args: Parsed arguments carrying ``config_command`` and, for ``set``, the
            ``key`` and ``value`` to persist.

    Returns:
        ``0`` on success, ``1`` if the config file is malformed or the key is
        rejected.
    """
    if args.config_command == "show":
        return _config_show()
    if args.config_command == "set":
        return _config_set(args.key, args.value)
    # ``path`` is the only remaining action; the parser rejects anything else.
    print(config_path())
    return 0

def _config_show() -> int:
    """Print each effective setting with whether it came from the file or default."""
    try:
        settings = resolved_settings(DEFAULTS)
    except ConfigError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1
    for key, value, source in settings:
        print(f"{key} = {value}  ({source})")
    return 0

def _config_set(key: str, value: str) -> int:
    """Persist ``key = value`` to the config file, reporting any rejection."""
    try:
        set_value(key, value)
    except ConfigError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1
    return 0


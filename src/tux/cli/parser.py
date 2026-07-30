"""Argument parser construction for the ``tux`` command."""

import argparse

from tux import __version__
from tux.config import ALLOWED_KEYS, config_path

DESCRIPTION = (
    "A terminal-native Linux assistant that proposes commands in plain "
    "English; you decide whether to run them."
)

EXAMPLE = """\
example:
  Ask tux in plain English what you want to do, and it suggests the command:

    you:  how do I see which processes are using the most memory?
    tux:  ps aux --sort=-%mem | head -10
          (lists the top ten processes ranked by memory usage)

tux proposes the command; you decide whether to run it.\
"""

ASK_DESCRIPTION = "Ask tux a plain-English question about working with your system."
CONFIG_DESCRIPTION = (
    "Inspect and change tux's endpoint, model, capability variant, and Linux environment."
)
CONFIG_HELP = f"{CONFIG_DESCRIPTION} Run `config --help` for more."
PROVISION_DESCRIPTION = (
    "Detect this Linux environment, assess the machine's hardware, ensure the "
    "Ollama runtime, pull a suitable model, and write tux's config."
)
HISTORY_DESCRIPTION = (
    "List the commands tux has run, re-run one by its number, or clear the log."
)
HISTORY_HELP = f"{HISTORY_DESCRIPTION} Run `history --help` for more."
HISTORY_LONG_DESCRIPTION = (
    f"{HISTORY_DESCRIPTION}\n\n"
    "With no argument it lists the runs recorded in tux's run log, oldest first, "
    "each numbered with the exact command and its one-line description. Give a "
    "number (optionally '!'-prefixed, e.g. 3 or '!3') to re-run that recorded "
    "command: it is re-staged through tux's normal propose/run path — the command "
    "is shown with any destructive warning and you choose run or dismiss, so "
    "nothing runs until you say so. Use --clear to empty the log."
)

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``tux`` command."""
    parser = argparse.ArgumentParser(
        prog="tux",
        description=DESCRIPTION,
        epilog=EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tux {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    ask_parser = subparsers.add_parser(
        "ask",
        help=ASK_DESCRIPTION,
        description=ASK_DESCRIPTION,
    )
    ask_parser.add_argument(
        "question",
        nargs="?",
        help="The plain-English question to ask tux. Omit it to start an "
        "interactive session where you can ask follow-up questions.",
    )
    ask_parser.add_argument(
        "--new",
        action="store_true",
        help="Start a fresh conversation in this terminal, discarding any prior "
        "context from earlier questions in this shell.",
    )
    _add_config_parser(subparsers)
    _add_provision_parser(subparsers)
    _add_history_parser(subparsers)
    return parser

def _config_description() -> str:
    """Return the ``config`` subcommand description, noting where the file lives."""
    return f"{CONFIG_DESCRIPTION}\n\nThe config file lives at {config_path()}."

def _add_config_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``config`` subcommand with its ``show`` / ``set`` / ``path`` actions."""
    config_parser = subparsers.add_parser(
        "config",
        help=CONFIG_HELP,
        description=_config_description(),
        epilog=(
            "settings:\n"
            "  endpoint  OpenAI-compatible model-server base URL\n"
            "  model     Model name sent to the server\n"
            "  variant   Capability tier: lite, mid, or full\n"
            "  system    Linux environment: linux or termux\n\n"
            "examples:\n"
            "  tux config set model qwen2.5-coder:3b\n"
            "  tux config set system termux"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = config_parser.add_subparsers(
        dest="config_command", metavar="action", required=True
    )
    actions.add_parser(
        "show",
        help="Show every effective setting and where it comes from.",
        description="Show every effective setting and where it comes from.",
    )
    actions.add_parser(
        "path",
        help="Print the path tux uses for its config file.",
        description="Print the path tux uses for its config file.",
    )
    set_parser = actions.add_parser(
        "set",
        help="Set a config value, creating the config file if needed.",
        description="Set a config value, creating the config file if needed.",
    )
    set_parser.add_argument("key", choices=ALLOWED_KEYS, help="The config key to set.")
    set_parser.add_argument("value", help="The value to store for the key.")

def _add_provision_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``provision`` subcommand for the guided, re-runnable install."""
    provision_parser = subparsers.add_parser(
        "provision",
        help=PROVISION_DESCRIPTION,
        description=PROVISION_DESCRIPTION,
    )
    provision_parser.add_argument(
        "--yes",
        action="store_true",
        help="Treat runtime-install and model-download consent as already granted; "
        "do not prompt. Use for an unattended install with consent preseeded.",
    )
    provision_parser.add_argument(
        "--variant",
        choices=("lite", "mid", "full"),
        help="Pin the tier instead of probing hardware, forcing any of the three "
        "tiers (lite/mid/full) against the host and writing it to config, so a "
        "human can override what the probe would otherwise pick.",
    )

def _add_history_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``history`` subcommand for listing, re-running, and clearing runs."""
    history_parser = subparsers.add_parser(
        "history",
        help=HISTORY_HELP,
        description=HISTORY_LONG_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    history_parser.add_argument(
        "entry",
        nargs="?",
        help="Re-run the recorded command with this number, as shown by `tux "
        "history`. A leading '!' is accepted (e.g. 3 or '!3'); quote the '!' form "
        "so your shell does not expand it. The command is re-staged through the "
        "normal propose/run path — nothing runs until you choose run.",
    )
    history_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        metavar="N",
        help="When listing, show only the most recent N runs instead of all.",
    )
    history_parser.add_argument(
        "--clear",
        action="store_true",
        help="Empty the run log, discarding every recorded run.",
    )


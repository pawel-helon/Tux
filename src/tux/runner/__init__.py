"""Execute staged commands and maintain their bounded run history.

This package preserves the original :mod:`tux.runner` public API while keeping
subprocess execution, record serialization, and persistent log storage separate.
"""

from .execution import MAX_CAPTURED_CHARS, CommandRunner, run_command
from .log import MAX_LOG_BYTES, append_run, clear_runs, read_runs
from .records import NO_DESCRIPTION, RunRecord, format_run, parse_run

__all__ = [
    "MAX_CAPTURED_CHARS",
    "MAX_LOG_BYTES",
    "NO_DESCRIPTION",
    "CommandRunner",
    "RunRecord",
    "append_run",
    "clear_runs",
    "format_run",
    "parse_run",
    "read_runs",
    "run_command",
]

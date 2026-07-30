"""Shell-command execution with live output and bounded capture."""

import subprocess
import sys
from collections.abc import Callable

#: Upper bound on captured output characters. The capture exists to feed the
#: model and is bounded so a large output cannot blow the model context.
MAX_CAPTURED_CHARS = 4000

#: A command runner executes a shell command and returns ``(status, output)``.
CommandRunner = Callable[[str], tuple[int, str]]


def run_command(command: str) -> tuple[int, str]:
    """Run ``command`` in a subshell, teeing output, and return its result."""
    captured: list[str] = []
    remaining = MAX_CAPTURED_CHARS
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    stream = process.stdout
    if stream is not None:
        for line in stream:
            sys.stdout.write(line)
            sys.stdout.flush()
            if remaining > 0:
                kept = line[:remaining]
                captured.append(kept)
                remaining -= len(kept)
    status = process.wait()
    return status, "".join(captured)

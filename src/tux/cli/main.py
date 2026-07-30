"""Top-level command dispatcher for the ``tux`` console command."""

from __future__ import annotations

from collections.abc import Callable

from tux.chooser import Chooser, select
from tux.client import ModelClient
from tux.runner import CommandRunner, run_command

from .commands import run_config, run_history, run_provision
from .parser import build_parser
from .session.main import (
    ClarifyReader,
    EditReader,
    _default_edit_reader,
    _default_reader,
    _interactive,
    run_ask,
    run_session,
)


def main(
    argv: list[str] | None = None,
    client: ModelClient | None = None,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = _default_reader,
    editor: EditReader = _default_edit_reader,
) -> int:
    """Run the ``tux`` command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ask":
        if args.question is None:
            return run_session(client, runner, chooser, reader, editor)
        return run_ask(
            args.question,
            client,
            new=args.new,
            runner=runner,
            chooser=chooser,
            reader=reader,
            editor=editor,
        )
    if args.command == "config":
        return run_config(args)
    if args.command == "provision":
        return run_provision(args, interactive=_interactive)
    if args.command == "history":
        return run_history(args, runner=runner, chooser=chooser)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

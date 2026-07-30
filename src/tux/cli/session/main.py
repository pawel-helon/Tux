"""One-shot and interactive conversation orchestration."""

import os
import subprocess
import sys

from tux.chooser import Chooser, select
from tux.client import DEFAULT_VARIANT, ModelClient, ModelClientError
from tux.config import ConfigError, load_config
from tux.modes.command import assistant_turn
from tux.provisioning.main import managed_local_runtime
from tux.runner import CommandRunner, run_command
from tux.state import clear_thread, load_thread, save_thread
from tux.thinking import thinking
from tux.cli.session.interaction import (
    ClarifyReader,
    EditReader,
    default_edit_reader,
    default_reader,
    interactive,
)
from tux.cli.session.plan import present_command, present_single_command
from tux.cli.session.streaming import stream_reply

SESSION_PROMPT = "you: "
SESSION_INTRO = (
    "tux interactive session. Ask a question, then ask follow-ups in context.\n"
    "Press Ctrl-D or type 'exit' to quit."
)
EXIT_WORDS = frozenset({"exit", "quit"})
LITE_VARIANT = "lite"
FEATURES_ALL_ON = True
LITE_STEER = (
    "tux works best when you ask it for a command — for example: "
    'tux ask "how do I find the largest files in this folder?"'
)

# Compatibility aliases retained for callers that imported session internals.
_default_reader = default_reader
_default_edit_reader = default_edit_reader
_interactive = interactive
_present_single_command = present_single_command
_stream_reply = stream_reply
_present_command = present_command


def _lite_active(variant: str) -> bool:
    """Return whether lite lookup-only behavior is active."""
    if FEATURES_ALL_ON:
        return False
    return variant == LITE_VARIANT


def _resolve_variant() -> str:
    """Return the configured variant, falling back to the built-in default."""
    return load_config().get("variant", DEFAULT_VARIANT)


def run_ask(
    question: str,
    client: ModelClient | None = None,
    *,
    new: bool = False,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = default_reader,
    editor: EditReader = default_edit_reader,
) -> int:
    """Answer one ``tux ask`` turn, carrying context across invocations."""
    if client is None:
        try:
            with managed_local_runtime():
                return run_ask(
                    question,
                    ModelClient.from_config(),
                    new=new,
                    runner=runner,
                    chooser=chooser,
                    reader=reader,
                    editor=editor,
                )
        except (ConfigError, OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"tux: {exc}", file=sys.stderr)
            return 1
    try:
        variant = _resolve_variant()
    except ConfigError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1
    ppid = os.getppid()
    if new:
        clear_thread(ppid)
        history: list[dict[str, str]] = []
    else:
        history = load_thread(ppid)
    try:
        status, assistant = _answer_turn(
            client, question, history, runner, chooser, reader, editor, variant
        )
    except ModelClientError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1
    save_thread(ppid, [*history, {"role": "user", "content": question}, assistant])
    return status


def _answer_turn(
    client: ModelClient,
    question: str,
    history: list[dict[str, str]],
    runner: CommandRunner,
    chooser: Chooser,
    reader: ClarifyReader,
    editor: EditReader,
    variant: str,
) -> tuple[int, dict[str, str]]:
    """Route, present, and return one assistant turn."""
    lite = _lite_active(variant)
    with thinking():
        route = client.classify(question, history)
    if route == "command":
        with thinking():
            plan = client.suggest(question, history)
        status, final_plan = present_command(
            client,
            question,
            history,
            plan,
            runner,
            chooser,
            reader,
            editor,
            lite=lite,
        )
        return status, assistant_turn(final_plan)
    answer = stream_reply(client.converse_stream(question, history))
    if lite:
        print(f"\n{LITE_STEER}")
    return 0, {"role": "assistant", "content": answer}


def run_session(
    client: ModelClient | None = None,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = default_reader,
    editor: EditReader = default_edit_reader,
) -> int:
    """Run an interactive, multi-turn conversation in memory."""
    if client is None:
        try:
            with managed_local_runtime():
                return run_session(
                    ModelClient.from_config(), runner, chooser, reader, editor
                )
        except (ConfigError, OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"tux: {exc}", file=sys.stderr)
            return 1
    try:
        lite = _lite_active(_resolve_variant())
    except ConfigError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1
    print(SESSION_INTRO)
    history: list[dict[str, str]] = []
    while True:
        try:
            line = input(SESSION_PROMPT)
        except EOFError:
            print()
            return 0
        question = line.strip()
        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            return 0
        try:
            _, assistant = _answer_turn(
                client,
                question,
                history,
                runner,
                chooser,
                reader,
                editor,
                LITE_VARIANT if lite else DEFAULT_VARIANT,
            )
        except ModelClientError as exc:
            print(f"tux: {exc}", file=sys.stderr)
            continue
        history.append({"role": "user", "content": question})
        history.append(assistant)

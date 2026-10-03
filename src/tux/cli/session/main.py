"""One-shot and interactive conversation orchestration."""

import subprocess
import sys

from tux.chooser import Chooser, select
from tux.client import DEFAULT_VARIANT, ModelClient, ModelClientError
from tux.config import ConfigError, load_config
from tux.modes.command import assistant_turn
from tux.provisioning import managed_local_runtime
from tux.runner import CommandRunner, run_command
from tux.thinking import thinking
from tux.cli.session.interaction import (
    ClarifyReader,
    EditReader,
    default_edit_reader,
    default_reader,
)
from tux.cli.session.plan import present_command
from tux.cli.session.streaming import stream_reply
from tux.cli.session.state import Session
from tux.state.short_term_memory import (
    references_recent_session,
    retrieve,
    retrieved_context,
    save_session,
)
from tux.state.threads import historical_context, persist_session, retrieve_long_term

SESSION_PROMPT = "you: "
SESSION_INTRO = (
    "tux interactive session. Ask a question, then ask follow-ups in context.\n"
    "Type 'exit' to quit."
)
EXIT_WORDS = frozenset({"exit"})
LITE_VARIANT = "lite"
FEATURES_ALL_ON = True
LITE_STEER = (
    "tux works best when you ask it for a command — for example: "
    'tux ask "how do I find the largest files in this folder?"'
)

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
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = default_reader,
    editor: EditReader = default_edit_reader,
) -> int:
    """Answer one question in a fresh Tux session."""
    if client is None:
        try:
            with managed_local_runtime():
                return run_ask(
                    question,
                    ModelClient.from_config(),
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

    session = Session()

    try:
        status, assistant = _answer_turn(
            client,
            question,
            session.history,
            runner,
            chooser,
            reader,
            editor,
            variant,
        )
    except ModelClientError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1

    session.add_turn(question, assistant)
    save_session(session)
    _persist_completed_session(client, session)
    return status


def _persist_completed_session(client: ModelClient, session: Session) -> None:
    """Finalize long-term memory without making it a requirement for Tux."""
    if not session.history:
        return
    try:
        title, summary = client.summarize_conversation(session.history)
        persist_session(session, title, summary)
    except Exception as exc:
        print(f"tux: could not save long-term memory: {exc}", file=sys.stderr)


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
    model_history = history
    memory_route = route.startswith("memory_")
    if memory_route or references_recent_session(question):
        short_term = retrieve(question)
        memory_context = retrieved_context(short_term)
        if memory_context is None:
            try:
                memory_context = historical_context(retrieve_long_term(question))
            except Exception as exc:
                # Historical recall is optional; keep normal answering available.
                print(f"tux: long-term memory unavailable: {exc}", file=sys.stderr)
        if memory_context is not None:
            model_history = [memory_context, *history]
        route = route.removeprefix("memory_")

    if route == "command":
        with thinking():
            plan = client.suggest(question, model_history)

        status, final_plan = present_command(
            client,
            question,
            model_history,
            plan,
            runner,
            chooser,
            reader,
            editor,
            lite=lite,
        )

        return status, assistant_turn(final_plan)

    answer = stream_reply(client.converse_stream(question, model_history))

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
                    ModelClient.from_config(),
                    runner,
                    chooser,
                    reader,
                    editor,
                )
        except (ConfigError, OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"tux: {exc}", file=sys.stderr)
            return 1

    try:
        lite = _lite_active(_resolve_variant())
    except ConfigError as exc:
        print(f"tux: {exc}", file=sys.stderr)
        return 1

    session = Session()
    print(SESSION_INTRO)

    while True:
        try:
            line = input(SESSION_PROMPT)
        except EOFError:
            print()
            save_session(session)
            _persist_completed_session(client, session)
            return 0

        question = line.strip()

        if not question:
            continue

        if question.lower() in EXIT_WORDS:
            save_session(session)
            _persist_completed_session(client, session)
            return 0

        try:
            _, assistant = _answer_turn(
                client,
                question,
                session.history,
                runner,
                chooser,
                reader,
                editor,
                LITE_VARIANT if lite else DEFAULT_VARIANT,
            )
        except ModelClientError as exc:
            print(f"tux: {exc}", file=sys.stderr)
            continue

        session.add_turn(question, assistant)
        save_session(session)

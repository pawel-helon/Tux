"""Command-line entry point for the ``tux`` console command."""

import argparse
import os
import readline
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import replace
from contextlib import nullcontext

from tux import __version__
from tux.client import DEFAULT_VARIANT, DEFAULTS, ModelClient, ModelClientError
from tux.modes.chat import explain_request
from tux.modes.command import CommandSuggestion, Plan, assistant_turn, output_message
from tux.chooser import Chooser, read_line, select, stop_watch
from tux.config import (
    ALLOWED_KEYS,
    ConfigError,
    config_path,
    load_config,
    resolved_settings,
    set_value,
)
from tux.provisioning.main import ProvisionResult, managed_local_runtime, provision
from tux.runner import (
    CommandRunner,
    RunRecord,
    append_run,
    clear_runs,
    read_runs,
    run_command,
)
from tux.safety import destructive_reason
from tux.state import clear_thread, load_thread, save_thread
from tux.thinking import thinking

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

#: Prompt shown before each interactive turn.
SESSION_PROMPT = "you: "

#: One-line intro printed when the interactive session starts.
SESSION_INTRO = (
    "tux interactive session. Ask a question, then ask follow-ups in context.\n"
    "Press Ctrl-D or type 'exit' to quit."
)

#: Inputs that end the interactive session, matched case-insensitively.
EXIT_WORDS = frozenset({"exit", "quit"})

#: Per-step choices shown on the active step of a walked plan. Dismiss is listed
#: first so it is both the highlighted default and the fallback on any abort
#: (Ctrl-D, Escape, interrupt), keeping the safe choice the default; clarify
#: lets the user re-plan the remaining steps with a free-text question; edit opens
#: the active step's command for an inline tweak and then runs the edited text;
#: explain opens a pure-teaching Q&A loop about the step and runs nothing.
RUN_CHOICES = ("Dismiss", "Run", "Clarify", "Edit", "Explain")

#: Index in :data:`RUN_CHOICES` that abandons the rest of the plan.
DISMISS_CHOICE = 0

#: Index in :data:`RUN_CHOICES` that means run the active step's command.
RUN_CHOICE = 1

#: Index in :data:`RUN_CHOICES` that re-plans the remaining steps from free text.
CLARIFY_CHOICE = 2

#: Index in :data:`RUN_CHOICES` that opens the active step's command for an inline
#: edit and runs the edited text directly (no further run/dismiss confirmation).
EDIT_CHOICE = 3

#: Index in :data:`RUN_CHOICES` that opens the explain Q&A loop about the active
#: step. Explaining is pure teaching: it runs nothing and leaves the plan unchanged.
EXPLAIN_CHOICE = 4

#: Prompt shown when the user chooses clarify and tux reads their question.
CLARIFY_PROMPT = "clarify: "

#: Prompt shown in the explain loop when tux reads a free-text follow-up question.
#: A blank line, an Escape, or end-of-input here leaves the loop and returns to
#: the menu, the proposal's conversation thread untouched.
EXPLAIN_PROMPT = "ask: "

#: Prompt shown on the inline edit input line, which is pre-filled with the
#: currently proposed command so the user modifies it rather than retyping it.
EDIT_PROMPT = "edit: "

#: Variant name that engages lite gating. Any other state — ``full``, ``mid``,
#: unset, or a user-supplied endpoint with no variant (8a's escape hatch) — leaves
#: today's full behavior unchanged; lite gating engages only on an explicit match
#: here.
LITE_VARIANT = "lite"

#: Master features-all-on switch. While ``True`` (the default for the hypervisor
#: A/B round) every feature surface runs regardless of variant: a command turn
#: always gets the full stepwise walk + clarify/re-plan and a conversational turn
#: gets no steer, **even when** ``variant == "lite"``. Item 8c's lite lookup-only
#: gating below is retained but dormant behind this switch — flip to ``False`` to
#: restore lite's single-command / steer behavior with no re-implementation.
FEATURES_ALL_ON = True


def _lite_active(variant: str) -> bool:
    """Return whether item 8c's lite lookup-only gating engages for ``variant``.

    Lite engages only on an explicit ``variant == LITE_VARIANT`` **and** only while
    :data:`FEATURES_ALL_ON` is off. With the switch on (the A/B default) this is
    always ``False``, so every surface runs at full regardless of variant, leaving
    the downstream 8c gating intact but dormant. This is the single resolution
    point the switch flips; nothing downstream changes.
    """
    if FEATURES_ALL_ON:
        return False
    return variant == LITE_VARIANT

#: Per-turn choices on a lite command proposal. Lite shows a single command with
#: no clarify/re-plan, so the menu is the safe-run floor plus edit and explain:
#: dismiss (the highlighted default and abort fallback), run, edit — lite's only
#: lever for adjusting the single proposed command — and explain, the pure-teaching
#: Q&A loop. ``RUN_CHOICE``/``DISMISS_CHOICE`` index into it identically to
#: :data:`RUN_CHOICES`.
LITE_RUN_CHOICES = ("Dismiss", "Run", "Edit", "Explain")

#: Index in :data:`LITE_RUN_CHOICES` that opens the proposed command for an inline
#: edit. Lite carries no clarify, so edit sits at index 2 rather than 3.
LITE_EDIT_CHOICE = 2

#: Index in :data:`LITE_RUN_CHOICES` that opens the explain Q&A loop about the
#: proposed command. Explaining is pure teaching: it runs nothing and leaves the
#: proposal unchanged.
LITE_EXPLAIN_CHOICE = 3

#: Deterministic, tux-authored line appended after a lite conversational reply,
#: steering the user back toward command lookup with a concrete example request.
#: Kept here (not model-generated) so it is testable; plain text, not TTY-gated.
LITE_STEER = (
    "tux works best when you ask it for a command — for example: "
    'tux ask "how do I find the largest files in this folder?"'
)

#: ANSI styling for the interactive, framed proposal block. Emitted only when
#: interactive; the non-TTY fallback renders the same fields as plain text with
#: no escape sequences. The title, the command, and the description each get a
#: visually distinct style, and the dim label prefixes set the two labelled lines
#: apart from the bare title.
_RESET = "\x1b[0m"
_TITLE_STYLE = "\x1b[1;33m"  # bold yellow
_LABEL_STYLE = "\x1b[2m"  # dim
_COMMAND_STYLE = "\x1b[1;36m"  # bold cyan
_WARNING_STYLE = "\x1b[1;31m"  # bold red

#: Prefix on the destructive-command warning, shared by the styled and plain
#: branches so the same warning text reaches a terminal user and a log/script.
_WARNING_PREFIX = "potentially destructive"

#: Character repeated to form the horizontal rules that frame the proposal.
_RULE_CHAR = "─"

#: A clarify reader reads one line of free text (given a prompt) so the user can
#: re-plan the remaining steps. It mirrors the run-session ``input(...)`` seam and
#: is injected in tests so the clarify path runs without a real terminal. A blank
#: result (an empty line, or an Escape/Ctrl-D at the terminal) signals back-out.
ClarifyReader = Callable[[str], str]


def _default_reader(prompt: str) -> str:
    """Read one line of free text from stdin (the live default).

    Shared by the clarify prompt and the explain follow-up prompt: both read one
    line given a prompt, so both reuse the :data:`ClarifyReader` seam and this
    default. At a terminal the line is read through :func:`read_line`, so a bare
    Escape or a Ctrl-D backs out (returning a blank line the caller treats as a
    no-op); a piped session falls back to ``input`` and its EOF. Tests inject a
    fake to drive either loop without a real terminal.
    """
    if _interactive():
        return read_line(prompt)
    return input(prompt)


#: An explainer runs the interactive "why this command" loop for one proposal and
#: returns nothing — it teaches, running and changing nothing. The caller binds the
#: model client, the turn's running context, and the follow-up reader into it, so a
#: menu surface only has to hand it the active proposal. It is ``None`` on surfaces
#: that carry no model context (e.g. a history re-run), where explain is not offered.
ExplainRunner = Callable[[CommandSuggestion], None]


#: An edit reader is given the currently proposed command and returns the user's
#: edited command text. It mirrors the :data:`ClarifyReader` seam and is injected
#: in tests so the edit path runs without a real terminal; the live default opens
#: the line pre-filled with the current command. A blank/whitespace result (an
#: empty line, or an Escape/Ctrl-D at the terminal) means cancel — nothing runs.
EditReader = Callable[[str], str]


def _default_edit_reader(command: str) -> str:
    """Read an edited command from a line pre-filled with ``command``.

    At a terminal the line is read through :func:`read_line`, seeded with
    ``command`` so the user modifies the existing text rather than retyping it.
    Reading in cbreak mode is what lets a bare Escape or a Ctrl-D back out even
    while the pre-filled command still fills the line — ``readline`` would ring the
    bell at a Ctrl-D on a non-empty line, leaving no clean way out. A piped session
    falls back to a ``readline`` pre-filled ``input``; the startup hook is cleared
    in ``finally`` so it never bleeds into a later ``input`` call.
    """
    if _interactive():
        return read_line(EDIT_PROMPT, prefill=command)
    readline.set_startup_hook(lambda: readline.insert_text(command))
    try:
        return input(EDIT_PROMPT)
    finally:
        readline.set_startup_hook()


def _resolve_variant() -> str:
    """Return the configured variant, falling back to the built-in default.

    Lite gating keys on this: only an explicit ``variant = "lite"`` engages it.
    An unset variant — including 8a's escape hatch where the user named their own
    ``endpoint`` with no ``variant`` — resolves to the default (full) so existing
    users and the escape hatch keep today's behavior untouched.

    Raises:
        ConfigError: If the config file exists but is not valid TOML.
    """
    return load_config().get("variant", DEFAULT_VARIANT)

CONFIG_DESCRIPTION = (
    "Inspect and change tux's endpoint, model, capability variant, and Linux environment."
)

#: Help line shown in ``tux --help``; points the reader at the fuller help.
CONFIG_HELP = f"{CONFIG_DESCRIPTION} Run `config --help` for more."

PROVISION_DESCRIPTION = (
    "Detect this Linux environment, assess the machine's hardware, ensure the "
    "Ollama runtime, pull a suitable model, and write tux's config."
)

HISTORY_DESCRIPTION = (
    "List the commands tux has run, re-run one by its number, or clear the log."
)

#: Help line shown in ``tux --help``; points the reader at the fuller help.
HISTORY_HELP = f"{HISTORY_DESCRIPTION} Run `history --help` for more."

#: Fuller ``tux history --help`` body spelling out the three things it does.
HISTORY_LONG_DESCRIPTION = (
    f"{HISTORY_DESCRIPTION}\n\n"
    "With no argument it lists the runs recorded in tux's run log, oldest first, "
    "each numbered with the exact command and its one-line description. Give a "
    "number (optionally '!'-prefixed, e.g. 3 or '!3') to re-run that recorded "
    "command: it is re-staged through tux's normal propose/run path — the command "
    "is shown with any destructive warning and you choose run or dismiss, so "
    "nothing runs until you say so. Use --clear to empty the log."
)

#: Shown when the run log holds no records yet (missing, empty, or just cleared).
HISTORY_EMPTY = "tux has not recorded any runs yet."


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


def run_ask(
    question: str,
    client: ModelClient | None = None,
    *,
    new: bool = False,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = _default_reader,
    editor: EditReader = _default_edit_reader,
) -> int:
    """Answer one ``tux ask`` turn, carrying context across invocations.

    The conversation thread for this terminal (keyed to the parent shell's PID)
    is loaded from disk, the new turn is routed to either a guided plan or a
    conversational reply, the answer is shown, and the thread is saved so the
    next ``tux ask`` from the same shell sees this turn. A command turn comes
    back as an ordered plan and, in an interactive terminal, is walked one step
    at a time through the run/dismiss/clarify surface; a non-interactive session
    prints the whole plan only. Nothing runs until the user explicitly chooses
    run on a step.

    Args:
        question: The plain-English message for this turn.
        client: Model client to use; defaults to one built from the config file.
        new: When true, discard this shell's existing thread first so the turn
            starts a fresh conversation with no prior context.
        runner: Callable that executes a chosen step; injected in tests so the
            run path is exercised without spawning a real process.
        chooser: Callable presenting the per-step menu; injected in tests so the
            choice is driven without a real terminal.
        reader: Callable reading the clarify free text; injected in tests so the
            clarify re-plan runs without a real terminal.
        editor: Callable reading the inline-edited command; injected in tests so
            the edit path runs without a real terminal.

    Returns:
        The last run step's exit status when the user ran one; otherwise ``0`` on
        a dismissed, clarify-only, conversational, or non-interactive turn; ``1``
        if the model could not be reached or parsed, or the config is malformed.
    """
    if client is None:
        try:
            with managed_local_runtime():
                return run_ask(
                    question, ModelClient.from_config(), new=new, runner=runner,
                    chooser=chooser, reader=reader, editor=editor
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
        # Report and leave the stored thread untouched, so a failed turn never
        # corrupts or truncates the conversation that was already saved.
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
    """Route the turn, present the answer, and return ``(status, message)``.

    The model decides the turn type: a command request goes through the
    structured ``suggest`` path, while a conversational one goes through the
    free-form ``converse`` path and is shown as prose, never walked. ``status``
    is the last run step's exit status when one was run, and ``0`` otherwise;
    ``message`` is the assistant turn (the plan or prose) to store so a follow-up
    sees this turn as context.

    In the **lite** variant a command turn is reduced to a single-command
    proposal (no multi-step overview, per-step walk, or clarify/re-plan loop) and
    a conversational reply still answers in prose but ends with a steer back
    toward command lookup. Any other variant — full, mid, unset, or the escape
    hatch — keeps today's full behavior, conversational replies unsteered. The
    features-all-on switch (:func:`_lite_active`) forces lite off while on, so
    lite behaves like full for the A/B.
    """
    lite = _lite_active(variant)
    with thinking():
        route = client.classify(question, history)
    if route == "command":
        with thinking():
            plan = client.suggest(question, history)
        status, final_plan = _present_command(
            client, question, history, plan, runner, chooser, reader, editor, lite=lite
        )
        return status, assistant_turn(final_plan)
    answer = _stream_reply(client.converse_stream(question, history))
    if lite:
        # cli-layer append: the model's prose is saved as-is; the deterministic
        # steer is shown only, so it never leaks into the stored thread.
        print(f"\n{LITE_STEER}")
    return 0, {"role": "assistant", "content": answer}


def _stream_reply(pieces: Iterator[str]) -> str:
    """Stream a conversational reply to the screen as it arrives; return the full text.

    The "tux is thinking" spinner covers time-to-first-token: the first piece is
    pulled inside :func:`thinking` so the spinner is torn down — line cleared,
    cursor restored — before any prose is printed. The remaining pieces then stream
    straight to stdout, each written and flushed as it arrives so the reply grows on
    screen instead of appearing all at once, and the line is closed with a single
    trailing newline — the same bytes today's buffered ``print(answer)`` produced.

    While the tokens flow, a stop keypress (a bare Escape or a Ctrl-D at a
    terminal) ends the stream between pieces: no further tokens are printed and the
    accumulated partial is returned as-is, so the caller keeps and stores it exactly
    like a completed reply. Stopping is explicit teardown — :func:`_stream_reply`
    closes the ``pieces`` generator, which cascades ``GeneratorExit`` down the
    stream chain, exits the endpoint's ``urlopen`` block, and closes the socket so
    the server releases the in-flight generation rather than running it to
    completion. The stop poll is TTY-gated inside :func:`stop_watch`: off a terminal
    no key handling is engaged and the stream runs uninterrupted.

    If the transport fails mid-stream after prose has already been printed, a
    newline is emitted first so the propagating :class:`ModelClientError` is reported
    on a clean line rather than glued to a half-written one. A failure before the
    first piece (an unreachable endpoint or an empty reply) prints no prose at all.

    Returns:
        The full accumulated reply — or the partial accumulated up to a stop —
        stripped exactly as the buffered path stored it.
    """
    collected: list[str] = []
    printed = False
    try:
        with thinking():
            first = next(pieces)
        sys.stdout.write(first)
        sys.stdout.flush()
        printed = True
        collected.append(first)
        with stop_watch() as stop_requested:
            for piece in pieces:
                sys.stdout.write(piece)
                sys.stdout.flush()
                collected.append(piece)
                if stop_requested():
                    break
    except ModelClientError:
        if printed:
            sys.stdout.write("\n")
            sys.stdout.flush()
        raise
    finally:
        # Explicit teardown, not left to GC: closing the outer generator cascades
        # GeneratorExit down the stream chain, exits the ``urlopen`` block, and
        # closes the socket — which is what lets the server abort the in-flight
        # generation on a stop. On normal exhaustion or a mid-stream error the
        # generator is already finished, so this is a harmless no-op there.
        pieces.close()
    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(collected)


def _present_command(
    client: ModelClient,
    question: str,
    history: list[dict[str, str]],
    plan: Plan,
    runner: CommandRunner,
    chooser: Chooser,
    reader: ClarifyReader,
    editor: EditReader,
    *,
    lite: bool = False,
) -> tuple[int, Plan]:
    """Present a plan and, in a terminal, walk it; return ``(status, final_plan)``.

    In the **lite** variant the turn is reduced to a single-command proposal via
    :func:`_present_single_command`, skipping the multi-step machinery entirely.
    Otherwise, in an interactive terminal the plan is walked one step at a time
    through the run/dismiss/clarify surface, each step reprinting the whole plan
    as one framed block with the active step expanded. A non-interactive session
    renders every step as
    plain text (no styling, no menu) and returns ``0`` with the plan unchanged,
    never running anything, so the propose-only guarantee holds end to end. The
    returned plan is the plan as last known (after any in-walk re-plans), stored
    so the next turn sees this turn as context.
    """
    if lite:
        # The explain loop is seeded from the same running context the walk builds
        # its thread from — prior turns, this turn's question, the proposal — but
        # only as a local copy, so explaining never touches the stored thread.
        context = [*history, {"role": "user", "content": question}, assistant_turn(plan)]

        def explain(suggestion: CommandSuggestion) -> None:
            _explain_loop(client, suggestion, context, question, reader)

        return _present_single_command(
            plan, runner, chooser, editor, explain=explain
        )
    if not _interactive():
        _print_plan_plain(plan)
        return 0, plan
    return _walk_plan(client, question, history, plan, runner, chooser, reader, editor)


def _present_single_command(
    plan: Plan,
    runner: CommandRunner,
    chooser: Chooser,
    editor: EditReader = _default_edit_reader,
    *,
    explain: ExplainRunner | None = None,
) -> tuple[int, Plan]:
    """Present a lite command turn as a single proposal; return ``(status, plan)``.

    Lite stays lookup-first: only the first proposed command is shown — there is
    no multi-step overview, no per-step walk, and no clarify/re-plan loop — while
    the safe-run floor is unchanged. In a terminal the proposal is framed and the
    user is offered run, dismiss, edit, and — when an ``explain`` runner is bound
    (a command turn, but not a history re-run) — explain (dismiss the highlighted
    default and abort fallback). Choosing run executes the command and logs it,
    edit opens the command for an inline tweak and then runs the edited text
    directly, and explain opens a pure-teaching Q&A loop that runs nothing and
    leaves the proposal unchanged before re-offering the menu. A piped session
    prints the proposal plainly and runs nothing. The returned plan is the single
    proposal — carrying the edited command when one ran — so the next turn sees
    what actually ran as context.
    """
    if not plan:
        return 0, []
    suggestion = plan[0]
    if not _interactive():
        _print_suggestion(suggestion, styled=False)
        return 0, [suggestion]
    # Explain sits last in the menu; a surface with no model context (history
    # re-run) drops it, keeping dismiss/run/edit at the same indices.
    choices = LITE_RUN_CHOICES if explain is not None else LITE_RUN_CHOICES[:LITE_EXPLAIN_CHOICE]
    _print_suggestion(suggestion, styled=True)
    while True:
        choice = chooser(choices)
        if choice == RUN_CHOICE:
            status, _ = runner(suggestion.command)
            append_run(suggestion.command, status, suggestion.description)
            return status, [suggestion]
        if choice == LITE_EDIT_CHOICE:
            edited = _read_edit(editor, suggestion.command)
            if edited is None:
                continue  # cancel: back to the proposal's menu, unchanged
            status, _ = _run_edited(edited, runner, suggestion.description)
            return status, [replace(suggestion, command=edited)]
        if choice == LITE_EXPLAIN_CHOICE and explain is not None:
            explain(suggestion)
            continue  # explain runs nothing: re-offer the menu, proposal unchanged
        return 0, [suggestion]  # dismiss, the highlighted default and abort fallback


def _walk_plan(
    client: ModelClient,
    question: str,
    history: list[dict[str, str]],
    plan: Plan,
    runner: CommandRunner,
    chooser: Chooser,
    reader: ClarifyReader,
    editor: EditReader,
) -> tuple[int, Plan]:
    """Walk an ordered plan one step at a time; return ``(status, final_plan)``.

    Each step reprints the whole plan as one framed block — inactive steps as dim
    numbered titles, the active step expanded with its command and description —
    with a run/dismiss/clarify/edit choice offered only on that active step. On
    run the step's single command is executed, the run is logged, and — when later
    steps remain — its captured output is fed back to the model so the remaining
    steps are refined (placeholders resolved) without the user copy/pasting. On
    clarify the user's free text re-plans the remaining steps and the block is
    reprinted with the revised steps on the next iteration; backing out of clarify
    (a blank line, Escape, or Ctrl-D) re-offers the active step's menu with the
    plan unchanged rather than abandoning the walk. On edit the step's
    command is opened for an inline tweak and the
    edited text runs directly — flagged, logged, and fed to any re-plan in place of
    the original — with the edited command replacing the step in the walked plan;
    backing out of an edit returns to the active step's menu and runs nothing. On
    explain the active step opens a pure-teaching Q&A loop that runs nothing and
    leaves the plan (and its thread) untouched, then returns to the same step's
    menu. On dismiss (also the abort fallback) the rest of the plan is abandoned.
    Nothing runs until the user chooses run or confirms an edit on the active step.
    """
    # Working conversation trail for in-walk re-planning: the prior turns, this
    # turn's question, then the assistant's plan. Re-plans append to it so the
    # model always sees the running context (the same history-in-body trail).
    thread = [*history, {"role": "user", "content": question}, assistant_turn(plan)]
    steps = list(plan)
    status = 0
    index = 0
    while index < len(steps):
        step = steps[index]
        _print_walk_block(steps, index)
        _warn_if_destructive(step.command)
        choice = chooser(RUN_CHOICES)
        if choice == RUN_CHOICE:
            run_status, output = runner(step.command)
            append_run(step.command, run_status, step.description)
            status = run_status
            index += 1
            if index < len(steps):
                steps = steps[:index] + _replan_from_output(
                    client, thread, step.command, output
                )
        elif choice == CLARIFY_CHOICE:
            clarification = _read_clarification(reader)
            if clarification is None:
                # Back out (blank line, Escape, or Ctrl-D): re-offer the active
                # step's menu, the plan unchanged — never abandon the walk.
                continue
            revised = _replan_from_clarification(client, thread, clarification)
            steps = steps[:index] + revised
        elif choice == EDIT_CHOICE:
            edited = _read_edit(editor, step.command)
            if edited is None:
                # Cancel: re-offer the active step's menu, the plan unchanged.
                continue
            run_status, output = _run_edited(edited, runner, step.description)
            status = run_status
            # The edited command replaces the step so the run log, the re-plan
            # input, and the stored plan all agree on what actually ran.
            steps[index] = replace(step, command=edited)
            index += 1
            if index < len(steps):
                steps = steps[:index] + _replan_from_output(
                    client, thread, edited, output
                )
        elif choice == EXPLAIN_CHOICE:
            # Pure teaching about the active step: runs nothing, changes nothing,
            # and leaves the plan thread untouched. The loop then re-offers this
            # same step's menu, unchanged.
            _explain_loop(client, step, thread, question, reader)
        else:
            break
    return status, steps


def _replan_from_output(
    client: ModelClient, thread: list[dict[str, str]], command: str, output: str
) -> Plan:
    """Feed a run step's output back and return the refined remaining steps.

    The output is appended to the running thread as context and the model
    re-plans the remaining steps so a placeholder resolves from the real output.
    The captured output reaches only the model and the user, never the run log.
    """
    message = output_message(command, output)
    with thinking():
        revised = client.suggest(message, thread)
    thread.append({"role": "user", "content": message})
    thread.append(assistant_turn(revised))
    return revised


def _replan_from_clarification(
    client: ModelClient, thread: list[dict[str, str]], clarification: str
) -> Plan:
    """Send the clarify text to the model and return the revised remaining steps."""
    with thinking():
        revised = client.suggest(clarification, thread)
    thread.append({"role": "user", "content": clarification})
    thread.append(assistant_turn(revised))
    return revised


def _read_clarification(reader: ClarifyReader) -> str | None:
    """Read the clarify free text, or ``None`` to back out (blank or end-of-input).

    A blank line, an Escape, or a Ctrl-D resolves to back out so a stray keystroke
    never re-plans; the walk then re-offers the active step's menu, the plan
    unchanged, rather than abandoning the rest of the walk.
    """
    try:
        text = reader(CLARIFY_PROMPT).strip()
    except EOFError:
        # A bare Ctrl-D leaves the prompt mid-line; finish it cleanly.
        print()
        return None
    return text or None


def _explain_loop(
    client: ModelClient,
    suggestion: CommandSuggestion,
    context: list[dict[str, str]],
    question: str,
    reader: ClarifyReader,
) -> None:
    """Answer *why* ``suggestion`` is the right command, then loop on follow-ups.

    Pure teaching: it runs nothing and changes nothing. tux first streams an
    explanation of why the proposed command fits the question — grounded in the
    command and the turn's running ``context`` and going beyond the one-line
    description — then reads a free-text follow-up; a non-empty question yields
    another streamed answer and the loop repeats. A blank line or end-of-input
    leaves the loop, and a model error surfaces a short message and leaves too — in
    every case returning to the caller's menu with the proposal intact.

    The exchange lives on a **local** trail seeded from a copy of ``context`` (the
    prior turns and this turn), so follow-ups never leak into the plan thread used
    for re-planning nor into the on-disk per-shell conversation.
    """
    trail = list(context)
    request = explain_request(
        question, suggestion.title, suggestion.command, suggestion.description
    )
    while True:
        try:
            answer = _stream_reply(client.explain_stream(request, trail))
        except ModelClientError as exc:
            # Surface a short message and fall back to the menu, proposal intact,
            # rather than aborting the turn.
            print(f"tux: {exc}", file=sys.stderr)
            return
        trail.append({"role": "user", "content": request})
        trail.append({"role": "assistant", "content": answer})
        follow_up = _read_follow_up(reader)
        if follow_up is None:
            return
        request = follow_up


def _read_follow_up(reader: ClarifyReader) -> str | None:
    """Read an explain follow-up question, or ``None`` to leave (blank line or EOF).

    A blank line, an Escape, or a Ctrl-D resolves to leave so the explain loop
    returns to the proposal's menu without the aborted follow-up leaking into the
    stored thread, mirroring :func:`_read_clarification`.
    """
    try:
        text = reader(EXPLAIN_PROMPT).strip()
    except EOFError:
        # A bare Ctrl-D leaves the prompt mid-line; finish it cleanly.
        print()
        return None
    return text or None


def _read_edit(editor: EditReader, command: str) -> str | None:
    """Read an edited command, or ``None`` to cancel (blank line or end-of-input).

    A blank/whitespace-only result, an Escape, or a Ctrl-D resolves to cancel so a
    stray keystroke never runs a command and the caller falls back to its unchanged
    proposal, preserving the "nothing runs on a stray keystroke" guarantee.
    """
    try:
        edited = editor(command).strip()
    except EOFError:
        # A bare Ctrl-D leaves the prompt mid-line; finish it cleanly.
        print()
        return None
    return edited or None


def _run_edited(
    command: str, runner: CommandRunner, description: str
) -> tuple[int, str]:
    """Run an edited command directly, flagging it first and logging it after.

    The edit-then-run path takes no further run/dismiss confirmation, so the
    item-6 destructive warning is shown on the *edited* text before execution —
    editing can never silently slip a destructive command past the flag, and a
    benign edit shows no warning. The edited command (not the original proposal)
    is what runs and what is appended to the run log (item 5: command text and
    exit status only; captured output is never logged). The edit changes the
    command text, not the intent, so the run is logged with ``description`` — the
    originating proposal/step's description — rather than a description of the edit.
    """
    _warn_if_destructive(command)
    status, output = runner(command)
    append_run(command, status, description)
    return status, output


def _warn_if_destructive(command: str) -> None:
    """Print the destructive warning for ``command`` when static inspection flags it.

    The edit-then-run path is interactive only, so the warning carries the same
    bold-red styling as the framed proposal's warning; a benign command — one
    :func:`destructive_reason` does not flag — prints nothing.
    """
    reason = destructive_reason(command)
    if reason is not None:
        print(f"{_WARNING_STYLE}⚠ {_WARNING_PREFIX}: {reason}{_RESET}")


def _print_walk_block(steps: Plan, active: int) -> None:
    """Print the whole plan as one framed block with only the active step expanded.

    The numbered step list is wrapped in a single pair of horizontal rules. Each
    inactive step is a dim numbered title line with no pointer glyph; the active
    step's numbered title is shown in the normal (undimmed) style with its command
    and description indented beneath it, so the block stays compact while the
    reader still sees the whole path. Reprinted on each step of the walk with the
    newly-active step expanded. Display only, and — like the framed proposal — all
    colour is gated to the interactive walk; nothing runs.
    """
    titles = [f"{number}. {step.title}" for number, step in enumerate(steps, start=1)]
    active_step = steps[active]
    command_line = f"   command: {active_step.command}"
    description_line = f"   description: {active_step.description}"
    width = max(len(line) for line in (*titles, command_line, description_line))
    rule = _RULE_CHAR * width
    print()
    print(rule)
    for number, step in enumerate(steps, start=1):
        if number - 1 == active:
            print(f"{number}. {step.title}")
            print(
                f"{_LABEL_STYLE}   command:{_RESET} "
                f"{_COMMAND_STYLE}{step.command}{_RESET}"
            )
            print(f"{_LABEL_STYLE}   description:{_RESET} {step.description}")
        else:
            print(f"{_LABEL_STYLE}{number}. {step.title}{_RESET}")
    print(rule)


def _print_plan_plain(plan: Plan) -> None:
    """Print every step of the plan as plain text for a non-interactive session.

    No styling, no menu, no overview frame: each step renders as the same
    labelled title/command/description block the piped fallback already uses,
    keeping the per-step single-command shape visible to scripts.
    """
    for step in plan:
        _print_suggestion(step, styled=False)


def _interactive() -> bool:
    """Return whether tux is attached to a terminal on both stdin and stdout.

    Only then is the run/dismiss menu shown; a piped or redirected session falls
    back to printing the proposal and running nothing, preserving the
    one-shot/scripting path.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_suggestion(suggestion: CommandSuggestion, *, styled: bool) -> None:
    """Render a proposal as a title / command / description block.

    When ``styled`` (an interactive terminal), the block is framed between two
    horizontal rules, carries distinct ANSI styling per line, and gets vertical
    breathing room — a blank line above and a blank line below before the menu.
    When not styled (the piped/redirected fallback), the same three fields are
    printed as plain text with no escape sequences and no frame, keeping the
    one-shot/scripting path script-friendly. Running is offered separately and
    only after the user explicitly chooses it.

    A command that tux's static inspection flags as potentially destructive
    carries a distinct warning — bold red and set apart in the styled block,
    plain text in the fallback — so the risk is visible before the run/dismiss
    choice. A non-destructive command renders exactly as it did before.
    """
    reason = destructive_reason(suggestion.command)
    if not styled:
        print(suggestion.title)
        print(f"command: {suggestion.command}")
        print(f"description: {suggestion.description}")
        if reason is not None:
            print(f"warning: {_WARNING_PREFIX} — {reason}")
        return
    width = max(
        len(suggestion.title),
        len(f"command: {suggestion.command}"),
        len(f"description: {suggestion.description}"),
    )
    rule = _RULE_CHAR * width
    print()  # padding above the block
    print(rule)
    print(f"{_TITLE_STYLE}{suggestion.title}{_RESET}")
    print(f"{_LABEL_STYLE}command:{_RESET} {_COMMAND_STYLE}{suggestion.command}{_RESET}")
    print(f"{_LABEL_STYLE}description:{_RESET} {suggestion.description}")
    print(rule)
    if reason is not None:
        # Set apart below the frame, in bold red, so it is read before the menu.
        print(f"{_WARNING_STYLE}⚠ {_WARNING_PREFIX}: {reason}{_RESET}")
    print()  # margin below the block, before the menu


def run_session(
    client: ModelClient | None = None,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = _default_reader,
    editor: EditReader = _default_edit_reader,
) -> int:
    """Run an interactive, multi-turn conversation, holding context in memory.

    The user types a question, sees the proposed plan, and walks it one step at a
    time through the run/dismiss/clarify surface, then asks follow-ups that build
    on the earlier turns. Each request carries the prior turns so a follow-up is
    answered in context. A step may be run (tux executes it and logs the run),
    dismissed, or clarified; nothing runs until the user chooses run. The
    accumulated context lives only for this session. The session ends on EOF or
    an exit word.

    Args:
        client: Model client to use; defaults to one built from the config file.
        runner: Callable that executes a chosen step; injected in tests so the
            run path is exercised without spawning a real process.
        chooser: Callable presenting the per-step menu; injected in tests so the
            choice is driven without a real terminal.
        reader: Callable reading the clarify free text; injected in tests so the
            clarify re-plan runs without a real terminal.
        editor: Callable reading the inline-edited command; injected in tests so
            the edit path runs without a real terminal.

    Returns:
        ``0`` when the session ends cleanly, ``1`` if the client could not be
        built from a malformed config file.
    """
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
    # Prior turns as chat messages, oldest first; sent with each request so the
    # model answers follow-ups in context. Lives only for this session.
    history: list[dict[str, str]] = []
    while True:
        try:
            line = input(SESSION_PROMPT)
        except EOFError:
            # A bare Ctrl-D leaves the prompt mid-line; finish it cleanly.
            print()
            return 0
        question = line.strip()
        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            return 0
        try:
            _, assistant = _answer_turn(
                client, question, history, runner, chooser, reader, editor,
                LITE_VARIANT if lite else DEFAULT_VARIANT,
            )
        except ModelClientError as exc:
            print(f"tux: {exc}", file=sys.stderr)
            continue
        history.append({"role": "user", "content": question})
        history.append(assistant)


def main(
    argv: list[str] | None = None,
    client: ModelClient | None = None,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
    reader: ClarifyReader = _default_reader,
    editor: EditReader = _default_edit_reader,
) -> int:
    """Run the ``tux`` command-line interface.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]`` when ``None``.
        client: Model client for the ``ask`` flow; injected in tests so the flow
            can run without a live endpoint. Defaults to one built from the
            environment.
        runner: Callable that executes a chosen step; injected in tests so the
            run path is exercised without spawning a real process.
        chooser: Callable presenting the per-step menu; injected in tests so the
            choice is driven without a real terminal.
        reader: Callable reading the clarify free text; injected in tests so the
            clarify re-plan runs without a real terminal.
        editor: Callable reading the inline-edited command; injected in tests so
            the edit path runs without a real terminal.

    Returns:
        Process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ask":
        # ``--version`` and ``--help`` are handled (and exit) inside parse_args.
        # No question given starts an interactive, multi-turn session; a supplied
        # question keeps the one-shot path intact for scripting/piping.
        if args.question is None:
            return run_session(client, runner, chooser, reader, editor)
        return run_ask(
            args.question, client, new=args.new, runner=runner, chooser=chooser,
            reader=reader, editor=editor,
        )
    if args.command == "config":
        return run_config(args)
    if args.command == "provision":
        return run_provision(args)
    if args.command == "history":
        return run_history(args, runner=runner, chooser=chooser)
    # No subcommand was given, so show the help to keep the tool self-explanatory.
    parser.print_help()
    return 0


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


def run_provision(args: argparse.Namespace) -> int:
    """Run the guided, re-runnable provisioning and report what it did.

    Consent is interactive only when tux is attached to a terminal; a piped or
    redirected (unattended) run never prompts — it defers the model pull to first
    run unless ``--yes`` preseeds consent — so the install never hangs.

    Returns:
        ``0`` on success; ``1`` if a provisioning step (install, pull, or config
        write) fails.
    """
    try:
        result = provision(
            interactive=_interactive(), assume_yes=args.yes, pin=args.variant
        )
    except (OSError, subprocess.CalledProcessError, ConfigError) as exc:
        print(f"tux: provisioning failed: {exc}", file=sys.stderr)
        return 1
    _print_provision_result(result)
    return 0


def _print_provision_result(result: ProvisionResult) -> None:
    """Print a human summary of a provisioning run."""
    if result.bypassed:
        print(
            "tux is already pointed at a configured endpoint "
            f"({result.endpoint}); skipping provisioning."
        )
        return
    if not result.ollama_ready:
        print(
            "The Ollama runtime is not installed, so provisioning stopped there "
            "(no model tier was chosen and nothing was downloaded). Run 'tux "
            "provision' again to be asked, or 'tux provision --yes' to install "
            "it and continue."
        )
        return
    if result.decision is not None:
        print(f"Selected the {result.tier.capability} tier ({result.variant}):")
        for reason in result.decision.reasons:
            print(f"  - {reason}")
    print(f"Detected system: {result.system}.")
    if result.ollama_installed:
        print("Installed the Ollama runtime.")
    if result.ollama_server_started:
        print("Started the Ollama server for this provisioning run.")
    if result.model_pulled:
        print(f"Pulled model {result.model}.")
    elif result.model_deferred:
        print(
            f"Deferred the download of {result.model} to first run "
            "(no consent given yet)."
        )
    else:
        print(f"Model {result.model} already present.")
    if result.endpoint_reachable is False:
        print(f"warning: endpoint {result.endpoint} is not reachable yet.")
    print(
        f"Config now points at {result.endpoint} "
        f"(model {result.model}, system {result.system})."
    )


def run_history(
    args: argparse.Namespace,
    *,
    runner: CommandRunner = run_command,
    chooser: Chooser = select,
) -> int:
    """Dispatch a ``tux history`` invocation: clear, re-run an entry, or list.

    ``--clear`` empties the log and wins over the others; otherwise an ``entry``
    reference re-stages that recorded command, and with neither the active log is
    listed (optionally limited to the most recent ``-n`` runs).

    Returns:
        ``0`` on a successful list or clear, ``0`` when a re-run dismisses or runs
        cleanly (or the run's own exit status), and ``1`` for a bad re-run
        reference.
    """
    if args.clear:
        clear_runs()
        return 0
    if args.entry is not None:
        return _history_rerun(args.entry, runner, chooser)
    return _history_list(args.limit)


def _history_list(limit: int | None) -> int:
    """Print the active run log, numbered chronologically; honor a recent-N limit.

    Numbers are positional within the active log (entry 1 is the oldest record),
    so a ``-n`` limit shows a tail with those same numbers preserved — the number
    a user reads is the number ``tux history <n>`` re-runs. An empty or missing
    log prints a friendly note and still exits 0.
    """
    records = read_runs()
    if not records:
        print(HISTORY_EMPTY)
        return 0
    numbered = list(enumerate(records, start=1))
    if limit is not None:
        numbered = numbered[-limit:] if limit > 0 else []
    styled = _interactive()
    for number, record in numbered:
        _print_history_entry(number, record, styled=styled)
    return 0


def _print_history_entry(number: int, record: RunRecord, *, styled: bool) -> None:
    """Render one numbered run entry: ``N. <command> — <description>``.

    For a learning tool the *why* — the command's one-line description — is the
    teaching payload, so the entry pairs the command with its description and
    drops the timestamp and exit status from the display (both stay stored and
    still drive re-run). A pre-change entry with no stored description shows the
    :data:`NO_DESCRIPTION` placeholder in the description position. At a terminal
    the line carries the established styling — a dim number, the command in the
    command style, and the description dimmed — so the listing matches tux's other
    output; piped or redirected it is plain text with no escape sequences so it
    stays script-friendly.
    """
    if not styled:
        print(f"{number}. {record.command} — {record.description}")
        return
    print(
        f"{_LABEL_STYLE}{number}.{_RESET} "
        f"{_COMMAND_STYLE}{record.command}{_RESET} "
        f"{_LABEL_STYLE}— {record.description}{_RESET}"
    )


def _history_rerun(reference: str, runner: CommandRunner, chooser: Chooser) -> int:
    """Re-stage the recorded command named by ``reference`` through the normal run path.

    The reference is a 1-based number (optionally ``!``-prefixed) into the active
    log. The recorded command is wrapped in a single-command proposal and run
    through the same staging tail as a fresh suggestion — destructive flagging,
    the run/dismiss chooser, the command runner, and the run-log append — with no
    model call, so the command text is exactly what was logged. The re-staged
    proposal inherits the source entry's description, so the re-logged run carries
    that real description (never a synthesized string) and lists with it. A
    reference that is non-numeric, out of range, or used against an empty log
    prints a friendly
    error, runs nothing, and exits non-zero.
    """
    records = read_runs()
    index = _parse_reference(reference)
    if index is None or not (1 <= index <= len(records)):
        print(f"tux: no recorded run #{reference}", file=sys.stderr)
        return 1
    record = records[index - 1]
    suggestion = CommandSuggestion(
        title=f"Re-running #{index}",
        command=record.command,
        description=record.description,
    )
    status, _ = _present_single_command([suggestion], runner, chooser)
    return status


def _parse_reference(reference: str) -> int | None:
    """Parse a re-run reference into a positive 1-based index, or ``None``.

    A single optional leading ``!`` is stripped (so ``3`` and ``!3`` are the same
    reference); the remainder must be a plain positive integer. Anything else —
    empty, non-numeric, zero, or negative — yields ``None`` for the caller to
    reject.
    """
    text = reference[1:] if reference.startswith("!") else reference
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


if __name__ == "__main__":
    raise SystemExit(main())

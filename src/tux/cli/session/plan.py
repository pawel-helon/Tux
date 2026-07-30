"""Presentation and execution of command plans."""

from collections.abc import Callable
from dataclasses import replace

from tux.chooser import Chooser
from tux.client import ModelClient
from tux.modes.command import CommandSuggestion, Plan, assistant_turn, output_message
from tux.runner import CommandRunner, append_run
from tux.thinking import thinking
from tux.cli.session.explain import explain_loop
from tux.cli.session.interaction import (
    ClarifyReader,
    EditReader,
    default_edit_reader,
    interactive,
    read_clarification,
    read_edit,
)
from tux.cli.session.presentation import (
    print_plan_plain,
    print_suggestion,
    print_walk_block,
    warn_if_destructive,
)

RUN_CHOICES = ("Dismiss", "Run", "Clarify", "Edit", "Explain")
DISMISS_CHOICE = 0
RUN_CHOICE = 1
CLARIFY_CHOICE = 2
EDIT_CHOICE = 3
EXPLAIN_CHOICE = 4

LITE_RUN_CHOICES = ("Dismiss", "Run", "Edit", "Explain")
LITE_EDIT_CHOICE = 2
LITE_EXPLAIN_CHOICE = 3

ExplainRunner = Callable[[CommandSuggestion], None]


def present_command(
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
    """Present a command plan and return its status and final stored form."""
    if lite:
        context = [*history, {"role": "user", "content": question}, assistant_turn(plan)]

        def explain(suggestion: CommandSuggestion) -> None:
            explain_loop(client, suggestion, context, question, reader)

        return present_single_command(plan, runner, chooser, editor, explain=explain)
    if not interactive():
        print_plan_plain(plan)
        return 0, plan
    return walk_plan(client, question, history, plan, runner, chooser, reader, editor)


def present_single_command(
    plan: Plan,
    runner: CommandRunner,
    chooser: Chooser,
    editor: EditReader = default_edit_reader,
    *,
    explain: ExplainRunner | None = None,
) -> tuple[int, Plan]:
    """Present a single proposal with dismiss, run, edit, and optional explain."""
    if not plan:
        return 0, []
    suggestion = plan[0]
    if not interactive():
        print_suggestion(suggestion, styled=False)
        return 0, [suggestion]
    choices = (
        LITE_RUN_CHOICES
        if explain is not None
        else LITE_RUN_CHOICES[:LITE_EXPLAIN_CHOICE]
    )
    print_suggestion(suggestion, styled=True)
    while True:
        choice = chooser(choices)
        if choice == RUN_CHOICE:
            status, _ = runner(suggestion.command)
            append_run(suggestion.command, status, suggestion.description)
            return status, [suggestion]
        if choice == LITE_EDIT_CHOICE:
            edited = read_edit(editor, suggestion.command)
            if edited is None:
                continue
            status, _ = run_edited(edited, runner, suggestion.description)
            return status, [replace(suggestion, command=edited)]
        if choice == LITE_EXPLAIN_CHOICE and explain is not None:
            explain(suggestion)
            continue
        return 0, [suggestion]


def walk_plan(
    client: ModelClient,
    question: str,
    history: list[dict[str, str]],
    plan: Plan,
    runner: CommandRunner,
    chooser: Chooser,
    reader: ClarifyReader,
    editor: EditReader,
) -> tuple[int, Plan]:
    """Walk an ordered plan one step at a time."""
    thread = [*history, {"role": "user", "content": question}, assistant_turn(plan)]
    steps = list(plan)
    status = 0
    index = 0
    while index < len(steps):
        step = steps[index]
        print_walk_block(steps, index)
        warn_if_destructive(step.command)
        choice = chooser(RUN_CHOICES)
        if choice == RUN_CHOICE:
            run_status, output = runner(step.command)
            append_run(step.command, run_status, step.description)
            status = run_status
            index += 1
            if index < len(steps):
                steps = steps[:index] + replan_from_output(
                    client, thread, step.command, output
                )
        elif choice == CLARIFY_CHOICE:
            clarification = read_clarification(reader)
            if clarification is None:
                continue
            steps = steps[:index] + replan_from_clarification(
                client, thread, clarification
            )
        elif choice == EDIT_CHOICE:
            edited = read_edit(editor, step.command)
            if edited is None:
                continue
            run_status, output = run_edited(edited, runner, step.description)
            status = run_status
            steps[index] = replace(step, command=edited)
            index += 1
            if index < len(steps):
                steps = steps[:index] + replan_from_output(
                    client, thread, edited, output
                )
        elif choice == EXPLAIN_CHOICE:
            explain_loop(client, step, thread, question, reader)
        else:
            break
    return status, steps


def replan_from_output(
    client: ModelClient, thread: list[dict[str, str]], command: str, output: str
) -> Plan:
    """Feed command output back to the model and refine remaining steps."""
    message = output_message(command, output)
    with thinking():
        revised = client.suggest(message, thread)
    thread.append({"role": "user", "content": message})
    thread.append(assistant_turn(revised))
    return revised


def replan_from_clarification(
    client: ModelClient, thread: list[dict[str, str]], clarification: str
) -> Plan:
    """Re-plan remaining steps from the user's clarification."""
    with thinking():
        revised = client.suggest(clarification, thread)
    thread.append({"role": "user", "content": clarification})
    thread.append(assistant_turn(revised))
    return revised


def run_edited(
    command: str, runner: CommandRunner, description: str
) -> tuple[int, str]:
    """Warn, run, and log an edited command."""
    warn_if_destructive(command)
    status, output = runner(command)
    append_run(command, status, description)
    return status, output

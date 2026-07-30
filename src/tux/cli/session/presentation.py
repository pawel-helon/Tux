"""Rendering helpers for command proposals and plans."""

from tux.modes.command import CommandSuggestion, Plan
from tux.safety import destructive_reason

_RESET = "\x1b[0m"
_TITLE_STYLE = "\x1b[1;33m"
_LABEL_STYLE = "\x1b[2m"
_COMMAND_STYLE = "\x1b[1;36m"
_WARNING_STYLE = "\x1b[1;31m"
_WARNING_PREFIX = "potentially destructive"
_RULE_CHAR = "─"


def print_suggestion(suggestion: CommandSuggestion, *, styled: bool) -> None:
    """Render a proposal as a title, command, and description block."""
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
    print()
    print(rule)
    print(f"{_TITLE_STYLE}{suggestion.title}{_RESET}")
    print(f"{_LABEL_STYLE}command:{_RESET} {_COMMAND_STYLE}{suggestion.command}{_RESET}")
    print(f"{_LABEL_STYLE}description:{_RESET} {suggestion.description}")
    print(rule)
    if reason is not None:
        print(f"{_WARNING_STYLE}⚠ {_WARNING_PREFIX}: {reason}{_RESET}")
    print()


def print_walk_block(steps: Plan, active: int) -> None:
    """Print the whole plan with only the active step expanded."""
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


def print_plan_plain(plan: Plan) -> None:
    """Print every step of a plan without terminal styling."""
    for step in plan:
        print_suggestion(step, styled=False)


def warn_if_destructive(command: str) -> None:
    """Print a styled warning when static inspection flags ``command``."""
    reason = destructive_reason(command)
    if reason is not None:
        print(f"{_WARNING_STYLE}⚠ {_WARNING_PREFIX}: {reason}{_RESET}")

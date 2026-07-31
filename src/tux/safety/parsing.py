"""Shell tokenisation and command-segment normalisation for safety checks."""

import shlex

_PRIVILEGE_COMMANDS = frozenset({"sudo", "doas"})
_SEPARATORS = frozenset({"|", "||", "&&", ";", "&", "|&"})


def tokenise(text: str) -> list[str]:
    """Split shell text into tokens, falling back to whitespace splitting."""
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def segments(tokens: list[str]) -> list[list[str]]:
    """Split shell tokens into individual command segments."""
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def strip_privilege_prefix(segment: list[str]) -> list[str]:
    """Drop leading privilege commands and environment assignments."""
    index = 0
    while index < len(segment) and (
        command_name(segment[index]) in _PRIVILEGE_COMMANDS or "=" in segment[index]
    ):
        index += 1
    return segment[index:]


def command_name(token: str) -> str:
    """Return a command's basename."""
    return token.rsplit("/", 1)[-1]


def has_flag(
    args: list[str], short_letters: frozenset[str], long_flags: frozenset[str]
) -> bool:
    """Return whether arguments contain one of the requested flags."""
    for arg in args:
        if arg in long_flags:
            return True
        if len(arg) > 1 and arg[0] == "-" and arg[1] != "-":
            if any(letter in arg[1:] for letter in short_letters):
                return True
    return False


# Compatibility aliases for the former private helpers.
_tokenise = tokenise
_segments = segments
_strip_privilege_prefix = strip_privilege_prefix
_command_name = command_name
_has_flag = has_flag

"""Conversational-path request shaping and routing for the tux model client.

This module owns the *free-form* turns: a lightweight routing prompt that decides
whether a message is a command request or ordinary conversation, a chat prompt
that answers conversationally, and an explain prompt that teaches *why* an
already-proposed command is the right one. None uses a ``json_schema`` response
format, so a plain question — including one that refers back to an earlier turn —
is answered as prose instead of being forced into a command.

Like :mod:`tux.modes.command`, it is pure: it builds request bodies and interprets the
routing reply, knowing nothing about HTTP or streaming. The transport lives in
:mod:`tux.client`.
"""

from tux.helpers import build_messages
from tux.system import chat_context, explain_context

#: Routing needs only a single word back; conversational replies need room for a
#: short paragraph. An explain answer teaches the *why* behind a command, so it
#: gets the same room as a conversational reply.
CLASSIFY_MAX_TOKENS = 8
CHAT_MAX_TOKENS = 512
EXPLAIN_MAX_TOKENS = 512

#: Prompt for the lightweight routing call that decides a turn's type before the
#: real answer is produced. It also identifies requests that need earlier-session
#: context, using the existing route decision rather than another classifier.
CLASSIFY_PROMPT = (
    "You route messages for a Linux assistant. Read the user's latest message in "
    "the current conversation and choose one route. Reply with exactly one token: "
    "COMMAND for a system task best answered with a shell command; CHAT for "
    "ordinary conversation; MEMORY_COMMAND when answering requires details from a "
    "previous, separate Tux session and the answer is a system command; or "
    "MEMORY_CHAT when answering requires details from a previous, separate Tux "
    "session and the answer is conversational. An explicit reference to a "
    "previous session takes priority over CHAT: always choose a MEMORY route for "
    "questions like 'What did I ask you last time?', 'What was that shortcut "
    "again?', or 'What did we decide in our previous conversation?' Do not use a "
    "MEMORY route when the current conversation already supplies the context."
)

#: System prompt for a free-form conversational turn. No shell command is
#: proposed here; the model answers in plain prose, in context.
CHAT_SYSTEM_PROMPT = (
    "You are tux, a friendly Linux assistant. Answer the user's message "
    "conversationally in plain prose, drawing on earlier turns when relevant. Do not "
    "turn the reply into a staged command plan; answer the question directly."
)

EXPLAIN_SYSTEM_PROMPT = (
    "You are tux, a friendly Linux assistant. The user has been shown a proposed "
    "shell command and wants to understand WHY it is the right command for what they "
    "asked, not merely what it does. Explain why the command and its options fit the "
    "task, how it relates to alternatives, and what it teaches about the system. This "
    "is teaching only: do not propose a different command and do not tell the user to "
    "run anything."
)


def chat_system_prompt(system: str) -> str:
    return f"{CHAT_SYSTEM_PROMPT} Environment details: {chat_context(system)}"


def explain_system_prompt(system: str) -> str:
    return f"{EXPLAIN_SYSTEM_PROMPT} Environment details: {explain_context(system)}"



def build_classify_payload(
    model: str, question: str, history: list[dict[str, str]]
) -> dict:
    """Build the request body for the routing call (no structured output)."""
    return _build_payload(model, CLASSIFY_PROMPT, question, history, CLASSIFY_MAX_TOKENS)


def build_chat_payload(
    model: str, system: str, question: str, history: list[dict[str, str]]
) -> dict:
    """Build the request body for a free-form conversational reply."""
    return _build_payload(
        model, chat_system_prompt(system), question, history, CHAT_MAX_TOKENS
    )


def build_explain_payload(
    model: str, system: str, question: str, history: list[dict[str, str]]
) -> dict:
    """Build the request body for an explain answer (no structured output)."""
    return _build_payload(
        model, explain_system_prompt(system), question, history, EXPLAIN_MAX_TOKENS
    )


def explain_request(
    question: str, title: str, command: str, description: str
) -> str:
    """Phrase the opening 'why this command' request, seeded with the proposal.

    The seed states the user's original question and the proposed command with its
    title and one-line description, then asks for the reasoning behind it. It is a
    user-role message so the model answers it as the current turn; the fields are
    passed as plain strings so this stays decoupled from the command dataclass.
    """
    return (
        f'I asked: "{question}"\n'
        "tux proposed this command:\n"
        f"  title: {title}\n"
        f"  command: {command}\n"
        f"  description: {description}\n"
        "Explain why this is the right command for what I asked, going beyond the "
        "one-line description."
    )


def interpret_route(reply: str) -> str:
    """Map the router's reply to command/chat and optional-memory route names.

    Anything that is not an explicit command vote falls back to ``"chat"`` so a
    stray word never forces an unwanted command proposal.
    """
    route = reply.strip().upper().replace("-", "_")
    if "MEMORY_COMMAND" in route:
        return "memory_command"
    if "MEMORY_CHAT" in route:
        return "memory_chat"
    return "command" if "COMMAND" in route else "chat"


def _build_payload(
    model: str,
    system_prompt: str,
    question: str,
    history: list[dict[str, str]],
    max_tokens: int,
) -> dict:
    """Build a plain chat request body with **no** structured-output format."""
    return {
        "model": model,
        "stream": True,
        "max_tokens": max_tokens,
        "reasoning_effort": "none",
        "messages": build_messages(system_prompt, question, history),
    }

"""Shared, pure helpers for both the command and conversational model paths.

These have no knowledge of HTTP or of which path is calling them: they assemble
the chat message list and accumulate a streamed reply. Keeping them here lets
:mod:`tux.modes.command` and :mod:`tux.modes.chat` build requests the same way and lets
:mod:`tux.client` collect any stream without either path duplicating the logic.
"""

import json
from collections.abc import Iterable, Iterator


def build_messages(
    system_prompt: str, question: str, history: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Return ``[system, *history, user]`` for a chat request.

    The system prompt leads, prior turns follow oldest-first, and the new
    question comes last, so the model always sees the running conversation in
    order.
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    return messages


def iter_stream(lines: Iterable[str]) -> Iterator[str]:
    """Yield each ``delta.content`` piece from SSE lines, stopping at ``finish_reason``.

    This is the streaming form of :func:`collect_stream`: it emits each content
    delta as it is parsed so a caller can show a reply as it arrives instead of
    waiting for the whole thing. Termination is driven by ``finish_reason`` rather
    than the trailing ``[DONE]`` sentinel so iteration finishes promptly when the
    model signals completion. Blank, non-``data:``, and unparseable lines are
    skipped exactly as the accumulating form skips them.
    """
    for line in lines:
        raw = line.rstrip("\n")
        if not raw.startswith("data:"):
            continue
        data = raw[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choice = chunk["choices"][0]
        content = choice.get("delta", {}).get("content")
        if content:
            yield content
        if choice.get("finish_reason"):
            break


def collect_stream(lines: Iterable[str]) -> str:
    """Accumulate ``delta.content`` from SSE lines, stopping at ``finish_reason``.

    Implemented as the join of :func:`iter_stream` so the buffered and streamed
    paths read the same SSE lines identically and cannot drift.
    """
    return "".join(iter_stream(lines))

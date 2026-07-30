"""Pure-teaching explanation loop for proposed commands."""

import sys

from tux.client import ModelClient, ModelClientError
from tux.modes.chat import explain_request
from tux.modes.command import CommandSuggestion
from tux.cli.session.interaction import ClarifyReader, read_follow_up
from tux.cli.session.streaming import stream_reply


def explain_loop(
    client: ModelClient,
    suggestion: CommandSuggestion,
    context: list[dict[str, str]],
    question: str,
    reader: ClarifyReader,
) -> None:
    """Explain a proposal and answer follow-ups without changing or running it."""
    trail = list(context)
    request = explain_request(
        question, suggestion.title, suggestion.command, suggestion.description
    )
    while True:
        try:
            answer = stream_reply(client.explain_stream(request, trail))
        except ModelClientError as exc:
            print(f"tux: {exc}", file=sys.stderr)
            return
        trail.append({"role": "user", "content": request})
        trail.append({"role": "assistant", "content": answer})
        follow_up = read_follow_up(reader)
        if follow_up is None:
            return
        request = follow_up

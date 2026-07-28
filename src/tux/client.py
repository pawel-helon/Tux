"""HTTP client for an OpenAI-compatible local or remote model endpoint.

The client streams a request to ``/v1/chat/completions`` and returns the reply.
It supports two turn types, each shaped by its own pure module so the paths stay
separate: the **command** path (:mod:`tux.modes.command`) constrains the model with a
strict ``json_schema`` and parses an ordered ``steps`` plan, while
the **conversational** path (:mod:`tux.modes.chat`) omits the schema so a plain
question is answered as prose. A lightweight routing call decides which a turn
is. Shared request/stream helpers live in :mod:`tux.helpers`.

The HTTP transport is injectable so the whole flow can be exercised without a
live server: tests pass a callable that yields canned Server-Sent Event lines.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator

from tux.config import load_config
from tux.helpers import collect_stream, iter_stream
from tux.modes import chat, command

#: Endpoint default points at the KVM host gateway where ``llama-server`` runs.
#: Used as the fallback whenever the config file omits the corresponding key.
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:3b"
DEFAULT_TIMEOUT = 90.0

#: Capability tier assumed when provisioning has not recorded one. The dev/test
#: default endpoint is the full-capability ``llama-server``, so the matching
#: default variant is the full tier.
DEFAULT_VARIANT = "full"
DEFAULT_SYSTEM = "linux"

#: Built-in defaults keyed by config key, shared with the ``tux config`` command.
DEFAULTS = {
    "endpoint": DEFAULT_ENDPOINT,
    "model": DEFAULT_MODEL,
    "variant": DEFAULT_VARIANT,
    "system": DEFAULT_SYSTEM,
}

#: A transport opens the streaming request and yields raw SSE lines.
Transport = Callable[[str, dict, float], Iterable[str]]


class ModelClientError(Exception):
    """Raised when the model endpoint cannot be reached or its reply is unusable."""


def http_stream(url: str, payload: dict, timeout: float) -> Iterator[str]:
    """Yield decoded lines from a streaming POST to ``url``.

    Network failures surface as ``OSError`` (``urllib.error.URLError`` and
    ``TimeoutError`` both derive from it) for the caller to translate.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            yield raw.decode("utf-8")


class ModelClient:
    """Talks to a remote ``llama-server``, routing each turn to its path.

    The client owns only the endpoint configuration, the transport seam, and
    error translation; the request shaping and parsing live in :mod:`tux.modes.command`
    and :mod:`tux.modes.chat`. It stays stateless across turns — the caller owns the
    conversation thread and passes it in as ``history``.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        system: str = DEFAULT_SYSTEM,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport = http_stream,
    ) -> None:
        """Configure the client.

        Args:
            endpoint: Base URL of the ``llama-server`` (no trailing path).
            model: Model name passed through to the server.
            system: Linux environment profile used to select system prompts.
            timeout: Seconds to wait on the request before giving up.
            transport: Callable that performs the streaming request; injected in
                tests to supply canned SSE lines without a server.
        """
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._system = system
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_config(cls, transport: Transport = http_stream) -> "ModelClient":
        """Build a client from the config file, falling back to the defaults.

        Raises:
            ConfigError: If the config file exists but is not valid TOML.
        """
        overrides = load_config()
        return cls(
            endpoint=overrides.get("endpoint", DEFAULT_ENDPOINT),
            model=overrides.get("model", DEFAULT_MODEL),
            system=overrides.get("system", DEFAULT_SYSTEM),
            transport=transport,
        )

    def suggest(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> command.Plan:
        """Return an ordered guided plan of single-command steps for ``question``.

        Args:
            question: The plain-English task for this turn.
            history: Prior conversation turns as ``{"role", "content"}`` messages
                (alternating user/assistant), oldest first. When given, they are
                placed before this turn so a follow-up — or an in-walk re-plan
                driven by a step's output or a clarification — is answered in
                context.

        Raises:
            ModelClientError: If the endpoint is unreachable, times out, or the
                reply cannot be parsed into the expected fields.
        """
        payload = command.build_payload(self._model, self._system, question, history or [])
        content = self._stream_text(payload)
        try:
            return command.parse_plan(content)
        except ValueError as exc:
            raise ModelClientError(str(exc)) from exc

    def classify(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Return ``"command"`` or ``"chat"`` for the latest turn.

        A lightweight routing call decides the turn's type so the caller can send
        a command request down :meth:`suggest` and a conversational one down
        :meth:`converse`. This call carries no ``json_schema``.

        Raises:
            ModelClientError: If the endpoint is unreachable or times out.
        """
        payload = chat.build_classify_payload(self._model, question, history or [])
        return chat.interpret_route(self._stream_text(payload))

    def converse(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Return a free-form prose answer for a conversational turn.

        Unlike :meth:`suggest`, this omits the ``json_schema`` response format so
        the model can answer a plain question — including one that refers back to
        an earlier turn — as ordinary text. Implemented as the join of
        :meth:`converse_stream` so the buffered and streamed conversational paths
        produce the same text and raise the same errors.

        Raises:
            ModelClientError: If the endpoint is unreachable, times out, or
                returns an empty reply.
        """
        return "".join(self.converse_stream(question, history))

    def converse_stream(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> Iterator[str]:
        """Yield a free-form prose answer piece by piece as the model emits it.

        This is the streaming seam for the conversational path: each ``delta.content``
        piece is yielded as it arrives so the caller can print the reply while it is
        still being generated, rather than waiting for the whole paragraph. The
        client stays pure — it owns only the transport and error translation, never
        the terminal — so the presentation layer drives the spinner handoff and the
        live printing.

        The pieces are stripped to match the buffered path byte-for-byte: leading
        whitespace before the first visible token is dropped, trailing whitespace is
        held back, so the concatenation of the yielded pieces equals what
        :meth:`converse` returned before. A wholly empty or whitespace-only reply
        yields nothing and raises the empty-response error on exhaustion, so a caller
        that streamed real text never sees it.

        Raises:
            ModelClientError: If the endpoint is unreachable or times out (raised on
                the first or any later piece), or if the reply is empty.
        """
        return self._stream_prose(
            chat.build_chat_payload(self._model, self._system, question, history or [])
        )

    def explain(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Return a prose explanation of why a proposed command is the right one.

        The grammar-free sibling of :meth:`converse` for the explain affordance: it
        omits the ``json_schema`` so the model teaches in plain prose why a *given*
        command fits the question, going beyond its one-line description. Implemented
        as the join of :meth:`explain_stream` so the buffered and streamed explain
        paths produce the same text and raise the same errors.

        Raises:
            ModelClientError: If the endpoint is unreachable, times out, or returns
                an empty reply.
        """
        return "".join(self.explain_stream(question, history))

    def explain_stream(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> Iterator[str]:
        """Yield a prose 'why this command' explanation piece by piece.

        Mirrors :meth:`converse_stream` for the explain affordance — same streaming
        seam, same leading/trailing trimming, same transport-error translation and
        empty-response handling — differing only in the system prompt, which asks
        for the reasoning behind an already-proposed command rather than a general
        reply. The client stays pure; the presentation layer drives the spinner
        handoff and the live printing.

        Raises:
            ModelClientError: If the endpoint is unreachable or times out (raised on
                the first or any later piece), or if the reply is empty.
        """
        return self._stream_prose(
            chat.build_explain_payload(self._model, self._system, question, history or [])
        )

    def _stream_prose(self, payload: dict) -> Iterator[str]:
        """Yield a grammar-free prose reply piece by piece, trimmed like the buffered path.

        Shared by :meth:`converse_stream` and :meth:`explain_stream` so the two
        grammar-free streaming paths read the same SSE lines identically and cannot
        drift. Leading whitespace before the first visible token is dropped and
        trailing whitespace is held back, so the concatenation of the yielded pieces
        equals what the buffered join returns. A wholly empty or whitespace-only
        reply yields nothing and raises the empty-response error on exhaustion.

        Raises:
            ModelClientError: If the endpoint is unreachable or times out (raised on
                the first or any later piece), or if the reply is empty.
        """
        url = f"{self._endpoint}/v1/chat/completions"
        started = False
        pending = ""
        try:
            for content in iter_stream(self._transport(url, payload, self._timeout)):
                if not started:
                    content = content.lstrip()
                    if not content:
                        continue
                    started = True
                combined = pending + content
                visible = combined.rstrip()
                pending = combined[len(visible):]
                if visible:
                    yield visible
        except OSError as exc:
            raise ModelClientError(
                f"could not reach the model endpoint at {self._endpoint} ({exc})"
            ) from exc
        if not started:
            raise ModelClientError("the model returned an empty response")

    def _stream_text(self, payload: dict) -> str:
        """Stream a chat request and return the accumulated text content.

        Raises:
            ModelClientError: If the endpoint cannot be reached or times out.
        """
        url = f"{self._endpoint}/v1/chat/completions"
        try:
            return collect_stream(self._transport(url, payload, self._timeout))
        except OSError as exc:
            raise ModelClientError(
                f"could not reach the model endpoint at {self._endpoint} ({exc})"
            ) from exc

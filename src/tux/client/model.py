"""High-level model client API."""

from collections.abc import Iterator

from tux.modes import chat, command

from .config import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM,
    DEFAULT_TIMEOUT,
    load_client_options,
)
from .streaming import ModelClientError, stream_prose, stream_text
from .transport import Transport, http_stream


class ModelClient:
    """Talk to an OpenAI-compatible endpoint and route each turn."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        system: str = DEFAULT_SYSTEM,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport = http_stream,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._system = system
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_config(cls, transport: Transport = http_stream) -> "ModelClient":
        """Build a client from the config file, falling back to defaults."""
        options = load_client_options()
        return cls(transport=transport, **options)

    def suggest(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> command.Plan:
        """Return an ordered guided command plan for ``question``."""
        payload = command.build_payload(self._model, self._system, question, history or [])
        content = self._stream_text(payload)
        try:
            return command.parse_plan(content)
        except ValueError as exc:
            raise ModelClientError(str(exc)) from exc

    def classify(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Return ``command`` or ``chat`` for the latest turn."""
        payload = chat.build_classify_payload(self._model, question, history or [])
        return chat.interpret_route(self._stream_text(payload))

    def converse(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Return a buffered free-form conversational reply."""
        return "".join(self.converse_stream(question, history))

    def converse_stream(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> Iterator[str]:
        """Yield a free-form conversational reply piece by piece."""
        return self._stream_prose(
            chat.build_chat_payload(self._model, self._system, question, history or [])
        )

    def explain(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        """Return a buffered explanation for a proposed command."""
        return "".join(self.explain_stream(question, history))

    def explain_stream(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> Iterator[str]:
        """Yield an explanation for a proposed command piece by piece."""
        return self._stream_prose(
            chat.build_explain_payload(self._model, self._system, question, history or [])
        )

    def _stream_prose(self, payload: dict) -> Iterator[str]:
        return stream_prose(
            self._endpoint,
            payload,
            self._timeout,
            self._transport,
        )

    def _stream_text(self, payload: dict) -> str:
        return stream_text(
            self._endpoint,
            payload,
            self._timeout,
            self._transport,
        )

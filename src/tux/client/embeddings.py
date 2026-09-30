"""Embedding client for Ollama."""

from collections.abc import Callable

from .transport import http_post

EmbeddingTransport = Callable[[str, dict, float], dict]

EMBEDDING_MODEL = "embeddinggemma"
EMBEDDING_DIMENSIONS = 768


class EmbeddingClientError(Exception):
    """Raised when an embedding request fails or returns unusable data."""


class EmbeddingClient:
    """Generate embeddings through Ollama."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = EMBEDDING_MODEL,
        timeout: float = 90.0,
        transport: EmbeddingTransport = http_post,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._transport = transport

    def embed(self, text: str) -> list[float]:
        """Return a 768-dimensional embedding for ``text``."""
        payload = {
            "model": self._model,
            "input": text,
        }

        try:
            response = self._transport(
                f"{self._endpoint}/api/embed",
                payload,
                self._timeout,
            )
        except OSError as exc:
            raise EmbeddingClientError(
                f"could not reach the embedding endpoint at "
                f"{self._endpoint} ({exc})"
            ) from exc

        try:
            embedding = response["embeddings"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingClientError(
                "the embedding endpoint returned an invalid response"
            ) from exc

        if not isinstance(embedding, list):
            raise EmbeddingClientError(
                "the embedding endpoint returned an invalid vector"
            )

        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise EmbeddingClientError(
                f"expected {EMBEDDING_DIMENSIONS} dimensions, "
                f"got {len(embedding)}"
            )

        return embedding

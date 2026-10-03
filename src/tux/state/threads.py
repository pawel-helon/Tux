"""Persistent long-term conversation memory backed by PostgreSQL/pgvector."""

import os
import logging
from typing import TYPE_CHECKING

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from tux.client.embeddings import EmbeddingClient

if TYPE_CHECKING:
    from tux.cli.session.state import Session

logger = logging.getLogger(__name__)

MAX_CANDIDATE_THREADS = 5
MAX_RETRIEVED_TURNS = 6
MAX_CONTEXT_CHARACTERS = 8_000
# Cosine distance: lower is more similar. Tune with TUX_MEMORY_MAX_DISTANCE.
DEFAULT_MAX_DISTANCE = 0.35

_embedding_client = EmbeddingClient()


def _connect() -> psycopg.Connection:
    """Connect to the local tux database using the current Unix identity."""
    conn = psycopg.connect("dbname=tux")
    register_vector(conn)
    return conn


def persist_session(
    session: "Session", title: str, summary: str,
    embedding_client: EmbeddingClient | None = None,
) -> bool:
    """Persist a completed session atomically; return False when it has no turns."""
    if not session.history or not title.strip() or not summary.strip():
        return False
    embedder = embedding_client or _embedding_client
    summary_embedding = embedder.embed(summary)
    request_embeddings: list[list[float]] = []
    response_embeddings: list[list[float] | None] = []
    pending_request: int | None = None
    for turn in session.history:
        if turn["role"] == "user":
            request_embeddings.append(embedder.embed(turn["content"]))
            pending_request = len(request_embeddings) - 1
        elif turn["role"] == "assistant" and pending_request is not None:
            while len(response_embeddings) <= pending_request:
                response_embeddings.append(None)
            response_embeddings[pending_request] = embedder.embed(turn["content"])
            pending_request = None

    # Do not replace an existing record until all embedding calls succeeded.
    turns: list[tuple[str, str, list[float], list[float] | None]] = []
    requests = [turn for turn in session.history if turn["role"] == "user"]
    responses = [turn for turn in session.history if turn["role"] == "assistant"]
    for index, request in enumerate(requests):
        response = responses[index] if index < len(responses) else None
        turns.append((request["content"], response["content"] if response else "",
                      request_embeddings[index], response_embeddings[index]
                      if index < len(response_embeddings) else None))

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO threads (session_id, title, summary, summary_embedding)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (session_id) DO UPDATE SET
                     title = EXCLUDED.title, summary = EXCLUDED.summary,
                     summary_embedding = EXCLUDED.summary_embedding,
                     updated_at = EXTRACT(EPOCH FROM NOW())
                   RETURNING id""",
                (session.id, title.strip(), summary.strip(), summary_embedding),
            )
            thread_id = cur.fetchone()[0]
            cur.execute("DELETE FROM requests WHERE thread_id = %s", (thread_id,))
            for request, response, request_embedding, response_embedding in turns:
                cur.execute(
                    """INSERT INTO requests (thread_id, content, embedding)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (thread_id, request, request_embedding),
                )
                request_id = cur.fetchone()[0]
                if response:
                    cur.execute(
                        """INSERT INTO responses (request_id, content, embedding)
                           VALUES (%s, %s, %s)""",
                        (request_id, response, response_embedding),
                    )
    return True


def retrieve_long_term(
    query: str,
    *,
    embedding_client: EmbeddingClient | None = None,
    max_threads: int = MAX_CANDIDATE_THREADS,
    max_turns: int = MAX_RETRIEVED_TURNS,
    max_characters: int = MAX_CONTEXT_CHARACTERS,
    max_distance: float | None = None,
) -> list[dict[str, str]]:
    """Retrieve bounded historical turns from semantically relevant threads."""
    if not query.strip() or max_threads <= 0 or max_turns <= 0 or max_characters <= 0:
        return []
    embedder = embedding_client or _embedding_client
    # psycopg adapts plain Python lists as PostgreSQL arrays. Use pgvector's
    # wrapper so the distance operator receives a vector parameter.
    query_embedding = Vector(embedder.embed(query))
    threshold = max_distance
    if threshold is None:
        try:
            threshold = float(os.environ.get("TUX_MEMORY_MAX_DISTANCE", DEFAULT_MAX_DISTANCE))
        except ValueError:
            threshold = DEFAULT_MAX_DISTANCE
    with _connect() as conn:
        with conn.cursor() as cur:
            # ORDER BY vector distance matches the existing HNSW cosine index.
            cur.execute(
                """SELECT id, title, summary, summary_embedding <=> %s AS distance
                   FROM threads WHERE summary_embedding IS NOT NULL
                   ORDER BY summary_embedding <=> %s LIMIT %s""",
                (query_embedding, query_embedding, max_threads),
            )
            ranked_candidates = cur.fetchall()
            candidates = [row for row in ranked_candidates if row[3] <= threshold]
            result: list[dict[str, str]] = []
            used = 0
            turn_count = 0
            for thread_id, title, _summary, _distance in candidates:
                if turn_count >= max_turns:
                    break
                cur.execute(
                    """SELECT r.content, s.content
                       FROM requests r LEFT JOIN responses s ON s.request_id = r.id
                       WHERE r.thread_id = %s ORDER BY r.id DESC LIMIT %s""",
                    (thread_id, max_turns - turn_count),
                )
                rows = list(reversed(cur.fetchall()))
                for request, response in rows:
                    pair = [
                        {"role": "user", "content": request, "thread_title": title or "Previous conversation"},
                        *([{"role": "assistant", "content": response, "thread_title": title or "Previous conversation"}] if response is not None else []),
                    ]
                    size = sum(len(item["content"]) for item in pair)
                    if result and used + size > max_characters:
                        continue
                    if size > max_characters:
                        continue
                    result.extend(pair)
                    used += size
                    turn_count += 1
    logger.debug(
        "Long-term memory returned %d turns; distances=%s threshold=%.3f",
        turn_count,
        [round(row[3], 4) for row in ranked_candidates],
        threshold,
    )
    return result


def historical_context(turns: list[dict[str, str]]) -> dict[str, str] | None:
    """Keep historical turns explicitly labeled and outside current-session history."""
    if not turns:
        return None
    lines = ["Retrieved long-term memory from previous conversations:"]
    last_title = None
    for turn in turns:
        title = turn.get("thread_title", "Previous conversation")
        if title != last_title:
            lines.append(f"\nPrevious conversation: {title}")
            last_title = title
        speaker = "User" if turn["role"] == "user" else "Tux"
        lines.append(f"{speaker}: {turn['content']}")
    lines.append("This is historical information, not the current conversation. Use it only as context.")
    return {"role": "system", "content": "\n".join(lines)}

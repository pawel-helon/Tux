"""PostgreSQL-backed per-terminal conversation thread persistence."""

import json
import time
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from tux.client.embeddings import EmbeddingClient

from .paths import thread_path


THREAD_TTL = 8 * 60 * 60

_embedding_client = EmbeddingClient()


def _connect() -> psycopg.Connection:
    """Connect to the local tux database using the current Unix identity."""
    conn = psycopg.connect("dbname=tux")
    register_vector(conn)
    return conn


def load_thread(ppid: int) -> list[dict[str, str]]:
    """Return the stored conversation history for ``ppid``."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, shell_start, updated_at
                FROM threads
                WHERE ppid = %s
                """,
                (ppid,),
            )

            thread = cur.fetchone()

            if thread is None:
                return []

            thread_id, recorded_shell_start, updated_at = thread

            if _is_stale(recorded_shell_start, updated_at, ppid):
                return []

            cur.execute(
                """
                SELECT r.content, s.content
                FROM requests r
                LEFT JOIN responses s ON s.request_id = r.id
                WHERE r.thread_id = %s
                ORDER BY r.id
                """,
                (thread_id,),
            )

            history: list[dict[str, str]] = []

            for request, response in cur.fetchall():
                history.append(
                    {
                        "role": "user",
                        "content": request,
                    }
                )

                if response is not None:
                    history.append(
                        {
                            "role": "assistant",
                            "content": response,
                        }
                    )

            return history


def save_thread(ppid: int, history: list[dict[str, str]]) -> None:
    """Persist ``history`` for ``ppid``."""
    if not _valid_history(history):
        raise ValueError("invalid conversation history")

    shell_start = _shell_start(ppid)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO threads (ppid, shell_start)
                VALUES (%s, %s)
                ON CONFLICT (ppid)
                DO UPDATE SET
                    shell_start = EXCLUDED.shell_start,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """,
                (ppid, shell_start),
            )

            thread_id = cur.fetchone()[0]

            # Preserve the old snapshot-style behavior:
            # replace the stored history with the supplied history.
            cur.execute(
                "DELETE FROM requests WHERE thread_id = %s",
                (thread_id,),
            )

            request_id = None

            for turn in history:
                if turn["role"] == "user":
                    embedding = _embedding_client.embed(turn["content"])

                    cur.execute(
                        """
                        INSERT INTO requests (thread_id, content, embedding)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (thread_id, turn["content"], embedding),
                    )

                    request_id = cur.fetchone()[0]

                elif turn["role"] == "assistant" and request_id is not None:
                    embedding = _embedding_client.embed(turn["content"])

                    cur.execute(
                        """
                        INSERT INTO responses (request_id, content, embedding)
                        VALUES (%s, %s, %s)
                        """,
                        (request_id, turn["content"], embedding),
                    )


def clear_thread(ppid: int) -> None:
    """Discard the stored thread for ``ppid``."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM threads WHERE ppid = %s",
                (ppid,),
            )


def _read(path: Path) -> dict | None:
    """Read a JSON state file for compatibility with the former API."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    text = text.strip()

    if not text:
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    return data if isinstance(data, dict) else None


def _is_stale(
    recorded_shell_start: str | None,
    updated_at: float,
    ppid: int,
) -> bool:
    """Return whether a stored thread is stale or belongs to a reused PID."""
    if time.time() - updated_at > THREAD_TTL:
        return True

    current = _shell_start(ppid)

    return (
        recorded_shell_start is not None
        and current is not None
        and recorded_shell_start != current
    )


def _valid_history(history: object) -> bool:
    """Return whether ``history`` is a list of well-formed chat messages."""
    if not isinstance(history, list):
        return False

    return all(
        isinstance(turn, dict)
        and isinstance(turn.get("role"), str)
        and isinstance(turn.get("content"), str)
        for turn in history
    )


def _shell_start(pid: int) -> str | None:
    """Return the process start time of ``pid`` from ``/proc``, or ``None``."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        after_comm = stat[stat.rindex(")") + 1 :].split()
        return after_comm[19]
    except (ValueError, IndexError):
        return None

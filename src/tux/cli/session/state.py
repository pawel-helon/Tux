"""In-memory state owned by one Tux process invocation."""

from dataclasses import dataclass, field
import time
from uuid import uuid4


@dataclass
class Session:
    """Conversation history for a single Tux session."""

    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list[dict[str, str]] = field(default_factory=list)

    def add_turn(self, question: str, answer: dict[str, str]) -> None:
        """Append one completed user and assistant turn."""
        self.history.extend(
            ({"role": "user", "content": question}, answer)
        )
        self.updated_at = time.time()

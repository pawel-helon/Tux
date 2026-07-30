"""Run-record model and on-disk serialization format."""

from dataclasses import dataclass

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
_FIELD_SEP = "\t"
_RECORD_MARKER = "v2"
NO_DESCRIPTION = "(no description recorded)"


@dataclass(frozen=True)
class RunRecord:
    """One recorded command execution."""

    timestamp: str
    status: int
    description: str
    command: str


def _one_line(text: str) -> str:
    """Collapse record-breaking whitespace in a middle field."""
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def format_run(record: RunRecord) -> str:
    """Format a run record as one tab-separated log line."""
    description = _one_line(record.description)
    return _FIELD_SEP.join(
        (_RECORD_MARKER, record.timestamp, str(record.status), description, record.command)
    )


def parse_run(line: str) -> RunRecord | None:
    """Parse one current or legacy log line, returning ``None`` if malformed."""
    text = line.rstrip("\n")
    if text.startswith(_RECORD_MARKER + _FIELD_SEP):
        fields = text.split(_FIELD_SEP, 4)
        if len(fields) < 5:
            return None
        _, timestamp, status_text, description, command = fields
    else:
        fields = text.split(_FIELD_SEP, 2)
        if len(fields) < 3:
            return None
        timestamp, status_text, command = fields
        description = NO_DESCRIPTION
    try:
        status = int(status_text)
    except ValueError:
        return None
    return RunRecord(timestamp, status, description, command)

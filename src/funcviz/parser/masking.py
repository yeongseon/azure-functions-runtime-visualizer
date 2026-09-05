"""Secret redaction for log text before a trace leaves the machine (PRD §16).

A trace embeds raw log lines and may be pasted into an issue or shown in a
presentation, so v0.1 masks the four secret classes §16 names -- authorization
headers, function keys, connection strings, and storage/shared-access
credentials -- as a pure, parse-time regex pass. Every match keeps its
surrounding key visible and replaces only the secret *value* with a typed
``[REDACTED:kind]`` marker, so a redacted trace announces what it hid rather
than silently dropping content (a quietly shortened trace is worse than one
that shows the redaction).

The pass is pure and standalone: the CLI applies it to records *before*
``parse_trace`` (default on, ``--no-mask`` off), keeping the parser itself free
of redaction policy. Masking rewrites both ``LogRecord.message`` (which becomes
each event's ``raw``) and ``fields["content"]`` (which extraction reads), and is
scoped so it never touches the invocation IDs, durations, status codes, ports,
or GUIDs the extractor depends on. Re-masking already-masked text is a no-op.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import LogRecord
from .regexes import redact_secrets


def mask_text(text: str) -> str:
    """Redact every known secret value in ``text``; idempotent on marked text.

    The redaction patterns live in :mod:`.regexes` (the parser's sole ``re``
    owner, PRD R1); this thin wrapper keeps masking's public name stable.
    """
    return redact_secrets(text)


def mask_record(record: LogRecord) -> LogRecord:
    """Return a copy of ``record`` with secrets masked in message and content."""
    fields = dict(record.fields)
    content = fields.get("content")
    if isinstance(content, str):
        fields["content"] = mask_text(content)
    return LogRecord(
        message=mask_text(record.message),
        timestamp=record.timestamp,
        fields=fields,
    )


def mask_records(records: Iterable[LogRecord]) -> list[LogRecord]:
    """Mask secrets across a stream of records (see :func:`mask_record`)."""
    return [mask_record(record) for record in records]


__all__ = ["mask_record", "mask_records", "mask_text"]

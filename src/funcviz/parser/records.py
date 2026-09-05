"""Physical log lines -> logical records, folding multiline HTTP JSON blocks.

The Core Tools HTTP request/response lines emit a pretty-printed JSON body where
every physical line carries its own ``[timestamp]`` prefix. This stage folds
such a block back into a single :class:`~funcviz.models.LogRecord` whose message
is the joined original text, so no downstream extractor needs multiline
awareness. Only known HTTP request/response blocks are folded; unrelated JSON
config dumps in startup noise are left as-is.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..models import LogRecord
from .regexes import is_http_request_start, is_http_response_start, split_timestamp


def from_log_text(text: str) -> list[LogRecord]:
    records: list[LogRecord] = []
    for line in text.splitlines():
        ts, content = split_timestamp(line)
        records.append(
            LogRecord(message=line, timestamp=None, fields={"content": content, "ts": ts or ""})
        )
    return records


def record_content(record: LogRecord) -> str:
    """The log-message body, preferring a pre-split ``fields['content']``.

    A raw ``LogRecord(message=line)`` from an adapter that did not pre-split is
    supported: the ``[timestamp]`` prefix is stripped from ``message`` on demand
    so ``parse_trace`` honors its ``Iterable[LogRecord]`` contract regardless of
    whether ``from_log_text`` was used.
    """
    value = record.fields.get("content")
    if isinstance(value, str):
        return value
    _, content = split_timestamp(record.message)
    return content


def record_timestamp(record: LogRecord) -> str:
    """The record's ISO timestamp, resolved in fields-first order (PRD FR-2.1).

    Structured ``fields['ts']`` wins; a structured ``LogRecord.timestamp`` is
    next; only then is the ``[timestamp]`` prefix parsed out of ``message``. This
    lets adapters carry timestamps as data while a bare ``message``-only record
    still yields a usable timestamp for interval derivation.
    """
    value = record.fields.get("ts")
    if isinstance(value, str) and value:
        return value
    if record.timestamp is not None:
        return _format_timestamp(record.timestamp)
    ts, _ = split_timestamp(record.message)
    return ts or ""


def _format_timestamp(moment: datetime) -> str:
    return moment.isoformat()


def fold_http_blocks(records: Iterable[LogRecord]) -> list[LogRecord]:
    items = list(records)
    folded: list[LogRecord] = []
    i = 0
    while i < len(items):
        record = items[i]
        content = record_content(record)
        if is_http_request_start(content) or is_http_response_start(content):
            depth = content.count("{") - content.count("}")
            block = [record]
            j = i + 1
            while depth > 0 and j < len(items):
                nxt = items[j]
                nxt_content = record_content(nxt)
                depth += nxt_content.count("{") - nxt_content.count("}")
                block.append(nxt)
                j += 1
            joined_message = "\n".join(b.message for b in block)
            joined_content = "\n".join(record_content(b) for b in block)
            folded.append(
                LogRecord(
                    message=joined_message,
                    timestamp=None,
                    fields={"content": joined_content, "ts": record_timestamp(record)},
                )
            )
            i = j
        else:
            folded.append(record)
            i += 1
    return folded

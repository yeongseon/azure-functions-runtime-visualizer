"""App Insights query-result adapter (issue #67, PRD §5.1).

Turns the JSON output of ``az monitor app-insights query`` into the same
:class:`LogRecord` stream ``from_log_text`` produces, so the pure parser runs
with zero edits (FR-2). Per the discovery in issue #66:

- ``message`` carries the host log strings (Executing/Executed bookends), so
  the v0.1 event-mapping regexes transfer as-is;
- ``timestamp`` orders rows globally (the adapter sorts defensively even
  though the reference query orders ascending);
- raw python-worker verbose lines are NOT ingested by App Insights, so a
  trace built from an export legitimately lacks worker-internal detail — the
  parser's lane derivation already reports that honestly as ``unknown``.

The adapter stays offline: it reads a file the user exported; it performs no
auth, no network calls, and no Azure SDK dependency.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone

from .models import LogRecord, Trace, TraceInput

_SOURCE = "app-insights-query"
_ADAPTER = "AppInsightsQueryAdapter"
_ADAPTER_VERSION = "0.1"


def records_from_query_result(data: Mapping[str, object]) -> list[LogRecord]:
    """Flatten ``az monitor app-insights query -o json`` output to records.

    Expected shape: ``{"tables": [{"columns": [{"name": ...}, ...],
    "rows": [[...], ...]}]}`` with the reference projection from PRD §5.1
    (``timestamp, itemType, message, name, customDimensions``). Rows without
    a message cannot match any event mapping and are dropped.
    """
    tables = data.get("tables")
    if not isinstance(tables, Sequence) or isinstance(tables, (str, bytes)):
        raise ValueError(
            "App Insights export has no 'tables' array (expected az CLI -o json output)"
        )
    records: list[LogRecord] = []
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        columns = table.get("columns")
        rows = table.get("rows")
        if not isinstance(columns, Sequence) or not isinstance(rows, Sequence):
            continue
        names: list[str | None] = []
        for c in columns:
            name = c.get("name") if isinstance(c, Mapping) else None
            names.append(name if isinstance(name, str) else None)
        index: dict[str, int] = {name: i for i, name in enumerate(names) if name}
        for row in rows:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                continue
            ts = _cell(row, index, "timestamp")
            message = _cell(row, index, "message")
            if not isinstance(message, str) or not message.strip():
                continue
            if not isinstance(ts, str) or not ts.strip():
                raise ValueError(
                    "App Insights export has a message-bearing row without a timestamp; "
                    "the reference query must project timestamp"
                )
            ts_text = _normalize_timestamp(ts)
            content = message
            records.append(
                LogRecord(
                    message=(f"[{ts_text}] " if ts_text else "") + content,
                    timestamp=None,
                    fields={
                        "content": content,
                        "ts": ts_text,
                        "itemType": _cell(row, index, "itemType"),
                        "ai": _custom_dimensions(_cell(row, index, "customDimensions")),
                    },
                )
            )
    if not records:
        raise ValueError("App Insights export contains no message-bearing rows")
    records.sort(key=_sort_key)
    return records


def relabel_input(trace: Trace) -> Trace:
    """Mark the trace as App-Insights-sourced without touching parser logic."""
    return replace(
        trace,
        input=TraceInput(source=_SOURCE, adapter=_ADAPTER, adapter_version=_ADAPTER_VERSION),
    )


def with_host_instances(trace: Trace, records: Sequence[LogRecord]) -> Trace:
    """Annotate the trace when an export spans multiple host instances (#68).

    A single invocation lives on one host instance, so distinct
    ``HostInstanceId`` values among an export's rows mean the query reached
    beyond one invocation's story (or caught special-controller noise). The
    trace is still built — ordering is timestamp-primary — but the span is
    recorded in ``metadata.hostInstances`` instead of silently implying one
    instance. Existing metadata (e.g. the #84 incomplete marker) is preserved.
    """
    ids: list[str] = []
    for record in records:
        ai = record.fields.get("ai")
        if not isinstance(ai, Mapping):
            continue
        value = ai.get("HostInstanceId")
        if isinstance(value, str) and value and value not in ids:
            ids.append(value)
    if len(ids) < 2:
        return trace
    metadata = dict(trace.metadata)
    metadata["hostInstances"] = ids
    return replace(trace, metadata=metadata)


def _cell(row: Sequence[object], index: Mapping[str, int], name: str) -> object:
    i = index.get(name)
    if i is None or i >= len(row):
        return None
    return row[i]


def _custom_dimensions(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _normalize_timestamp(raw: str) -> str:
    """Any ISO-8601 App Insights timestamp as UTC millisecond precision.

    Handles the observed shapes plus defensive ones: ``Z`` suffix, ISO offsets
    (``+09:00`` — converted to the true UTC instant, never dropped), and
    100-nanosecond ticks (truncated to microseconds, then milliseconds).
    Stdlib-only so Python 3.10's stricter ``fromisoformat`` is respected: the
    ``Z`` suffix is stripped before parsing and UTC is re-applied explicitly.
    """
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1]
    if "." in text:
        head, rest = text.split(".", 1)
        digits: list[str] = []
        i = 0
        while i < len(rest) and rest[i].isdigit():
            digits.append(rest[i])
            i += 1
        text = head + "." + ("".join(digits) + "000000")[:6] + rest[i:]
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"App Insights row has an unparseable timestamp: {raw!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _sort_key(record: LogRecord) -> tuple[int, str]:
    ts = record.fields.get("ts")
    return (0, ts) if isinstance(ts, str) and ts else (1, "")

"""Pure parser entry point: Iterable[LogRecord] -> Trace (PRD FR-2).

``parse_trace`` performs no file or network I/O and knows nothing about the CLI.
It folds multiline records, extracts the frozen event set, derives intervals and
lane statuses, and reads only runtime metadata that is present in the log itself.
Source-file text (application.sourceText) is intentionally left unset here: the
parser never reads the filesystem, so a caller that wants source context loads it
in a separate layer.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import (
    Application,
    Outcome,
    Runtime,
    Trace,
    TraceInput,
)
from ..models import LogRecord as LogRecord
from .derive import (
    build_failures,
    build_intervals,
    build_lanes,
    finalize_events,
    synthesize_application_events,
)
from .events import extract_events
from .records import fold_http_blocks, record_content
from .records import from_log_text as _from_log_text
from .regexes import (
    find_core_tools_version,
    find_function_path,
    find_runtime_version,
    find_worker_runtime,
    match_invocation_started,
)

_ADAPTER = "CoreToolsLogAdapter"
_ADAPTER_VERSION = "0.1"
_SOURCE = "core-tools-log"


def from_log_text(text: str) -> list[LogRecord]:
    return _from_log_text(text)


def parse_trace(
    log_records: Iterable[LogRecord],
    *,
    trace_id: str,
    outcome: Outcome = Outcome.SUCCESS,
) -> Trace:
    folded = fold_http_blocks(log_records)
    raw_events = synthesize_application_events(extract_events(folded))
    finalized = finalize_events(raw_events)
    intervals = build_intervals(finalized, raw_events)
    lanes = build_lanes(finalized)
    failures = build_failures(finalized, raw_events)

    meta = _scan_metadata(folded)
    completed = next((r for r in raw_events if r["event"] == "InvocationCompleted"), None)
    resolved_outcome = _resolve_outcome(completed, raw_events, outcome)

    return Trace(
        trace_id=trace_id,
        outcome=resolved_outcome,
        input=TraceInput(source=_SOURCE, adapter=_ADAPTER, adapter_version=_ADAPTER_VERSION),
        runtime=Runtime(
            environment="local",
            language=meta.get("language", "python"),
            trigger="http",
            core_tools_version=meta.get("coreToolsVersion"),
            host_version=meta.get("hostVersion"),
        ),
        lanes=lanes,
        events=finalized,
        intervals=intervals,
        application=_application_from(meta),
        failures=failures,
    )


def _resolve_outcome(
    completed: dict[str, object] | None,
    raw_events: list[dict[str, object]],
    fallback: Outcome,
) -> Outcome:
    if completed is not None:
        return _outcome_from(completed)
    if any(r["event"] == "WorkerIndexingFailed" for r in raw_events):
        return Outcome.FAILURE
    return fallback


def _application_from(meta: dict[str, str]) -> Application | None:
    name = meta.get("functionName")
    if name is None:
        return None
    return Application(function_name=name, source_file=meta.get("sourceFile"))


def _outcome_from(completed: dict[str, object]) -> Outcome:
    return Outcome.SUCCESS if completed.get("result") == "Succeeded" else Outcome.FAILURE


def _scan_metadata(folded: Iterable[LogRecord]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for record in folded:
        content = record_content(record)
        _put(meta, "language", find_worker_runtime(content))
        _put(meta, "coreToolsVersion", find_core_tools_version(content))
        _put(meta, "hostVersion", find_runtime_version(content))
        path = find_function_path(content)
        if path is not None:
            meta.setdefault("sourceFile", path.rsplit("/", 1)[-1])
        started = match_invocation_started(content)
        if started is not None:
            meta.setdefault("functionName", started["name"])
    return meta


def _put(meta: dict[str, str], key: str, value: str | None) -> None:
    if value is not None:
        meta.setdefault(key, value)


__all__ = ["from_log_text", "parse_trace"]

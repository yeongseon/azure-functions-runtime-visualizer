"""Extract lifecycle events from folded records, in log order.

The success vocabulary is exactly what survived the Phase 0 coverage matrix
(docs/event-coverage.md): HttpRequestReceived, InvocationStarted,
WorkerReceivedInvocation, InvocationCompleted, HttpResponseReturned. A log with
no invocation (issue #9) instead yields the worker-startup failure vocabulary:
HostBuildStarted, WorkerIndexingStarted, PythonWorkerStarted,
WorkerMetadataRequested, WorkerIndexingFailed. This stage owns no regexes; it
delegates every log-shape decision to :mod:`.regexes` and emits order-preserving
intermediate dicts that :mod:`.derive` finalizes.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Confidence, Lane, LogRecord
from .records import record_content, record_timestamp
from .regexes import (
    find_http_duration,
    find_http_request_id,
    find_module_not_found,
    is_host_build_started,
    is_http_request_start,
    is_http_response_start,
    is_python_worker_started,
    is_worker_failed_to_index,
    is_worker_indexing_started,
    match_invocation_completed,
    match_invocation_started,
    match_worker_invocation,
    match_worker_metadata_request,
)


def extract_events(folded: Iterable[LogRecord]) -> list[dict[str, object]]:
    records = list(folded)
    success = extract_success_events(records)
    if any(e["event"] == "InvocationCompleted" for e in success):
        return success
    failure = extract_worker_startup_failure_events(records)
    return failure or success


def extract_success_events(folded: Iterable[LogRecord]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for record in folded:
        content = record_content(record)
        ts = record_timestamp(record)

        if is_http_request_start(content):
            http_id = find_http_request_id(content)
            events.append(
                {
                    "event": "HttpRequestReceived",
                    "lane": Lane.CLIENT,
                    "confidence": Confidence.INFERRED,
                    "timestamp": ts,
                    "raw": record.message,
                    "httpRequestId": http_id,
                }
            )
            continue

        if is_http_response_start(content):
            http_id = find_http_request_id(content)
            events.append(
                {
                    "event": "HttpResponseReturned",
                    "lane": Lane.CLIENT,
                    "confidence": Confidence.INFERRED,
                    "timestamp": ts,
                    "raw": record.message,
                    "httpRequestId": http_id,
                    "httpDuration": find_http_duration(content),
                }
            )
            continue

        started = match_invocation_started(content)
        if started is not None:
            events.append(
                {
                    "event": "InvocationStarted",
                    "lane": Lane.HOST,
                    "confidence": Confidence.OBSERVED,
                    "timestamp": ts,
                    "raw": record.message,
                    "invocationId": started["invocation"],
                }
            )
            continue

        worker = match_worker_invocation(content)
        if worker is not None:
            events.append(
                {
                    "event": "WorkerReceivedInvocation",
                    "lane": Lane.PYTHON_WORKER,
                    "confidence": Confidence.OBSERVED,
                    "timestamp": ts,
                    "raw": record.message,
                    "workerRequestId": worker["worker"],
                    "invocationId": worker["invocation"],
                }
            )
            continue

        completed = match_invocation_completed(content)
        if completed is not None:
            events.append(
                {
                    "event": "InvocationCompleted",
                    "lane": Lane.HOST,
                    "confidence": Confidence.OBSERVED,
                    "timestamp": ts,
                    "raw": record.message,
                    "invocationId": completed["invocation"],
                    "result": completed["result"],
                    "hostDuration": completed["duration"],
                }
            )
            continue

    return events


def extract_worker_startup_failure_events(
    folded: Iterable[LogRecord],
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    seen: set[str] = set()
    module_message: str | None = None

    def emit(name: str, lane: Lane, record: LogRecord, ts: str, **extra: object) -> None:
        if name in seen:
            return
        seen.add(name)
        events.append(
            {
                "event": name,
                "lane": lane,
                "confidence": Confidence.OBSERVED,
                "timestamp": ts,
                "raw": record.message,
                **extra,
            }
        )

    for record in folded:
        content = record_content(record)
        ts = record_timestamp(record)

        module = find_module_not_found(content)
        if module is not None and module_message is None:
            module_message = f"ModuleNotFoundError: No module named '{module}'"

        if is_host_build_started(content):
            emit("HostBuildStarted", Lane.HOST, record, ts)
            continue
        if is_worker_indexing_started(content):
            emit("WorkerIndexingStarted", Lane.HOST, record, ts)
            continue
        if is_python_worker_started(content):
            emit("PythonWorkerStarted", Lane.PYTHON_WORKER, record, ts)
            continue
        metadata = match_worker_metadata_request(content)
        if metadata is not None:
            emit(
                "WorkerMetadataRequested",
                Lane.PYTHON_WORKER,
                record,
                ts,
                workerRequestId=metadata["worker"],
            )
            continue
        if is_worker_failed_to_index(content):
            emit(
                "WorkerIndexingFailed",
                Lane.PYTHON_WORKER,
                record,
                ts,
                failureMessage=module_message,
            )
            break

    if "WorkerIndexingFailed" not in seen:
        return []
    return events

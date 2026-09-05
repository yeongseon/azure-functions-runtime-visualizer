"""Extract the five frozen events from folded records, in log order.

The event vocabulary is exactly what survived the Phase 0 coverage matrix
(docs/event-coverage.md): HttpRequestReceived, InvocationStarted,
WorkerReceivedInvocation, InvocationCompleted, HttpResponseReturned. This stage
owns no regexes; it delegates every log-shape decision to :mod:`.regexes` and
emits order-preserving intermediate dicts that :mod:`.derive` finalizes.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Confidence, Lane, LogRecord
from .records import record_content, record_timestamp
from .regexes import (
    find_http_duration,
    find_http_request_id,
    is_http_request_start,
    is_http_response_start,
    match_invocation_completed,
    match_invocation_started,
    match_worker_invocation,
)


def extract_events(folded: Iterable[LogRecord]) -> list[dict[str, object]]:
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

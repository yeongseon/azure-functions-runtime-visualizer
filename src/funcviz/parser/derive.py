"""Derive finalized events, intervals, and lane statuses from raw extractions.

This stage is regex-free and purely arithmetic/relational: it assigns event ids
and sequences, computes ``elapsedMs`` relative to the first event, reconstructs
the three provenance-tagged invocation/HTTP intervals, and infers lane
reachability. Duration provenance (log-delta vs host-reported vs http-reported)
is preserved deliberately per docs/event-coverage.md rather than collapsed.
"""

from __future__ import annotations

from datetime import datetime

from ..models import (
    Confidence,
    Event,
    Failure,
    Interval,
    IntervalSource,
    Lane,
    Lanes,
    LaneState,
    LaneStatus,
)

_CLIENT_REASON = "Derived from host HTTP request/response lines."
_APPLICATION_REASON = "User-code entry/exit is not separately logged."

_FAIL_CLIENT_REASON = "No HTTP request was observed before worker indexing failed."
_FAIL_HOST_REASON = (
    "Host built the app and requested worker metadata; retry-loop logs after the failure "
    "are omitted."
)
_FAIL_WORKER_REASON = "Python worker failed while indexing functions."
_FAIL_APPLICATION_REASON = (
    "No invocation reached the function body; indexing failed before the function was loaded."
)


def _to_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _elapsed_ms(ts: str, base: str) -> int:
    return round((_to_dt(ts) - _to_dt(base)).total_seconds() * 1000)


def finalize_events(raw_events: list[dict[str, object]]) -> list[Event]:
    if not raw_events:
        return []
    base = str(raw_events[0]["timestamp"])
    events: list[Event] = []
    for n, raw in enumerate(raw_events):
        ts = str(raw["timestamp"])
        raw_text = raw["raw"]
        events.append(
            Event(
                id=f"e{n}",
                sequence=n,
                lane=_as_lane(raw["lane"]),
                event=str(raw["event"]),
                confidence=_as_confidence(raw["confidence"]),
                raw=raw_text if isinstance(raw_text, str) else None,
                timestamp=ts,
                elapsed_ms=_elapsed_ms(ts, base),
                http_request_id=_opt_str(raw.get("httpRequestId")),
                worker_request_id=_opt_str(raw.get("workerRequestId")),
                invocation_id=_opt_str(raw.get("invocationId")),
            )
        )
    return events


def build_intervals(events: list[Event], raw_events: list[dict[str, object]]) -> list[Interval]:
    by_name = {e.event: e for e in events}
    raw_by_name = {str(r["event"]): r for r in raw_events}
    intervals: list[Interval] = []

    started = by_name.get("InvocationStarted")
    completed = by_name.get("InvocationCompleted")
    if started is not None and completed is not None and started.timestamp and completed.timestamp:
        intervals.append(
            Interval(
                id="i1",
                label="Invocation (host log delta)",
                lane=Lane.HOST,
                kind="invocation",
                start_event=started.id,
                end_event=completed.id,
                duration_ms=_elapsed_ms(completed.timestamp, started.timestamp),
                source=IntervalSource.LOG_DELTA,
                confidence=Confidence.OBSERVED,
            )
        )
        host_duration = _opt_str(raw_by_name["InvocationCompleted"].get("hostDuration"))
        if host_duration is not None:
            intervals.append(
                Interval(
                    id="i2",
                    label="Invocation (host-reported)",
                    lane=Lane.HOST,
                    kind="invocation",
                    start_event=started.id,
                    end_event=completed.id,
                    duration_ms=int(host_duration),
                    source=IntervalSource.HOST_REPORTED,
                    confidence=Confidence.OBSERVED,
                    raw=f"Duration={host_duration}ms",
                )
            )

    request = by_name.get("HttpRequestReceived")
    response = by_name.get("HttpResponseReturned")
    if request is not None and response is not None:
        http_duration = _opt_str(raw_by_name["HttpResponseReturned"].get("httpDuration"))
        if http_duration is not None:
            intervals.append(
                Interval(
                    id="i3",
                    label="HTTP request",
                    lane=Lane.CLIENT,
                    kind="http",
                    start_event=request.id,
                    end_event=response.id,
                    duration_ms=int(http_duration),
                    source=IntervalSource.HTTP_REPORTED,
                    confidence=Confidence.INFERRED,
                    raw=f'"duration": "{http_duration}"',
                )
            )
    return intervals


def build_lanes(events: list[Event]) -> Lanes:
    failed = next((e for e in events if e.event == "WorkerIndexingFailed"), None)
    if failed is not None:
        return Lanes(
            client=LaneStatus(
                LaneState.NOT_REACHED, Confidence.OBSERVED, reason=_FAIL_CLIENT_REASON
            ),
            host=LaneStatus(LaneState.REACHED, Confidence.OBSERVED, reason=_FAIL_HOST_REASON),
            python_worker=LaneStatus(
                LaneState.FAILED_HERE,
                Confidence.OBSERVED,
                reason=_FAIL_WORKER_REASON,
                failure_event=failed.id,
            ),
            application=LaneStatus(
                LaneState.NOT_REACHED, Confidence.OBSERVED, reason=_FAIL_APPLICATION_REASON
            ),
        )

    names = {e.event for e in events}
    completed = next((e for e in events if e.event == "InvocationCompleted"), None)
    application_reached = completed is not None

    client_reached = bool(names & {"HttpRequestReceived", "HttpResponseReturned"})
    host_reached = bool(names & {"InvocationStarted", "InvocationCompleted"})
    worker_reached = "WorkerReceivedInvocation" in names

    return Lanes(
        client=LaneStatus(
            LaneState.REACHED if client_reached else LaneState.NOT_REACHED,
            Confidence.INFERRED,
            reason=_CLIENT_REASON,
        ),
        host=LaneStatus(
            LaneState.REACHED if host_reached else LaneState.NOT_REACHED,
            Confidence.OBSERVED,
        ),
        python_worker=LaneStatus(
            LaneState.REACHED if worker_reached else LaneState.NOT_REACHED,
            Confidence.OBSERVED,
        ),
        application=LaneStatus(
            LaneState.REACHED if application_reached else LaneState.NOT_REACHED,
            Confidence.INFERRED,
            reason=_APPLICATION_REASON,
        ),
    )


def build_failures(events: list[Event], raw_events: list[dict[str, object]]) -> list[Failure]:
    failed = next((e for e in events if e.event == "WorkerIndexingFailed"), None)
    if failed is None:
        return []
    raw_by_name = {str(r["event"]): r for r in raw_events}
    message = _opt_str(raw_by_name.get("WorkerIndexingFailed", {}).get("failureMessage"))
    return [Failure(event=failed.id, kind="worker-indexing", message=message)]


def _as_lane(value: object) -> Lane:
    return value if isinstance(value, Lane) else Lane(str(value))


def _as_confidence(value: object) -> Confidence:
    return value if isinstance(value, Confidence) else Confidence(str(value))


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None

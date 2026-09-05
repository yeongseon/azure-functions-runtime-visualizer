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

_INVOCATION_FAILED_HOST_REASON = (
    "The host reported the invocation failed; the run stopped in the function body."
)


_APPLICATION_INTERVAL_LABEL = "Application (inferred window)"


def synthesize_application_events(
    raw_events: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Insert the two inferred ``application``-lane window events (PRD FR-4).

    The application lane has no dedicated log line (docs/event-coverage.md): user
    code entry/exit is inferred from the surrounding observed events. When a
    trace pairs a ``WorkerReceivedInvocation`` with a matching later
    ``InvocationCompleted`` (same ``invocationId``), we synthesize an
    ``ApplicationFunctionStarted`` immediately after the worker received the
    invocation and, when the invocation succeeded, an
    ``ApplicationFunctionCompleted`` immediately before the host reported
    completion, so the lane owns the markers FR-4 requires. These are
    inferences, not log records, so they carry ``confidence = INFERRED`` and
    ``raw = None``. When the invocation failed (``result == "Failed"``) we
    synthesize only ``ApplicationFunctionStarted``: user code was entered but
    never completed normally, so fabricating a completion marker would imply a
    success that did not happen. Worker-startup failure traces (indexing never
    reached the function body) synthesize nothing and leave the application lane
    empty.
    """
    names = {str(e["event"]) for e in raw_events}
    if names & {"ApplicationFunctionStarted", "ApplicationFunctionCompleted"}:
        return list(raw_events)

    worker_idx = next(
        (i for i, e in enumerate(raw_events) if e["event"] == "WorkerReceivedInvocation"), None
    )
    completed_idx = next(
        (i for i, e in enumerate(raw_events) if e["event"] == "InvocationCompleted"), None
    )
    if worker_idx is None or completed_idx is None or worker_idx >= completed_idx:
        return list(raw_events)

    worker = raw_events[worker_idx]
    completed = raw_events[completed_idx]
    if worker.get("invocationId") != completed.get("invocationId"):
        return list(raw_events)

    invocation_id = worker.get("invocationId")
    invocation_failed = completed.get("result") == "Failed"

    started = {
        "event": "ApplicationFunctionStarted",
        "lane": Lane.APPLICATION,
        "confidence": Confidence.INFERRED,
        "timestamp": worker["timestamp"],
        "raw": None,
        "invocationId": invocation_id,
    }
    finished = {
        "event": "ApplicationFunctionCompleted",
        "lane": Lane.APPLICATION,
        "confidence": Confidence.INFERRED,
        "timestamp": completed["timestamp"],
        "raw": None,
        "invocationId": invocation_id,
    }

    result: list[dict[str, object]] = []
    for event in raw_events:
        if event is completed and not invocation_failed:
            result.append(finished)
        result.append(event)
        if event is worker:
            result.append(started)
    return result


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

    app_started = by_name.get("ApplicationFunctionStarted")
    app_completed = by_name.get("ApplicationFunctionCompleted")
    if (
        app_started is not None
        and app_completed is not None
        and app_started.timestamp
        and app_completed.timestamp
    ):
        intervals.append(
            Interval(
                id="i4",
                label=_APPLICATION_INTERVAL_LABEL,
                lane=Lane.APPLICATION,
                kind="application",
                start_event=app_started.id,
                end_event=app_completed.id,
                duration_ms=_elapsed_ms(app_completed.timestamp, app_started.timestamp),
                source=IntervalSource.INFERRED,
                confidence=Confidence.INFERRED,
            )
        )
    return intervals


def build_lanes(events: list[Event], raw_events: list[dict[str, object]]) -> Lanes:
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
    application_reached = "ApplicationFunctionStarted" in names

    client_reached = bool(names & {"HttpRequestReceived", "HttpResponseReturned"})
    host_reached = bool(names & {"InvocationStarted", "InvocationCompleted"})
    worker_reached = "WorkerReceivedInvocation" in names

    invocation_failure = _failed_invocation_event(events, raw_events)
    if invocation_failure is not None:
        host_status = LaneStatus(
            LaneState.FAILED_HERE,
            Confidence.OBSERVED,
            reason=_INVOCATION_FAILED_HOST_REASON,
            failure_event=invocation_failure,
        )
    else:
        host_status = LaneStatus(
            LaneState.REACHED if host_reached else LaneState.NOT_REACHED,
            Confidence.OBSERVED,
        )

    return Lanes(
        client=LaneStatus(
            LaneState.REACHED if client_reached else LaneState.NOT_REACHED,
            Confidence.INFERRED,
            reason=_CLIENT_REASON,
        ),
        host=host_status,
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
    if failed is not None:
        raw_by_name = {str(r["event"]): r for r in raw_events}
        message = _opt_str(raw_by_name.get("WorkerIndexingFailed", {}).get("failureMessage"))
        return [Failure(event=failed.id, kind="worker-indexing", message=message)]

    invocation_failure = _failed_invocation_event(events, raw_events)
    if invocation_failure is not None:
        return [Failure(event=invocation_failure, kind="invocation-failed")]
    return []


def _failed_invocation_event(
    events: list[Event], raw_events: list[dict[str, object]]
) -> str | None:
    """Return the finalized event id of a failed ``InvocationCompleted``, if any.

    An in-invocation failure is a host ``InvocationCompleted`` whose parsed
    ``result`` is ``"Failed"`` (the ``Executed 'Functions.x' (Failed, ...)``
    line). v0.1 has no distinct ``InvocationFailed`` log line, so this is the
    single anchor the viewer uses to render the host lane's stop.
    """
    raw_completed = next((r for r in raw_events if r["event"] == "InvocationCompleted"), None)
    if raw_completed is None or raw_completed.get("result") != "Failed":
        return None
    return next((e.id for e in events if e.event == "InvocationCompleted"), None)


def _as_lane(value: object) -> Lane:
    return value if isinstance(value, Lane) else Lane(str(value))


def _as_confidence(value: object) -> Confidence:
    return value if isinstance(value, Confidence) else Confidence(str(value))


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None

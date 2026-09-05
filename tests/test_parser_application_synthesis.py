"""Edge-case contracts for the inferred application-window synthesis (issue #25).

``synthesize_application_events`` turns an observed Host<->Worker boundary into
the two inferred application-lane markers. These tests pin the guard behavior
that the golden happy-path traces cannot exercise: the pair is emitted only when
a worker receipt is followed by a matching completion, and never otherwise.
"""

from __future__ import annotations

from funcviz.models import Confidence, Lane
from funcviz.parser.derive import synthesize_application_events

_INV = "6a8f3658-2b31-4554-aa86-1ee32a9e679b"


def _worker(invocation: str = _INV, ts: str = "2024-01-01T00:00:00.100Z") -> dict[str, object]:
    return {
        "event": "WorkerReceivedInvocation",
        "lane": Lane.PYTHON_WORKER,
        "confidence": Confidence.OBSERVED,
        "timestamp": ts,
        "raw": "received",
        "invocationId": invocation,
        "workerRequestId": "w-1",
    }


def _completed(invocation: str = _INV, ts: str = "2024-01-01T00:00:00.150Z") -> dict[str, object]:
    return {
        "event": "InvocationCompleted",
        "lane": Lane.HOST,
        "confidence": Confidence.OBSERVED,
        "timestamp": ts,
        "raw": "executed",
        "invocationId": invocation,
    }


def _names(events: list[dict[str, object]]) -> list[str]:
    return [str(e["event"]) for e in events]


def test_pair_is_inserted_between_the_boundary_events():
    out = synthesize_application_events([_worker(), _completed()])
    assert _names(out) == [
        "WorkerReceivedInvocation",
        "ApplicationFunctionStarted",
        "ApplicationFunctionCompleted",
        "InvocationCompleted",
    ]
    started, finished = out[1], out[2]
    for event in (started, finished):
        assert event["lane"] is Lane.APPLICATION
        assert event["confidence"] is Confidence.INFERRED
        assert event["raw"] is None
        assert event["invocationId"] == _INV
        assert "workerRequestId" not in event


def test_no_synthesis_without_a_worker_receipt():
    assert _names(synthesize_application_events([_completed()])) == ["InvocationCompleted"]


def test_no_synthesis_without_a_completion():
    assert _names(synthesize_application_events([_worker()])) == ["WorkerReceivedInvocation"]


def test_no_synthesis_on_invocation_id_mismatch():
    events = [_worker(invocation="aaaa"), _completed(invocation="bbbb")]
    assert _names(synthesize_application_events(events)) == _names(events)


def test_no_synthesis_when_completion_precedes_worker_receipt():
    events = [_completed(ts="2024-01-01T00:00:00.100Z"), _worker(ts="2024-01-01T00:00:00.200Z")]
    assert _names(synthesize_application_events(events)) == _names(events)


def test_synthesis_is_idempotent():
    once = synthesize_application_events([_worker(), _completed()])
    twice = synthesize_application_events(once)
    assert _names(twice) == _names(once)

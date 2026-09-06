"""Semantic contracts for the success-path parser (issue #4, PRD R1).

These lock down *why* the golden trace looks the way it does — lane
reachability and confidence, per-event confidence classification, three-way ID
correlation, and ordering invariants — so a Core Tools log-format drift fails
with a targeted assertion instead of an opaque golden diff.
"""

from __future__ import annotations

import json
from pathlib import Path

from funcviz.parser import from_log_text, mask_records, parse_trace
from funcviz.source import enrich_trace_from_source

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "examples" / "python-http-trigger" / "function_app.py"
HTTP_REQUEST_ID = "2d0db691-8e70-4335-a8a9-e127715fa678"
WORKER_REQUEST_ID = "e42785bf-7670-4de1-a81d-b05df7b2b32d"
INVOCATION_ID = "6a8f3658-2b31-4554-aa86-1ee32a9e679b"


def _trace() -> dict[str, object]:
    text = (ROOT / "samples" / "success.log").read_text()
    trace = parse_trace(mask_records(from_log_text(text)), trace_id="success-001")
    return enrich_trace_from_source(trace, SOURCE).to_dict()


def _events() -> list[dict[str, object]]:
    events = _trace()["events"]
    assert isinstance(events, list)
    return events


def _lanes() -> dict[str, object]:
    lanes = _trace()["lanes"]
    assert isinstance(lanes, dict)
    return lanes


def test_all_four_lanes_reached_with_expected_confidence():
    lanes = _lanes()
    assert set(lanes) == {"client", "host", "python-worker", "application"}
    expected = {
        "client": "inferred",
        "host": "observed",
        "python-worker": "observed",
        "application": "inferred",
    }
    for name, confidence in expected.items():
        status = lanes[name]
        assert isinstance(status, dict)
        assert status["status"] == "reached"
        assert status["confidence"] == confidence


def test_inferred_lanes_carry_a_reason_and_no_lane_reports_failure():
    lanes = _lanes()
    for name in ("client", "application"):
        status = lanes[name]
        assert isinstance(status, dict)
        assert isinstance(status.get("reason"), str) and status["reason"]
    for status in lanes.values():
        assert isinstance(status, dict)
        assert "failureEvent" not in status


def test_event_confidence_is_classified_by_deliberate_rule():
    observed = {"InvocationStarted", "WorkerReceivedInvocation", "InvocationCompleted"}
    inferred = {
        "HttpRequestReceived",
        "HttpResponseReturned",
        "ApplicationFunctionStarted",
        "ApplicationFunctionCompleted",
    }
    for event in _events():
        name = event["event"]
        if name in observed:
            assert event["confidence"] == "observed", name
        elif name in inferred:
            assert event["confidence"] == "inferred", name
        else:
            raise AssertionError(f"unexpected event {name!r}")


def test_no_success_event_claims_instrumented_confidence():
    assert all(event["confidence"] != "instrumented" for event in _events())


def test_three_ids_stay_distinct_and_attach_to_the_right_events():
    by_name = {event["event"]: event for event in _events()}

    assert len({HTTP_REQUEST_ID, WORKER_REQUEST_ID, INVOCATION_ID}) == 3

    for name in ("HttpRequestReceived", "HttpResponseReturned"):
        event = by_name[name]
        assert event["httpRequestId"] == HTTP_REQUEST_ID
        assert "invocationId" not in event
        assert "workerRequestId" not in event

    worker = by_name["WorkerReceivedInvocation"]
    assert worker["workerRequestId"] == WORKER_REQUEST_ID
    assert worker["invocationId"] == INVOCATION_ID

    for name in ("InvocationStarted", "InvocationCompleted"):
        event = by_name[name]
        assert event["invocationId"] == INVOCATION_ID
        assert "httpRequestId" not in event
        assert "workerRequestId" not in event


def test_application_window_is_a_pair_of_inferred_events_between_worker_and_completion():
    events = _events()
    by_name = {event["event"]: event for event in events}
    started = by_name["ApplicationFunctionStarted"]
    finished = by_name["ApplicationFunctionCompleted"]

    for event in (started, finished):
        assert event["lane"] == "application"
        assert event["confidence"] == "inferred"
        assert event["raw"] is None
        assert event["invocationId"] == INVOCATION_ID

    seq = {event["event"]: event["sequence"] for event in events}
    assert seq["WorkerReceivedInvocation"] < seq["ApplicationFunctionStarted"]
    assert seq["ApplicationFunctionStarted"] < seq["ApplicationFunctionCompleted"]
    assert seq["ApplicationFunctionCompleted"] < seq["InvocationCompleted"]


def test_application_lane_owns_the_inferred_window_interval():
    intervals = _trace()["intervals"]
    assert isinstance(intervals, list)
    app_intervals = [i for i in intervals if i["lane"] == "application"]
    assert len(app_intervals) == 1
    interval = app_intervals[0]
    assert interval["source"] == "inferred"
    assert interval["confidence"] == "inferred"


def test_lifecycle_ordering_invariants_hold():
    events = _events()

    def seq(name: str) -> int:
        for event in events:
            if event["event"] == name:
                value = event["sequence"]
                assert isinstance(value, int)
                return value
        raise AssertionError(f"missing event {name!r}")

    assert seq("HttpRequestReceived") < seq("InvocationStarted")
    assert seq("InvocationStarted") < seq("WorkerReceivedInvocation")
    assert seq("WorkerReceivedInvocation") < seq("InvocationCompleted")
    assert seq("InvocationCompleted") < seq("HttpResponseReturned")


def test_elapsed_is_non_negative_and_monotonic():
    elapsed: list[int] = []
    for event in _events():
        value = event["elapsedMs"]
        assert isinstance(value, int)
        elapsed.append(value)
    assert elapsed[0] == 0
    assert all(value >= 0 for value in elapsed)
    assert elapsed == sorted(elapsed)


def test_golden_is_the_end_to_end_contract():
    golden = json.loads((ROOT / "traces" / "success.json").read_text())
    assert _trace() == golden


def test_tailless_log_is_marked_incomplete_not_clean_success(tmp_path):
    """#84 — a capture without terminal evidence must never read as completed."""
    text = (ROOT / "samples" / "success.log").read_text()
    tailless = (
        "\n".join(line for line in text.splitlines() if "Executed 'Functions." not in line) + "\n"
    )
    assert "InvocationCompleted" not in {e["event"] for e in _events_from_text(tailless)}
    trace = parse_trace(mask_records(from_log_text(tailless)), trace_id="tailless-001")
    assert trace.metadata.get("incomplete") is True
    out = trace.to_dict()
    assert out["metadata"]["incomplete"] is True


def test_completed_run_is_not_marked_incomplete():
    text = (ROOT / "samples" / "success.log").read_text()
    trace = parse_trace(mask_records(from_log_text(text)), trace_id="success-001")
    assert not trace.metadata.get("incomplete")
    assert "metadata" not in trace.to_dict()


def test_indexing_failure_is_terminal_not_incomplete():
    text = (ROOT / "samples" / "worker-fail.log").read_text()
    trace = parse_trace(mask_records(from_log_text(text)), trace_id="worker-fail-001")
    assert not trace.metadata.get("incomplete")


def _events_from_text(text: str) -> list[dict[str, object]]:
    from funcviz.parser.derive import synthesize_application_events
    from funcviz.parser.events import extract_events
    from funcviz.parser.records import fold_http_blocks

    return synthesize_application_events(extract_events(fold_http_blocks(from_log_text(text))))

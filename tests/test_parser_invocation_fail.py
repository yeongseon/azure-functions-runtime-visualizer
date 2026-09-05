"""In-invocation failure derivation for a function-body failure (issue #27).

Asserts that ``invocation-fail.log`` (a run that reached user code and then
failed, reported by the host's ``Executed 'Functions.hello' (Failed, ...)`` line
and an HTTP 500) parses into a schema-valid ``outcome: failure`` trace that the
viewer can render: the host lane owns the stop via ``failed-here`` +
``failureEvent``, the client/worker/application lanes stay reached (the failure
happened inside the function body, not before it), no misleading
``ApplicationFunctionCompleted`` marker is synthesized, and the application
interval is omitted. A byte-for-byte golden guards ``traces/invocation-fail.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from funcviz.parser import from_log_text, mask_records, parse_trace

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "trace-0.1.json").read_text())

INVOCATION_FAIL_EVENTS = [
    "HttpRequestReceived",
    "InvocationStarted",
    "WorkerReceivedInvocation",
    "ApplicationFunctionStarted",
    "InvocationCompleted",
    "HttpResponseReturned",
]


def _parsed() -> dict[str, object]:
    text = (ROOT / "samples" / "invocation-fail.log").read_text()
    return parse_trace(mask_records(from_log_text(text)), trace_id="invocation-fail-001").to_dict()


def test_invocation_fail_log_validates_against_schema():
    assert not list(Draft202012Validator(SCHEMA).iter_errors(_parsed()))


def test_outcome_is_failure_from_the_executed_failed_line():
    assert _parsed()["outcome"] == "failure"


def test_event_vocabulary_omits_the_application_completion_marker():
    names = [e["event"] for e in _parsed()["events"]]
    assert names == INVOCATION_FAIL_EVENTS
    assert "ApplicationFunctionCompleted" not in names


def test_host_lane_owns_the_stop_at_the_failed_invocation():
    lanes = _parsed()["lanes"]
    completed = next(e for e in _parsed()["events"] if e["event"] == "InvocationCompleted")
    assert lanes["host"]["status"] == "failed-here"
    assert lanes["host"]["failureEvent"] == completed["id"]


def test_lanes_reached_before_the_failure_stay_reached():
    lanes = _parsed()["lanes"]
    assert lanes["client"]["status"] == "reached"
    assert lanes["python-worker"]["status"] == "reached"
    assert lanes["application"]["status"] == "reached"


def test_failure_record_anchors_the_failed_invocation_without_a_fabricated_message():
    failures = _parsed()["failures"]
    completed = next(e for e in _parsed()["events"] if e["event"] == "InvocationCompleted")
    assert failures == [{"event": completed["id"], "kind": "invocation-failed"}]


def test_no_application_interval_for_a_run_that_never_completed_the_body():
    interval_ids = [i["id"] for i in _parsed()["intervals"]]
    assert "i4" not in interval_ids
    assert interval_ids == ["i1", "i2", "i3"]


def test_parser_output_matches_committed_golden():
    golden = json.loads((ROOT / "traces" / "invocation-fail.json").read_text())
    assert _parsed() == golden

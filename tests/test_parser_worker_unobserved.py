"""Unknown-lane derivation for an un-elevated capture (issue #28).

Asserts that ``worker-unobserved.log`` (a successful run captured without the §5
elevated worker/gRPC logging, so the ``Received FunctionInvocationRequest``
worker line is absent) does not claim to have *observed* a worker non-reach. The
host still observes the invocation, so the worker boundary is genuinely
``unknown`` rather than ``not-reached``; because the inferred application window
hangs off that same absent worker signal, the application lane is ``unknown``
too. Both carry ``inferred`` confidence, never the overclaiming ``observed``. A
byte-for-byte golden guards ``traces/worker-unobserved.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from funcviz.parser import from_log_text, mask_records, parse_trace

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "trace-0.1.json").read_text())

WORKER_UNOBSERVED_EVENTS = [
    "HttpRequestReceived",
    "InvocationStarted",
    "InvocationCompleted",
    "HttpResponseReturned",
]


def _parsed() -> dict[str, object]:
    text = (ROOT / "samples" / "worker-unobserved.log").read_text()
    return parse_trace(
        mask_records(from_log_text(text)), trace_id="worker-unobserved-001"
    ).to_dict()


def test_worker_unobserved_log_validates_against_schema():
    assert not list(Draft202012Validator(SCHEMA).iter_errors(_parsed()))


def test_no_worker_or_application_events_are_fabricated():
    names = [e["event"] for e in _parsed()["events"]]
    assert names == WORKER_UNOBSERVED_EVENTS
    assert "WorkerReceivedInvocation" not in names
    assert "ApplicationFunctionStarted" not in names


def test_observed_lanes_stay_observed():
    lanes = _parsed()["lanes"]
    assert lanes["client"]["status"] == "reached"
    assert lanes["host"]["status"] == "reached"
    assert lanes["host"]["confidence"] == "observed"


def test_worker_lane_is_unknown_not_observed_not_reached():
    worker = _parsed()["lanes"]["python-worker"]
    assert worker["status"] == "unknown"
    assert worker["confidence"] == "inferred"
    assert worker.get("reason")


def test_application_lane_propagates_unknown_from_the_worker():
    application = _parsed()["lanes"]["application"]
    assert application["status"] == "unknown"
    assert application["confidence"] == "inferred"


def test_parser_output_matches_committed_golden():
    golden = json.loads((ROOT / "traces" / "worker-unobserved.json").read_text())
    assert _parsed() == golden

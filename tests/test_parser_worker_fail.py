"""Failure-trace derivation for the worker startup/indexing case (issue #9).

Asserts that ``worker-fail.log`` (a worker that crashed while indexing, before
any HTTP request or invocation) parses into a schema-valid ``outcome: failure``
trace that stops honestly at the indexing failure: the python-worker lane owns
the stop, client and application are not reached, and the post-failure host
retry loop is not rendered as forward progress (PRD FR-9). A byte-for-byte
golden guards the committed ``traces/worker-fail.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from funcviz.parser import from_log_text, mask_records, parse_trace

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "trace-0.1.json").read_text())

FAILURE_EVENTS = [
    "HostBuildStarted",
    "WorkerIndexingStarted",
    "PythonWorkerStarted",
    "WorkerMetadataRequested",
    "WorkerIndexingFailed",
]

RETRY_LOOP_MARKERS = ["Starting Host", "0 functions found"]


def _parsed() -> dict[str, object]:
    text = (ROOT / "samples" / "worker-fail.log").read_text()
    return parse_trace(mask_records(from_log_text(text)), trace_id="worker-fail-001").to_dict()


def test_failure_log_validates_against_schema():
    assert not list(Draft202012Validator(SCHEMA).iter_errors(_parsed()))


def test_outcome_is_failure_without_an_executed_failed_line():
    assert _parsed()["outcome"] == "failure"


def test_event_vocabulary_and_order():
    events = _parsed()["events"]
    assert [e["event"] for e in events] == FAILURE_EVENTS
    assert [e["sequence"] for e in events] == [0, 1, 2, 3, 4]


def test_no_http_or_invocation_events_leak_in():
    names = {e["event"] for e in _parsed()["events"]}
    forbidden = {
        "HttpRequestReceived",
        "HttpResponseReturned",
        "InvocationStarted",
        "InvocationCompleted",
        "WorkerReceivedInvocation",
    }
    assert not (names & forbidden)


def test_python_worker_lane_owns_the_stop():
    lanes = _parsed()["lanes"]
    assert lanes["python-worker"]["status"] == "failed-here"
    assert lanes["python-worker"]["failureEvent"] == "e4"


def test_client_and_application_lanes_are_not_reached():
    lanes = _parsed()["lanes"]
    assert lanes["client"]["status"] == "not-reached"
    assert lanes["application"]["status"] == "not-reached"
    assert lanes["host"]["status"] == "reached"


def test_host_is_not_marked_failed():
    assert _parsed()["lanes"]["host"]["status"] != "failed-here"


def test_failure_record_references_the_terminal_event():
    failures = _parsed()["failures"]
    assert failures == [
        {
            "event": "e4",
            "kind": "worker-indexing",
            "message": "ModuleNotFoundError: No module named 'this_module_does_not_exist'",
        }
    ]


def test_no_intervals_for_a_run_that_never_invoked():
    assert _parsed()["intervals"] == []


def test_no_application_block_when_the_function_never_loaded():
    assert "application" not in _parsed()


def test_retry_loop_after_failure_is_not_rendered_as_events():
    for event in _parsed()["events"]:
        raw = event["raw"] or ""
        for marker in RETRY_LOOP_MARKERS:
            assert marker not in raw, marker


def test_parser_output_matches_committed_golden():
    golden = json.loads((ROOT / "traces" / "worker-fail.json").read_text())
    assert _parsed() == golden

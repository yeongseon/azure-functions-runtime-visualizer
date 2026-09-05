"""Golden-output smoke test for the pure parser (issue #3).

Parses the committed success.log fixture and asserts the structural contract
that issue #4 will expand: schema validity, frozen event order, monotonic
elapsed times, and the three provenance-tagged intervals. Byte-for-byte golden
comparison against traces/success.json guards against silent regressions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from funcviz.models import LogRecord
from funcviz.parser import from_log_text, mask_records, parse_trace

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "trace-0.1.json").read_text())

FROZEN_EVENTS = [
    "HttpRequestReceived",
    "InvocationStarted",
    "WorkerReceivedInvocation",
    "InvocationCompleted",
    "HttpResponseReturned",
]


def _parsed() -> dict[str, object]:
    text = (ROOT / "samples" / "success.log").read_text()
    return parse_trace(mask_records(from_log_text(text)), trace_id="success-001").to_dict()


def test_success_log_validates_against_schema():
    assert not list(Draft202012Validator(SCHEMA).iter_errors(_parsed()))


def test_event_order_matches_log_order():
    doc = _parsed()
    assert [e["event"] for e in doc["events"]] == FROZEN_EVENTS
    assert [e["elapsedMs"] for e in doc["events"]] == [0, 251, 272, 285, 294]


def test_intervals_preserve_duration_provenance():
    intervals = _parsed()["intervals"]
    assert [(i["id"], i["source"], i["durationMs"]) for i in intervals] == [
        ("i1", "log-delta", 34),
        ("i2", "host-reported", 54),
        ("i3", "http-reported", 294),
    ]


def test_three_id_correlation_is_separated():
    worker_event = _parsed()["events"][2]
    assert worker_event["workerRequestId"] == "e42785bf-7670-4de1-a81d-b05df7b2b32d"
    assert worker_event["invocationId"] == "6a8f3658-2b31-4554-aa86-1ee32a9e679b"


def test_parser_output_matches_committed_golden():
    golden = json.loads((ROOT / "traces" / "success.json").read_text())
    assert _parsed() == golden


def test_multiline_http_block_is_folded_into_one_event():
    events = _parsed()["events"]
    http_events = [e for e in events if e["event"].startswith("Http")]
    assert len(http_events) == 2
    assert all("\n" in e["raw"] for e in http_events)


def test_bare_message_records_parse_without_from_log_text():
    text = (ROOT / "samples" / "success.log").read_text()
    bare = [LogRecord(message=line) for line in text.splitlines()]
    assert parse_trace(mask_records(bare), trace_id="success-001").to_dict() == _parsed()


def test_structured_timestamp_is_honored_over_message_prefix():
    started = (
        "[2024-01-01T00:00:00.100Z] Executing 'Functions.hello' "
        "(Reason='...', Id=6a8f3658-2b31-4554-aa86-1ee32a9e679b)"
    )
    completed = (
        "[9999-01-01T00:00:00.000Z] Executed 'Functions.hello' "
        "(Succeeded, Id=6a8f3658-2b31-4554-aa86-1ee32a9e679b, Duration=54ms)"
    )
    records = [
        LogRecord(message=started),
        LogRecord(
            message=completed,
            timestamp=datetime(2024, 1, 1, 0, 0, 0, 400000, tzinfo=timezone.utc),
        ),
    ]
    events = parse_trace(records, trace_id="ts-001").to_dict()["events"]
    assert [e["elapsedMs"] for e in events] == [0, 300]

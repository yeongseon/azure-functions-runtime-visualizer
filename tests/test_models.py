"""Round-trip tests for the data models (issue #2).

Build the two shipped example traces as model objects, serialize them, and
assert the output both validates against the frozen schema and equals the
committed example JSON byte-for-value. This locks model<->schema parity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from funcviz.models import (
    Application,
    Confidence,
    Event,
    Failure,
    Interval,
    IntervalSource,
    Lane,
    Lanes,
    LaneState,
    LaneStatus,
    Outcome,
    Runtime,
    Trace,
    TraceInput,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "trace-0.1.json").read_text())
EXAMPLES = ROOT / "schemas" / "examples"

SOURCE_TEXT = (
    "import azure.functions as func\n\napp = func.FunctionApp()\n\n"
    '@app.route(route="hello")\n'
    "def hello(req: func.HttpRequest) -> func.HttpResponse:\n"
    '    name = req.params.get("name") or "Azure"\n'
    '    return func.HttpResponse(f"Hello, {name}!")\n'
)


def _local_input() -> TraceInput:
    return TraceInput(source="core-tools-log", adapter="CoreToolsLogAdapter", adapter_version="0.1")


def _local_runtime() -> Runtime:
    return Runtime(
        environment="local",
        language="python",
        trigger="http",
        core_tools_version="TBD",
        host_version="TBD",
    )


def build_success_trace() -> Trace:
    inv = "6a8f3658-2b31-4554-aa86-1ee32a9e679b"
    http = "2d0db691-8e70-4335-a8a9-e127715fa678"
    worker = "e42785bf-7670-4de1-a81d-b05df7b2b32d"
    return Trace(
        trace_id="success-001",
        outcome=Outcome.SUCCESS,
        input=_local_input(),
        runtime=_local_runtime(),
        application=Application(
            function_name="hello",
            source_file="function_app.py",
            source_text=SOURCE_TEXT,
            definition_line_range=(5, 8),
        ),
        lanes=Lanes(
            client=LaneStatus(
                LaneState.REACHED,
                Confidence.INFERRED,
                reason="Derived from host HTTP request/response lines.",
            ),
            host=LaneStatus(LaneState.REACHED, Confidence.OBSERVED),
            python_worker=LaneStatus(LaneState.REACHED, Confidence.OBSERVED),
            application=LaneStatus(
                LaneState.REACHED,
                Confidence.INFERRED,
                reason="User-code entry/exit is not separately logged.",
            ),
        ),
        events=[
            Event(
                id="e0",
                sequence=0,
                timestamp="2026-09-05T00:45:16.955Z",
                elapsed_ms=0,
                lane=Lane.CLIENT,
                event="HttpRequestReceived",
                http_request_id=http,
                confidence=Confidence.INFERRED,
                raw='[2026-09-05T00:45:16.955Z] Executing HTTP request: { "requestId": '
                '"2d0db691-8e70-4335-a8a9-e127715fa678", ... }',
            ),
            Event(
                id="e1",
                sequence=1,
                timestamp="2026-09-05T00:45:17.206Z",
                elapsed_ms=251,
                lane=Lane.HOST,
                event="InvocationStarted",
                invocation_id=inv,
                confidence=Confidence.OBSERVED,
                raw="[2026-09-05T00:45:17.206Z] Executing 'Functions.hello' (Reason='...', "
                "Id=6a8f3658-2b31-4554-aa86-1ee32a9e679b)",
            ),
            Event(
                id="e2",
                sequence=2,
                timestamp="2026-09-05T00:45:17.227Z",
                elapsed_ms=272,
                lane=Lane.PYTHON_WORKER,
                event="WorkerReceivedInvocation",
                worker_request_id=worker,
                invocation_id=inv,
                confidence=Confidence.OBSERVED,
                raw="[2026-09-05T00:45:17.227Z] Received FunctionInvocationRequest, request ID: "
                "e42785bf-..., invocation ID: 6a8f3658-...",
            ),
            Event(
                id="e3",
                sequence=3,
                timestamp="2026-09-05T00:45:17.240Z",
                elapsed_ms=285,
                lane=Lane.HOST,
                event="InvocationCompleted",
                invocation_id=inv,
                confidence=Confidence.OBSERVED,
                raw="[2026-09-05T00:45:17.240Z] Executed 'Functions.hello' (Succeeded, "
                "Id=6a8f3658-..., Duration=54ms)",
            ),
            Event(
                id="e4",
                sequence=4,
                timestamp="2026-09-05T00:45:17.249Z",
                elapsed_ms=294,
                lane=Lane.CLIENT,
                event="HttpResponseReturned",
                http_request_id=http,
                confidence=Confidence.INFERRED,
                raw='[2026-09-05T00:45:17.249Z] Executed HTTP request: { "requestId": '
                '"2d0db691-...", "status": "200", "duration": "294" }',
            ),
        ],
        intervals=[
            Interval(
                id="i1",
                label="Invocation (host log delta)",
                lane=Lane.HOST,
                kind="invocation",
                start_event="e1",
                end_event="e3",
                duration_ms=34,
                source=IntervalSource.LOG_DELTA,
                confidence=Confidence.OBSERVED,
            ),
            Interval(
                id="i2",
                label="Invocation (host-reported)",
                lane=Lane.HOST,
                kind="invocation",
                start_event="e1",
                end_event="e3",
                duration_ms=54,
                source=IntervalSource.HOST_REPORTED,
                confidence=Confidence.OBSERVED,
                raw="Duration=54ms",
            ),
            Interval(
                id="i3",
                label="HTTP request",
                lane=Lane.CLIENT,
                kind="http",
                start_event="e0",
                end_event="e4",
                duration_ms=294,
                source=IntervalSource.HTTP_REPORTED,
                confidence=Confidence.INFERRED,
                raw='"duration": "294"',
            ),
        ],
    )


def build_worker_fail_trace() -> Trace:
    worker = "e42785bf-7670-4de1-a81d-b05df7b2b32d"
    return Trace(
        trace_id="worker-fail-001",
        outcome=Outcome.FAILURE,
        input=_local_input(),
        runtime=_local_runtime(),
        application=Application(function_name="hello", source_file="function_app.py"),
        lanes=Lanes(
            client=LaneStatus(
                LaneState.NOT_REACHED,
                Confidence.OBSERVED,
                reason="No HTTP request was served; the worker failed to index functions "
                "before any request.",
            ),
            host=LaneStatus(LaneState.FAILED_HERE, Confidence.OBSERVED, failure_event="e2"),
            python_worker=LaneStatus(
                LaneState.FAILED_HERE, Confidence.OBSERVED, failure_event="e1"
            ),
            application=LaneStatus(
                LaneState.NOT_REACHED, Confidence.OBSERVED, reason="User code never executed."
            ),
        ),
        events=[
            Event(
                id="e0",
                sequence=0,
                timestamp="2026-09-05T00:44:10.000Z",
                elapsed_ms=0,
                lane=Lane.PYTHON_WORKER,
                event="WorkerStarting",
                worker_request_id=worker,
                confidence=Confidence.OBSERVED,
                raw="[...] Starting Azure Functions Python Worker.",
            ),
            Event(
                id="e1",
                sequence=1,
                timestamp="2026-09-05T00:44:11.000Z",
                elapsed_ms=1000,
                lane=Lane.PYTHON_WORKER,
                event="WorkerIndexingError",
                confidence=Confidence.OBSERVED,
                attributes={"exception": "ModuleNotFoundError"},
                raw="[...] Error in index_function_app. ModuleNotFoundError: "
                "No module named 'nonexistent'",
            ),
            Event(
                id="e2",
                sequence=2,
                timestamp="2026-09-05T00:44:11.100Z",
                elapsed_ms=1100,
                lane=Lane.HOST,
                event="WorkerIndexingFailure",
                confidence=Confidence.OBSERVED,
                raw="[...] Worker failed to index functions. Result: Failure",
            ),
        ],
        intervals=[],
        failures=[
            Failure(
                event="e1",
                kind="worker-init",
                message="Worker failed to index functions (ModuleNotFoundError).",
            )
        ],
    )


def test_success_trace_matches_example_and_validates():
    built = build_success_trace().to_dict()
    example = json.loads((EXAMPLES / "success.example.json").read_text())
    assert built == example
    assert not list(Draft202012Validator(SCHEMA).iter_errors(built))


def test_worker_fail_trace_matches_example_and_validates():
    built = build_worker_fail_trace().to_dict()
    example = json.loads((EXAMPLES / "worker-fail.example.json").read_text())
    assert built == example
    assert not list(Draft202012Validator(SCHEMA).iter_errors(built))


def test_lane_enum_serializes_python_worker_with_hyphen():
    assert Lane.PYTHON_WORKER.value == "python-worker"
    assert build_success_trace().to_dict()["lanes"]["python-worker"]["status"] == "reached"


def test_empty_optional_maps_are_omitted():
    ev = build_success_trace().to_dict()["events"][0]
    assert "correlation" not in ev
    assert "attributes" not in ev


def test_required_raw_is_emitted_even_when_none():
    ev = Event(
        id="x",
        sequence=0,
        lane=Lane.HOST,
        event="Synth",
        confidence=Confidence.INFERRED,
        raw=None,
    ).to_dict()
    assert "raw" in ev and ev["raw"] is None


def test_failed_here_lane_requires_failure_event():
    with pytest.raises(ValueError):
        LaneStatus(LaneState.FAILED_HERE, Confidence.OBSERVED)


def test_trace_requires_at_least_one_event():
    with pytest.raises(ValueError):
        Trace(
            trace_id="empty",
            outcome=Outcome.SUCCESS,
            input=_local_input(),
            runtime=_local_runtime(),
            lanes=build_success_trace().lanes,
            events=[],
        )


def test_input_and_failure_carry_extension_fields():
    inp = TraceInput(source="s", extra={"capture": "verbose"}).to_dict()
    assert inp["capture"] == "verbose"
    fail = Failure(event="e1", extra={"stackHash": "abc"}).to_dict()
    assert fail["stackHash"] == "abc"

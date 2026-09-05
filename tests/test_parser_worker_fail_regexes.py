"""Regex-layer drift guard for the failure fixture (issue #4, scope-limited).

Full failure-trace derivation is issue #9. Here we only characterize that the
shared startup/metadata regexes still recognize ``worker-fail.log`` and that the
success-path event regexes correctly find nothing in it, so a Core Tools format
bump surfaces as a named regex assertion rather than a surprise in #9.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from funcviz.parser import from_log_text, parse_trace
from funcviz.parser.regexes import (
    find_core_tools_version,
    find_function_path,
    find_runtime_version,
    find_worker_runtime,
    match_invocation_completed,
    match_invocation_started,
    match_worker_invocation,
    split_timestamp,
)

ROOT = Path(__file__).resolve().parent.parent


def _content_lines() -> list[str]:
    text = (ROOT / "samples" / "worker-fail.log").read_text()
    return [split_timestamp(line)[1] for line in text.splitlines()]


def _find(lines: list[str], finder: Callable[[str], str | None]) -> str | None:
    for line in lines:
        value = finder(line)
        if value is not None:
            return value
    return None


def test_shared_startup_metadata_still_matches():
    lines = _content_lines()
    assert _find(lines, find_worker_runtime) == "python"
    core_tools = _find(lines, find_core_tools_version)
    assert core_tools is not None and core_tools.startswith("4.6.0")
    assert _find(lines, find_runtime_version) == "4.1045.200.25556"
    path = _find(lines, find_function_path)
    assert path is not None and path.endswith("function_app.py")


def test_success_event_regexes_find_no_invocation_or_worker_events():
    lines = _content_lines()
    assert all(match_invocation_started(line) is None for line in lines)
    assert all(match_invocation_completed(line) is None for line in lines)
    assert all(match_worker_invocation(line) is None for line in lines)


def test_failure_shape_markers_are_still_present():
    text = (ROOT / "samples" / "worker-fail.log").read_text()
    markers = [
        "Error in index_function_app",
        "No module named 'this_module_does_not_exist'",
        "Worker failed to index functions",
        "Result: Failure",
        "0 functions found",
    ]
    for marker in markers:
        assert marker in text, marker


def test_failure_log_builds_a_failure_trace():
    text = (ROOT / "samples" / "worker-fail.log").read_text()
    doc = parse_trace(from_log_text(text), trace_id="worker-fail-001").to_dict()
    assert doc["outcome"] == "failure"
    assert [e["event"] for e in doc["events"]] == [
        "HostBuildStarted",
        "WorkerIndexingStarted",
        "PythonWorkerStarted",
        "WorkerMetadataRequested",
        "WorkerIndexingFailed",
    ]

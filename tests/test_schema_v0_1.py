"""Schema-freeze tests for trace-0.1.json (issue #1, PRD §6).

These lock the v0.1 trace contract: the schema must accept both shipped example
shapes (a success trace and a worker-failure trace with unreached lanes) and
must reject structural violations. Schema versioning is never-cut (PRD §11), so
a change that breaks these tests should come with a schemaVersion bump.

Run: pytest tests/test_schema_v0_1.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "trace-0.1.json"
EXAMPLES_DIR = ROOT / "schemas" / "examples"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def success_trace() -> dict:
    return json.loads((EXAMPLES_DIR / "success.example.json").read_text())


def test_schema_is_itself_valid(schema: dict) -> None:
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schemaVersion"]["const"] == "0.1"


@pytest.mark.parametrize(
    "example",
    ["success.example.json", "worker-fail.example.json"],
)
def test_example_traces_validate(validator: Draft202012Validator, example: str) -> None:
    trace = json.loads((EXAMPLES_DIR / example).read_text())
    errors = sorted(validator.iter_errors(trace), key=str)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_three_correlation_ids_stay_separate(success_trace: dict) -> None:
    """The success trace must exercise all three id namespaces as distinct fields."""
    props = json.loads(SCHEMA_PATH.read_text())["$defs"]["event"]["properties"]
    for field in ("httpRequestId", "workerRequestId", "invocationId"):
        assert field in props
    ids = {e.get("invocationId") for e in success_trace["events"] if e.get("invocationId")}
    assert ids == {"6a8f3658-2b31-4554-aa86-1ee32a9e679b"}


def test_intervals_carry_distinct_duration_sources(success_trace: dict) -> None:
    """No single canonical duration: the 34/54/294ms triple with explicit sources."""
    by_source = {i["source"]: i["durationMs"] for i in success_trace["intervals"]}
    assert by_source["log-delta"] == 34
    assert by_source["host-reported"] == 54
    assert by_source["http-reported"] == 294


def test_failure_trace_marks_unreached_lanes(validator: Draft202012Validator) -> None:
    trace = json.loads((EXAMPLES_DIR / "worker-fail.example.json").read_text())
    assert not list(validator.iter_errors(trace))
    assert trace["lanes"]["client"]["status"] == "not-reached"
    assert trace["lanes"]["application"]["status"] == "not-reached"
    assert trace["lanes"]["host"]["status"] == "failed-here"


def _mutate(base: dict, fn) -> dict:
    t = copy.deepcopy(base)
    fn(t)
    return t


REJECTIONS = {
    "wrong schemaVersion": lambda t: t.update(schemaVersion="0.2"),
    "bad outcome enum": lambda t: t.update(outcome="partial"),
    "bad lane enum": lambda t: t["events"][1].update(lane="worker"),
    "bad confidence enum": lambda t: t["events"][1].update(confidence="guessed"),
    "bad interval source enum": lambda t: t["intervals"][0].update(source="made-up"),
    "bad lane status enum": lambda t: t["lanes"]["host"].update(status="done"),
    "event missing required raw": lambda t: t["events"][1].pop("raw"),
    "event extra property": lambda t: t["events"][1].update(surprise=1),
    "lanes missing application": lambda t: t["lanes"].pop("application"),
    "missing top-level lanes": lambda t: t.pop("lanes"),
    "interval missing source": lambda t: t["intervals"][0].pop("source"),
    "missing input": lambda t: t.pop("input"),
    "missing intervals": lambda t: t.pop("intervals"),
    "empty events": lambda t: t.update(events=[]),
    "failed-here without failureEvent": lambda t: t["lanes"]["host"].update(status="failed-here"),
}


@pytest.mark.parametrize("label", list(REJECTIONS))
def test_schema_rejects_violations(
    validator: Draft202012Validator, success_trace: dict, label: str
) -> None:
    bad = _mutate(success_trace, REJECTIONS[label])
    assert list(validator.iter_errors(bad)), f"schema should reject: {label}"

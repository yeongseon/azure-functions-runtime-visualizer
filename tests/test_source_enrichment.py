"""Source enrichment tests for ``funcviz parse --source`` (issue #26, AC6, #58)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from funcviz import cli
from funcviz.models import (
    Application,
    Confidence,
    Event,
    Failure,
    Lane,
    Lanes,
    LaneState,
    LaneStatus,
    Outcome,
    Runtime,
    Trace,
    TraceInput,
)
from funcviz.source import enrich_trace_from_source

ROOT = Path(__file__).resolve().parent.parent
SUCCESS_LOG = ROOT / "samples" / "success.log"
EXAMPLE_SOURCE = ROOT / "examples" / "python-http-trigger" / "function_app.py"


def _run(argv, stdin_text=""):
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdin=stdin, stdout=stdout, stderr=stderr, opener=lambda url: None)
    return code, stdout.getvalue(), stderr.getvalue()


def test_parse_source_embeds_text_and_range():
    code, stdout, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(EXAMPLE_SOURCE)])
    assert code == 0
    assert stderr == ""
    application = json.loads(stdout)["application"]
    assert application["sourceText"] == EXAMPLE_SOURCE.read_text()
    assert application["definitionLineRange"] == [6, 9]
    assert application["sourceFile"] == "function_app.py"


def test_parse_without_source_omits_text():
    code, stdout, _ = _run(["parse", str(SUCCESS_LOG)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert "sourceText" not in application


def test_parse_missing_source_is_hard_error(tmp_path):
    missing = tmp_path / "nope.py"
    code, _, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(missing)])
    assert code == 1
    assert "funcviz:" in stderr


def test_parse_source_function_not_found_warns_and_omits_range(tmp_path):
    other = tmp_path / "other.py"
    other.write_text("def unrelated():\n    return 1\n")
    code, stdout, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(other)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert application["sourceText"] == other.read_text()
    assert "definitionLineRange" not in application
    assert "no match" in stderr


def test_parse_source_syntax_error_warns_and_omits_range(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def hello(:\n")
    code, stdout, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(broken)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert application["sourceText"] == broken.read_text()
    assert "definitionLineRange" not in application
    assert "could not parse" in stderr


def test_parse_non_python_source_embeds_text_only(tmp_path):
    txt = tmp_path / "handler.txt"
    txt.write_text("hello source\n")
    code, stdout, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(txt)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert application["sourceText"] == txt.read_text()
    assert "definitionLineRange" not in application
    assert "not a Python source file" in stderr


def test_enriched_trace_renders_in_viewer(tmp_path):
    trace_out = tmp_path / "trace.json"
    _run(["parse", str(SUCCESS_LOG), "--source", str(EXAMPLE_SOURCE), "-o", str(trace_out)])
    html_out = tmp_path / "viewer.html"
    code, _, _ = _run(["view", str(trace_out), "--html-out", str(html_out)])
    assert code == 0
    html = html_out.read_text()
    assert '"sourceText"' in html
    assert '"definitionLineRange":[6,9]' in html


def test_parse_source_basename_mismatch_uses_source_file(tmp_path):
    renamed = tmp_path / "renamed.py"
    renamed.write_text(EXAMPLE_SOURCE.read_text())
    code, stdout, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(renamed)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert application["sourceFile"] == "renamed.py"
    assert application["definitionLineRange"] == [6, 9]
    assert "differs from" in stderr


def test_parse_source_duplicate_function_warns_and_omits_range(tmp_path):
    dup = tmp_path / "dup.py"
    dup.write_text("def hello():\n    return 1\n\n\ndef hello():\n    return 2\n")
    code, stdout, stderr = _run(["parse", str(SUCCESS_LOG), "--source", str(dup)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert application["sourceText"] == dup.read_text()
    assert "definitionLineRange" not in application
    assert "2 matches" in stderr


def test_highlight_confidence_emitted_iff_range_present(tmp_path):
    code, stdout, _ = _run(["parse", str(SUCCESS_LOG), "--source", str(EXAMPLE_SOURCE)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert application["definitionLineRange"] == [6, 9]
    assert application["highlightConfidence"] == "inferred"

    other = tmp_path / "other.py"
    other.write_text("def unrelated():\n    return 1\n")
    code, stdout, _ = _run(["parse", str(SUCCESS_LOG), "--source", str(other)])
    assert code == 0
    application = json.loads(stdout)["application"]
    assert "definitionLineRange" not in application
    assert "highlightConfidence" not in application


def _failure_trace_with_raw(raw: str) -> Trace:
    status = LaneStatus(LaneState.REACHED, Confidence.INFERRED)
    failed = LaneStatus(LaneState.FAILED_HERE, Confidence.OBSERVED, failure_event="e1")
    event = Event(
        id="e1",
        sequence=1,
        lane=Lane.HOST,
        event="InvocationCompleted",
        confidence=Confidence.OBSERVED,
        raw=raw,
    )
    return Trace(
        trace_id="t1",
        outcome=Outcome.FAILURE,
        input=TraceInput(source="verbose-log"),
        runtime=Runtime(environment="local", language="python", trigger="http"),
        lanes=Lanes(client=status, host=failed, python_worker=status, application=status),
        events=[event],
        failures=[Failure(event="e1", kind="invocation-failed")],
        application=Application(function_name="hello"),
    )


def test_failure_source_line_matched_from_error_message():
    raw = (
        "Executed 'Functions.hello' (Failed, Id=abc, Duration=5ms) | "
        'File "C:\\site\\wwwroot\\function_app.py", line 7, in hello'
    )
    enriched = enrich_trace_from_source(_failure_trace_with_raw(raw), EXAMPLE_SOURCE)
    failure = enriched.failures[0]
    assert failure.source_line == 7
    assert failure.source_confidence == "inferred"
    assert failure.to_dict()["sourceLine"] == 7


def test_failure_source_line_ignored_for_other_files():
    raw = "Executed 'Functions.hello' (Failed, Id=abc, Duration=5ms) | File \"other.py\", line 9"
    enriched = enrich_trace_from_source(_failure_trace_with_raw(raw), EXAMPLE_SOURCE)
    failure = enriched.failures[0]
    assert failure.source_line is None
    assert failure.source_confidence is None
    assert "sourceLine" not in failure.to_dict()


def test_failure_source_line_beyond_file_end_is_ignored():
    raw = (
        "Executed 'Functions.hello' (Failed, Id=abc, Duration=5ms) | "
        'File "C:\\site\\wwwroot\\function_app.py", line 999, in hello'
    )
    enriched = enrich_trace_from_source(_failure_trace_with_raw(raw), EXAMPLE_SOURCE)
    failure = enriched.failures[0]
    assert failure.source_line is None
    assert failure.source_confidence is None

"""Source enrichment tests for ``funcviz parse --source`` (issue #26, AC6)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from funcviz import cli

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

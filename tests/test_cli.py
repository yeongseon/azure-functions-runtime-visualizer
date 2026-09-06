"""CLI behavior tests for ``funcviz`` parse / view / record (issue #8)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from funcviz import cli

ROOT = Path(__file__).resolve().parent.parent
SUCCESS_LOG = ROOT / "samples" / "success.log"
SUCCESS_TRACE = ROOT / "traces" / "success.json"


def _run(argv, stdin_text="", opener=None):
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(
        argv, stdin=stdin, stdout=stdout, stderr=stderr, opener=opener or (lambda url: None)
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_parse_file_to_output(tmp_path):
    out = tmp_path / "trace.json"
    code, _, _ = _run(["parse", str(SUCCESS_LOG), "-o", str(out)])
    assert code == 0
    trace = json.loads(out.read_text())
    assert trace["schemaVersion"] == "0.1"
    assert trace["traceId"] == "success"
    assert len(trace["events"]) >= 1


def test_parse_stdin_to_stdout():
    code, stdout, _ = _run(["parse", "-"], stdin_text=SUCCESS_LOG.read_text())
    assert code == 0
    trace = json.loads(stdout)
    assert trace["schemaVersion"] == "0.1"


def test_parse_trace_id_from_file_stem(tmp_path):
    log = tmp_path / "myrun.log"
    log.write_text(SUCCESS_LOG.read_text())
    code, stdout, _ = _run(["parse", str(log)])
    assert code == 0
    assert json.loads(stdout)["traceId"] == "myrun"


def test_parse_stdin_trace_id_is_deterministic_hash():
    text = SUCCESS_LOG.read_text()
    _, first, _ = _run(["parse", "-"], stdin_text=text)
    _, second, _ = _run(["parse", "-"], stdin_text=text)
    tid = json.loads(first)["traceId"]
    assert tid == json.loads(second)["traceId"]
    assert tid.startswith("stdin-")


def test_parse_trace_id_override():
    code, stdout, _ = _run(
        ["parse", "-", "--trace-id", "custom-42"], stdin_text=SUCCESS_LOG.read_text()
    )
    assert code == 0
    assert json.loads(stdout)["traceId"] == "custom-42"


def test_view_html_out_inlines_trace(tmp_path):
    out = tmp_path / "viewer.html"
    code, stdout, _ = _run(["view", str(SUCCESS_TRACE), "--html-out", str(out)])
    assert code == 0
    assert str(out) in stdout
    html = out.read_text()
    assert 'id="funcviz-default-trace"' in html
    assert '"schemaVersion":"0.1"' in html


def test_view_injection_escapes_script_close():
    trace = {"schemaVersion": "0.1", "note": "</script><!-- x"}
    template = cli._load_viewer_template()
    injected = cli._inject_default_trace(template, trace)
    assert "</script><!--" not in injected.split("funcviz-default-trace")[1][:2000]
    assert "\\u003c/script\\u003e" in injected


def test_view_injection_requires_exactly_one_placeholder():
    tag = '<script type="application/json" id="funcviz-default-trace">{}</script>'
    for template in ("<html>no placeholder</html>", tag + tag):
        try:
            cli._inject_default_trace(template, {"a": 1})
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def test_view_direct_opens_file_url(tmp_path):
    out = tmp_path / "viewer.html"
    opened = []
    code, _, _ = _run(
        ["view", str(SUCCESS_TRACE), "--html-out", str(out), "--direct"],
        opener=opened.append,
    )
    assert code == 0
    assert opened and opened[0].startswith("file://")


def test_view_invalid_json_returns_1(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    code, _, stderr = _run(["view", str(bad)])
    assert code == 1
    assert "funcviz:" in stderr


def test_record_reads_stdin_and_writes(tmp_path):
    out = tmp_path / "trace.json"
    code, _, _ = _run(["record", "-o", str(out)], stdin_text=SUCCESS_LOG.read_text())
    assert code == 0
    assert json.loads(out.read_text())["schemaVersion"] == "0.1"


def test_record_writes_partial_on_keyboard_interrupt(tmp_path):
    out = tmp_path / "trace.json"
    text = SUCCESS_LOG.read_text()

    class InterruptingStdin:
        def __init__(self, payload):
            self._payload = payload
            self._served = False

        def read(self, _size=-1):
            if not self._served:
                self._served = True
                return self._payload
            raise KeyboardInterrupt

    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli.main(
        ["record", "-o", str(out)],
        stdin=InterruptingStdin(text),
        stdout=stdout,
        stderr=stderr,
        opener=lambda url: None,
    )
    assert code == 0
    assert json.loads(out.read_text())["schemaVersion"] == "0.1"
    assert "interrupted" in stderr.getvalue()


def test_record_partial_without_terminal_event_is_marked_incomplete(tmp_path):
    """#84 — a Ctrl-C partial capture must not read as a completed success."""
    out = tmp_path / "trace.json"
    text = SUCCESS_LOG.read_text()
    tailless = (
        "\n".join(line for line in text.splitlines() if "Executed 'Functions." not in line) + "\n"
    )

    class InterruptingStdin:
        def __init__(self, payload):
            self._payload = payload
            self._served = False

        def read(self, _size=-1):
            if not self._served:
                self._served = True
                return self._payload
            raise KeyboardInterrupt

    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli.main(
        ["record", "-o", str(out)],
        stdin=InterruptingStdin(tailless),
        stdout=stdout,
        stderr=stderr,
        opener=lambda url: None,
    )
    assert code == 0
    trace = json.loads(out.read_text())
    assert trace["metadata"]["incomplete"] is True


def test_parse_multi_invocation_log_fails_with_clear_message(tmp_path):
    """#85 — the CLI surfaces the contract breach and writes nothing."""
    import uuid

    text = SUCCESS_LOG.read_text()
    original = "6a8f3658-2b31-4554-aa86-1ee32a9e679b"
    replacement = str(uuid.uuid4())
    combined = text + "\n" + text.replace(original, replacement)
    log = tmp_path / "multi.log"
    log.write_text(combined)
    out = tmp_path / "trace.json"

    code, _, stderr = _run(["parse", str(log), "-o", str(out)])
    assert code == 1
    assert "funcviz:" in stderr
    assert "2 invocations" in stderr
    assert "one invocation per trace" in stderr
    assert not out.exists()

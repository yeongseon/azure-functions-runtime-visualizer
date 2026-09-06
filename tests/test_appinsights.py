"""App Insights query-result adapter tests (issue #67, PRD §5.1, FR-2).

Fixtures mirror the shape ``az monitor app-insights query ... -o json``
returns (``tables/columns/rows``) and the row content the discovery in issue
#66 observed live: host Executing/Executed bookends in ``message``, ISO
timestamps with 100-ns ticks, structured ``customDimensions``, and NO raw
python-worker lines (App Insights never ingests them).
"""

from __future__ import annotations

import json
from pathlib import Path

from funcviz import cli
from funcviz.appinsights import records_from_query_result
from funcviz.parser import mask_records, parse_trace

ROOT = Path(__file__).resolve().parent.parent
SUCCESS_LOG = ROOT / "samples" / "success.log"
INVOCATION = "6a8f3658-2b31-4554-aa86-1ee32a9e679b"


def _host_rows():
    """Executing/Executed bookends from the real success sample, AI-shaped."""
    rows = []
    for line in SUCCESS_LOG.read_text().splitlines():
        if "Executing 'Functions.hello'" in line or "Executed 'Functions.hello'" in line:
            ts = line.split("]")[0].lstrip("[")
            rows.append(
                [
                    ts,
                    "trace",
                    line.split("] ", 1)[1],
                    "funcviz-ai",
                    json.dumps({"InvocationId": INVOCATION, "ProcessId": "44"}),
                ]
            )
    assert len(rows) == 2
    return rows


def _export(rows, *, tick_noise=True):
    if tick_noise and rows and "." in str(rows[0][0]):
        rows = [list(r) for r in rows]
        rows[0][0] = str(rows[0][0])[:-1] + "6689Z"  # 100-ns ticks variant
    return {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "timestamp", "type": "datetime"},
                    {"name": "itemType", "type": "string"},
                    {"name": "message", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "customDimensions", "type": "object"},
                ],
                "rows": rows,
            }
        ]
    }


def _trace_dict(export):
    records = mask_records(records_from_query_result(export))
    trace = parse_trace(records, trace_id="ai-001")
    from funcviz.appinsights import relabel_input

    return relabel_input(trace).to_dict()


def test_adapter_reuses_parser_body_for_host_bookends():
    trace = _trace_dict(_export(_host_rows()))
    names = [e["event"] for e in trace["events"]]
    assert names == ["InvocationStarted", "InvocationCompleted"]
    assert trace["outcome"] == "success"
    assert trace["input"]["source"] == "app-insights-query"
    assert trace["input"]["adapter"] == "AppInsightsQueryAdapter"
    assert "incomplete" not in trace.get("metadata", {})


def test_missing_worker_lines_report_honestly_as_unknown():
    trace = _trace_dict(_export(_host_rows()))
    lanes = trace["lanes"]
    assert lanes["host"]["status"] == "reached"
    assert lanes["python-worker"]["status"] == "unknown"
    assert lanes["client"]["status"] == "not-reached"


def test_timestamp_tick_normalization_and_defensive_sort():
    rows = list(reversed(_host_rows()))  # export order scrambled
    records = records_from_query_result(_export(rows))
    assert records[0].fields["ts"].endswith("Z")
    assert len(records[0].fields["ts"].split(".")[1][:-1]) == 3
    assert records[0].fields["ts"] < records[1].fields["ts"]
    assert records[0].fields["content"].startswith("Executing")


def test_multi_invocation_export_is_rejected_by_contract_guard():
    other = [r[:] for r in _host_rows()]
    for row in other:
        row[2] = row[2].replace(INVOCATION, "7b1e4769-3c42-5b55-cc97-2ff43b0f780c")
        row[4] = row[4].replace(INVOCATION, "7b1e4769-3c42-5b55-cc97-2ff43b0f780c")
    try:
        _trace_dict(_export(_host_rows() + other))
    except ValueError as exc:
        assert "2 invocations" in str(exc)
    else:
        raise AssertionError("multi-invocation export must be rejected (#85)")


def test_messageless_rows_dropped_and_empty_export_errors():
    export = _export([["2026-09-05T00:45:15.000Z", "request", None, "prod", "{}"]])
    try:
        records_from_query_result(export)
    except ValueError as exc:
        assert "no message-bearing rows" in str(exc)
    else:
        raise AssertionError("message-less export must error, not yield a blank trace")


def test_cli_from_appinsights_flag_end_to_end(tmp_path, capsys):
    export = tmp_path / "prod.json"
    export.write_text(json.dumps(_export(_host_rows())))
    out = tmp_path / "trace.json"
    code = cli.main(
        ["parse", str(export), "--from-appinsights", "-o", str(out)],
        stdin=__import__("io").StringIO(""),
        stdout=__import__("io").StringIO(),
        stderr=__import__("io").StringIO(),
        opener=lambda url: None,
    )
    assert code == 0
    trace = json.loads(out.read_text())
    assert trace["input"]["source"] == "app-insights-query"
    assert [e["event"] for e in trace["events"]] == [
        "InvocationStarted",
        "InvocationCompleted",
    ]


def test_cli_rejects_non_json_as_appinsights_input(tmp_path):
    bad = tmp_path / "prod.log"
    bad.write_text("not json at all")
    code, _, stderr = _run_cli(["parse", str(bad), "--from-appinsights"])
    assert code == 1
    assert "not valid JSON" in stderr


def _run_cli(argv):
    import io

    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli.main(
        argv, stdin=io.StringIO(""), stdout=stdout, stderr=stderr, opener=lambda url: None
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_offset_timestamp_converts_to_true_utc_instant():
    from funcviz.appinsights import _normalize_timestamp

    assert _normalize_timestamp("2026-09-05T09:45:15.123+09:00") == "2026-09-05T00:45:15.123Z"
    assert _normalize_timestamp("2026-09-05T00:45:15-03:30") == "2026-09-05T04:15:15.000Z"
    assert _normalize_timestamp("2026-09-05T00:45:15.1234567Z") == "2026-09-05T00:45:15.123Z"
    assert _normalize_timestamp("2026-09-05T00:45:15Z") == "2026-09-05T00:45:15.000Z"
    # regression shape: 100-ns ticks combined with an ISO offset
    assert _normalize_timestamp("2026-09-05T09:45:15.1234567+09:00") == "2026-09-05T00:45:15.123Z"


def test_unparseable_timestamp_is_a_clear_adapter_error():
    import pytest

    from funcviz.appinsights import _normalize_timestamp

    with pytest.raises(ValueError, match="unparseable timestamp"):
        _normalize_timestamp("not-a-timestamp")


def test_message_row_without_timestamp_errors_at_adapter():
    rows = _host_rows()
    rows[0][0] = None
    import pytest

    with pytest.raises(ValueError, match="without a timestamp"):
        records_from_query_result(_export(rows, tick_noise=False))


def test_equal_ms_timestamps_fall_back_to_export_order():
    """#68 — ms-precision ties keep the export's row order (stable sort)."""
    rows = _host_rows()
    same = "2026-09-05T00:45:15.400Z"
    rows[0][0] = same
    rows[1][0] = same
    records = records_from_query_result(_export(rows, tick_noise=False))
    assert [r.fields["content"][:9] for r in records] == ["Executing", "Executed "]


def test_multi_host_instance_export_is_annotated_not_silent():
    """#68 — spanning host instances lands in metadata.hostInstances."""
    from funcviz.appinsights import relabel_input, with_host_instances
    from funcviz.parser import parse_trace

    rows = _host_rows()
    rows[0][4] = rows[0][4].replace("ProcessId", "HostInstanceId\":\"h-1\",\"ProcessId")
    rows[1][4] = rows[1][4].replace("ProcessId", "HostInstanceId\":\"h-2\",\"ProcessId")
    records = mask_records(records_from_query_result(_export(rows, tick_noise=False)))
    trace = with_host_instances(relabel_input(parse_trace(records, trace_id="ai-2")), records)
    assert trace.metadata.get("hostInstances") == ["h-1", "h-2"]
    # single distinct id -> no annotation
    rows2 = _host_rows()
    for r in rows2:
        r[4] = r[4].replace("ProcessId", "HostInstanceId\":\"h-1\",\"ProcessId")
    records2 = mask_records(records_from_query_result(_export(rows2, tick_noise=False)))
    trace2 = with_host_instances(relabel_input(parse_trace(records2, trace_id="ai-3")), records2)
    assert "hostInstances" not in trace2.metadata


def test_host_instances_annotation_preserves_existing_metadata():
    """#68 — adding hostInstances must not clobber the #84 incomplete marker."""
    from funcviz.appinsights import records_from_query_result, with_host_instances
    from funcviz.parser import parse_trace

    rows = _host_rows()
    rows[0][4] = rows[0][4].replace("ProcessId", "HostInstanceId\":\"h-1\",\"ProcessId")
    rows[1][4] = rows[1][4].replace("ProcessId", "HostInstanceId\":\"h-2\",\"ProcessId")
    records = records_from_query_result(_export(rows, tick_noise=False))
    from dataclasses import replace as _replace

    trace = _replace(parse_trace(records, trace_id="t"), metadata={"incomplete": True})
    merged = with_host_instances(trace, records).to_dict()
    assert merged["metadata"]["incomplete"] is True
    assert merged["metadata"]["hostInstances"] == ["h-1", "h-2"]


def test_cli_wires_host_instances_annotation(tmp_path):
    """#68 — the CLI path emits metadata.hostInstances for a multi-host export."""
    import io
    import json as jsonlib

    rows = _host_rows()
    rows[0][4] = rows[0][4].replace("ProcessId", "HostInstanceId\":\"h-1\",\"ProcessId")
    rows[1][4] = rows[1][4].replace("ProcessId", "HostInstanceId\":\"h-2\",\"ProcessId")
    export = tmp_path / "multi-host.json"
    export.write_text(jsonlib.dumps(_export(rows, tick_noise=False)))
    out = tmp_path / "trace.json"
    code = cli.main(
        ["parse", str(export), "--from-appinsights", "-o", str(out)],
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        opener=lambda url: None,
    )
    assert code == 0
    trace = jsonlib.loads(out.read_text())
    assert trace["metadata"]["hostInstances"] == ["h-1", "h-2"]

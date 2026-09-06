"""Golden-trace regeneration is idempotent and honesty-preserving (issue #47)."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.regen_traces import GOLDENS, main, render  # noqa: E402  (needs sys.path setup)

EXPECTED_TRACE_IDS = {
    "success": "success-001",
    "invocation-fail": "invocation-fail-001",
    "worker-unobserved": "worker-unobserved-001",
    "worker-fail": "worker-fail-001",
}


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g.stem)
def test_render_matches_committed_trace(golden):
    assert render(golden) == golden.trace_path.read_text(encoding="utf-8")


def test_check_mode_passes_for_committed_traces():
    assert main(["--check"]) == 0


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g.stem)
def test_rendered_trace_id_is_pinned(golden):
    expected = EXPECTED_TRACE_IDS[golden.stem]
    assert golden.trace_id == expected
    assert json.loads(render(golden))["traceId"] == expected


def _has_embedded_source(rendered: dict) -> bool:
    application = rendered.get("application")
    return bool(application) and application.get("sourceText") is not None


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g.stem)
def test_rendered_source_embed_matches_honesty_rule(golden):
    rendered = json.loads(render(golden))
    assert _has_embedded_source(rendered) is golden.source


def test_dropping_source_flag_is_caught_against_committed_trace():
    success = next(g for g in GOLDENS if g.stem == "success")
    stripped = render(replace(success, source=False))
    assert stripped != success.trace_path.read_text(encoding="utf-8")
    assert _has_embedded_source(json.loads(stripped)) is False

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from funcviz import cli

pytestmark = pytest.mark.skipif(
    os.environ.get("FUNCVIZ_E2E") != "1",
    reason="set FUNCVIZ_E2E=1 and install Chromium to run viewer browser tests",
)

ROOT = Path(__file__).resolve().parent.parent
SELECTED_EVENT = '#lanes .event[aria-selected="true"]'


def _viewer(tmp_path: Path, trace_name: str) -> Path:
    output = tmp_path / f"{trace_name}.html"
    code = cli.main(
        ["view", str(ROOT / "traces" / f"{trace_name}.json"), "--html-out", str(output)],
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        opener=lambda _url: None,
    )
    assert code == 0
    return output


def test_view_switch_preserves_selection_and_playback_position(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        assert page.locator("body").get_attribute("data-view-mode") == "presentation"
        assert page.locator("[data-presentation-lane]").count() == 4
        page.locator("#presentationNextBtn").click()
        page.locator("#presentationNextBtn").click()
        page.locator("#presentationNextBtn").click()
        before = page.evaluate(
            """(selector) => ({
              selected: document.querySelector(selector)?.dataset.eventId,
              elapsed: document.querySelector('#presentationScrubber')?.dataset.elapsedMs,
              meta: document.querySelector('#presentationMeta')?.textContent,
              progress: window.Funcviz.replayProgressPct()
            })""",
            SELECTED_EVENT,
        )
        page.locator("#inspectTab").click()
        page.wait_for_timeout(150)
        assert page.locator("body").get_attribute("data-view-mode") == "inspect"
        assert page.locator("#lanes .lane").count() == 4
        assert page.locator("#lanes .connector").count() == 6
        page.locator("#presentationTab").click()
        after = page.evaluate(
            """(selector) => ({
              selected: document.querySelector(selector)?.dataset.eventId,
              elapsed: document.querySelector('#presentationScrubber')?.dataset.elapsedMs,
              meta: document.querySelector('#presentationMeta')?.textContent,
              progress: window.Funcviz.replayProgressPct()
            })""",
            SELECTED_EVENT,
        )
        assert after == before
        browser.close()


def test_failure_cutoff_and_forensic_selection_are_honest(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "invocation-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        for _ in range(8):
            button = page.locator("#presentationNextBtn")
            if button.is_disabled():
                break
            button.click()
        assert page.locator("#presentationEvent").text_content() == "InvocationCompleted"
        assert page.locator("#presentationOutcome").get_attribute("data-kind") == "failed"
        assert page.locator("#presentationNextBtn").is_disabled()
        page.locator("#inspectTab").click()
        forensic_connector = page.locator('#lanes .connector[data-to="e5"]')
        assert forensic_connector.get_attribute("data-forensic") == "true"
        page.locator('#lanes .event[data-event-id="e5"]').click()
        page.locator("#presentationTab").click()
        story = page.locator("#presentationStory")
        assert story.get_attribute("data-forensic") == "true"
        assert page.locator("#presentationEvent").text_content() == "Post-failure evidence selected"
        assert page.locator("#presentationScrubber").get_attribute("data-elapsed-ms") == "285"
        assert (
            page.locator('[data-presentation-lane="client"]').get_attribute("data-active")
            == "false"
        )
        assert (
            page.locator('[data-presentation-lane="host"]').get_attribute("data-active") == "true"
        )
        assert page.locator("#presentationNextBtn").is_disabled()
        browser.close()


def test_repeated_handoff_uses_latest_crossing_confidence(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    trace = {
        "traceId": "handoff-confidence",
        "outcome": "success",
        "runtime": {"language": "python", "trigger": "http", "environment": "local"},
        "lanes": {
            "client": {"status": "reached", "confidence": "observed"},
            "host": {"status": "reached", "confidence": "observed"},
            "python-worker": {"status": "unknown", "confidence": "inferred"},
            "application": {"status": "unknown", "confidence": "inferred"},
        },
        "events": [
            {
                "id": "e0",
                "sequence": 0,
                "elapsedMs": 0,
                "lane": "client",
                "event": "First",
                "confidence": "inferred",
                "raw": "",
            },
            {
                "id": "e1",
                "sequence": 1,
                "elapsedMs": 10,
                "lane": "host",
                "event": "Second",
                "confidence": "observed",
                "raw": "",
            },
            {
                "id": "e2",
                "sequence": 2,
                "elapsedMs": 20,
                "lane": "client",
                "event": "Third",
                "confidence": "observed",
                "raw": "",
            },
        ],
    }
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        page.locator("#tracePaste").fill(json.dumps(trace))
        page.locator("#loadPasteBtn").click()
        page.locator("#presentationNextBtn").click()
        page.locator("#presentationNextBtn").click()
        seam = page.locator('[data-presentation-handoff="client-host"]')
        assert seam.get_attribute("data-confidence") == "inferred"
        page.locator("#presentationNextBtn").click()
        assert seam.get_attribute("data-confidence") == "observed"
        assert "observed" in seam.locator(".ph-conf").text_content()
        browser.close()


def test_mobile_transport_stays_aligned_without_page_overflow(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 1800})
        page.goto(html.as_uri())
        geometry = page.evaluate(
            """() => {
              const buttons = [...document.querySelectorAll('.pres-transport button')]
                .map((el) => { const r = el.getBoundingClientRect(); return [r.y, r.height]; });
              const sourceTop = document.querySelector('#presentationSource')
                .getBoundingClientRect().top;
              const scrubberTop = document.querySelector('#presentationScrubber')
                .getBoundingClientRect().top;
              return {
                width: document.documentElement.scrollWidth,
                buttons, sourceTop, scrubberTop
              };
            }"""
        )
        assert geometry["width"] == 360
        assert len({round(item[0], 2) for item in geometry["buttons"]}) == 1
        assert len({round(item[1], 2) for item in geometry["buttons"]}) == 1
        assert geometry["sourceTop"] < geometry["scrubberTop"]
        browser.close()

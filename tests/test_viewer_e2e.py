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
        # #105 — the loader toolbar lives behind the disclosure at rest
        page.locator("#traceLoaderSummary").click()
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


# --------------------------------------------------------------------------
# #99 — additive visual-contract assertions (Fluent / Runtime Schematic).
# Style-only seams; every #97 behavior contract above stays the source of
# truth. These pin the retuned identity so a regression back to pills,
# glows, or card shadows fails loudly.
# --------------------------------------------------------------------------


def _style(page, selector, props, pseudo=None):
    return page.evaluate(
        """(a) => {
          const el = document.querySelector(a.s);
          if (!el) return null;
          const cs = getComputedStyle(el, a.p || null);
          const o = {}; a.ps.forEach(x => o[x] = cs.getPropertyValue(x));
          return o;
        }""",
        {"s": selector, "ps": props, "p": pseudo},
    )


def test_visual_selected_tab_is_underlined_not_a_pill(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        tab = _style(
            page,
            '.view-tab[aria-selected="true"]',
            ["background-color", "border-radius", "box-shadow"],
        )
        container = _style(page, ".view-tabs", ["border-radius"])
        assert tab["background-color"] == "rgba(0, 0, 0, 0)"  # no fill pill
        assert float(tab["border-radius"].split("px")[0]) <= 4
        assert "rgb(0, 120, 212)" in tab["box-shadow"]  # azure underline stroke
        assert float(container["border-radius"].split("px")[0]) <= 4
        browser.close()


def test_visual_actor_terminals_flat_small_radius_no_shadow(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        actor = _style(page, ".pres-actor", ["border-radius", "box-shadow"])
        assert float(actor["border-radius"].split("px")[0]) <= 4
        assert actor["box-shadow"] == "none"
        # CSS-counter designator is pseudo-only — title textContent stays the
        # actor title (the #97 text contract)
        title = page.evaluate(
            "() => document.querySelector('.pres-actor .pres-actor-title').textContent"
        )
        assert title in {"CLIENT", "FUNCTIONS HOST", "PYTHON WORKER", "APPLICATION"}
        browser.close()


def test_visual_active_handoff_packet_motion_respects_reduced_motion(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        for _ in range(4):  # e3 ApplicationFunctionStarted — python-worker→application seam active
            page.locator("#presentationNextBtn").click()
        page.wait_for_timeout(300)  # let the .15s conductor color transition settle
        pulse = _style(
            page,
            '.pres-handoff[data-active="true"] .ph-pulse',
            ["animation-name", "background-color"],
        )
        line = _style(
            page,
            '.pres-handoff[data-active="true"] .ph-line',
            ["border-left-color", "border-left-width"],
        )
        assert pulse["animation-name"] == "ph-travel"  # moving packet, normal motion
        assert pulse["background-color"] == "rgb(0, 120, 212)"  # azure signal
        assert line["border-left-color"] == "rgb(0, 120, 212)"
        assert line["border-left-width"] == "3px"  # weight carries the state

        reduced = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
        )
        rpage = reduced.new_page()
        rpage.goto(html.as_uri())
        for _ in range(4):
            rpage.locator("#presentationNextBtn").click()
        rpulse = _style(
            rpage, '.pres-handoff[data-active="true"] .ph-pulse', ["animation-name", "opacity"]
        )
        rline = _style(
            rpage, '.pres-handoff[data-active="true"] .ph-line', ["border-left-width", "box-shadow"]
        )
        assert rpulse["animation-name"] == "none"  # no travel under reduced motion
        assert rpulse["opacity"] == "0"  # packet disappears…
        assert rline["border-left-width"] == "4px"  # …conductor thickens instead
        assert rline["box-shadow"] == "none"  # discrete weight, never glow
        reduced.close()
        browser.close()


# --------------------------------------------------------------------------
# #104 — additive Fluent Light visual-contract assertions. Theme-only seams;
# #97 behavior and #99 schematic geometry contracts above stay the truth.
# --------------------------------------------------------------------------


def test_visual_light_theme_surfaces_and_text(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        assert page.locator('meta[name="color-scheme"]').get_attribute("content") == "light"
        body = _style(page, "body", ["background-color", "color"])
        assert body["background-color"] == "rgb(255, 255, 255)"  # background1 white
        assert body["color"] == "rgb(32, 31, 30)"  # foreground1 #201F1E
        summary = _style(page, ".summary-text", ["color"])
        assert summary["color"] == "rgb(50, 49, 48)"  # secondary text (fg2 family)
        chassis = _style(page, ".pres-flow", ["background-color"])
        assert chassis["background-color"] == "rgb(250, 249, 248)"  # background2
        browser.close()


def test_visual_light_tab_stays_azure_underline_transparent(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        tab = _style(page, '.view-tab[aria-selected="true"]', ["background-color", "box-shadow"])
        assert tab["background-color"] == "rgba(0, 0, 0, 0)"  # never a fill pill
        assert "rgb(0, 120, 212)" in tab["box-shadow"]  # azure underline survives light
        browser.close()


def test_visual_light_active_actor_azure_rail_no_glow(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        for _ in range(2):
            page.locator("#presentationNextBtn").click()
        page.wait_for_timeout(300)  # rail color transition settle
        rail = _style(
            page,
            '.pres-actor[data-active="true"]',
            ["background-color"],
            "::before",
        )
        actor = _style(page, '.pres-actor[data-active="true"]', ["box-shadow", "border-radius"])
        assert rail["background-color"] == "rgb(0, 120, 212)"  # azure energized rail
        shadow = actor["box-shadow"]
        assert "rgb(0, 120, 212)" in shadow  # azure ring…
        offsets = shadow.replace("rgb(0, 120, 212)", "").split()
        assert offsets == ["0px", "0px", "0px", "1px"]  # …zero blur, 1px stroke — not a glow
        assert float(actor["border-radius"].split("px")[0]) <= 4
        browser.close()


def test_visual_light_semantic_text_is_accessibly_dark(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        # warning/inferred text: dark amber #A15C00 — #FFB900 is banned on white
        warning = _style(page, ".conf-cat--inferred", ["color"])
        assert warning["color"] == "rgb(161, 92, 0)"
        # failure text: dark red #A4262C, never #D13438 on white
        failed = _style(
            page,
            '#presentationFlow .lane-status[data-status="failed-here"]',
            ["color"],
        )
        assert failed["color"] == "rgb(164, 38, 44)"
        # white-on-azure filled primary stays valid
        primary = _style(page, "#loadPasteBtn", ["background-color", "color"])
        assert primary["background-color"] == "rgb(0, 120, 212)"
        assert primary["color"] == "rgb(255, 255, 255)"
        idle_text = _style(
            page,
            '.pres-actor[data-status="not-reached"] .pres-actor-title',
            ["color"],
        )
        assert idle_text["color"] == "rgb(96, 94, 92)"
        browser.close()


# --------------------------------------------------------------------------
# #105 — trace loader disclosure contracts. Native details: closed at rest
# (toolbar chrome leaves the layout AND the focus order), opens on toggle,
# closes on successful loads, stays open on failures.
# --------------------------------------------------------------------------


def _wait_loader_closed(page, timeout=3.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if page.evaluate("window.Funcviz.traceLoaderOpen()") is False:
            return True
        time.sleep(0.05)
    return False


def test_trace_loader_starts_closed_hiding_toolbar(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        assert page.evaluate("window.Funcviz.traceLoaderOpen()") is False  # closed at rest
        assert page.locator("#traceLoaderSummary").is_visible()
        assert not page.locator("#tracePaste").is_visible()  # controls not rendered
        assert not page.locator("#loadStatus").is_visible()  # status hidden with panel
        closed_h = page.evaluate(
            "() => document.querySelector('#traceLoader').getBoundingClientRect().height"
        )
        switch_top_closed = page.evaluate(
            "() => document.querySelector('.view-switch').getBoundingClientRect().top"
        )
        page.locator("#traceLoaderSummary").click()
        open_h = page.evaluate(
            "() => document.querySelector('#traceLoader').getBoundingClientRect().height"
        )
        switch_top_open = page.evaluate(
            "() => document.querySelector('.view-switch').getBoundingClientRect().top"
        )
        # space recovery: closed row is a thin strip; the view switch sits
        # higher than the always-open toolbar baseline it replaces
        assert closed_h < 45
        assert open_h > closed_h + 60
        assert switch_top_closed < switch_top_open - 60
        browser.close()


def test_trace_loader_opens_controls_visible_focusable(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        page.focus("#traceLoaderSummary")
        page.keyboard.press("Enter")  # native keyboard toggle
        assert page.evaluate("window.Funcviz.traceLoaderOpen()") is True
        for selector in (
            "#traceFile",
            "#resetBtn",
            "#tracePaste",
            "#loadPasteBtn",
            ".local-only-note",
        ):
            assert page.locator(selector).is_visible(), selector
        page.locator("#loadPasteBtn").focus()
        focused = page.evaluate("() => document.activeElement.id")
        assert focused == "loadPasteBtn"  # controls join the focus order when open
        browser.close()


def test_invalid_paste_keeps_loader_open_with_error(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        page.locator("#traceLoaderSummary").click()
        page.locator("#tracePaste").fill("not json")
        page.locator("#loadPasteBtn").click()
        assert page.evaluate("window.Funcviz.traceLoaderOpen()") is True
        status = page.locator("#loadStatus")
        assert "Invalid JSON" in status.text_content()
        assert "error" in status.get_attribute("class")
        assert status.is_visible()
        browser.close()


def test_valid_paste_closes_loader_and_updates_trace(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        page.locator("#traceLoaderSummary").click()
        assert page.locator("#presentationScrubberEnd").text_content() == "+2942 ms"
        page.locator("#tracePaste").fill((ROOT / "traces" / "success.json").read_text())
        page.locator("#loadPasteBtn").click()
        assert _wait_loader_closed(page)
        assert "Loaded pasted JSON" in page.locator("#loadStatus").text_content()
        assert page.locator("#presentationScrubberEnd").text_content() == "+294 ms"
        assert page.locator("#traceLoaderMeta").text_content() == "success-001"
        assert page.evaluate("() => document.activeElement.id") == "traceLoaderSummary"
        browser.close()


def test_restore_default_closes_loader(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        page.locator("#traceLoaderSummary").click()
        page.locator("#resetBtn").click()
        assert _wait_loader_closed(page)
        assert "Restored default trace" in page.locator("#loadStatus").text_content()
        assert page.evaluate("() => document.activeElement.id") == "traceLoaderSummary"
        browser.close()


def test_file_input_load_closes_loader(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        page.locator("#traceLoaderSummary").click()
        page.set_input_files("#traceFile", str(ROOT / "traces" / "success.json"))
        assert _wait_loader_closed(page)  # closes only after read+parse succeed
        assert "Loaded success.json" in page.locator("#loadStatus").text_content()
        browser.close()


def test_trace_loader_360_no_overflow(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 1600})
        page.goto(html.as_uri())
        assert page.evaluate("document.documentElement.scrollWidth") == 360
        assert page.locator("#traceLoaderSummary").is_visible()
        summary_w = page.evaluate(
            "() => document.querySelector('#traceLoaderSummary').getBoundingClientRect().width"
        )
        assert summary_w <= 360
        page.locator("#traceLoaderSummary").click()
        assert page.evaluate("document.documentElement.scrollWidth") == 360
        browser.close()


# --------------------------------------------------------------------------
# #106 — compact Presentation confidence legend. ONE #confidenceBanner, two
# CSS projections: Presentation = one-line signal-grammar strip (no title,
# counts, toggle or body), Inspect = the unchanged full banner with counts,
# Details toggle and expansion state preserved across mode switches.
# --------------------------------------------------------------------------


def test_confidence_legend_compact_in_presentation(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "success")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        assert page.locator(".confidence-legend").is_visible()
        # full banner chrome leaves layout AND the focus/a11y tree
        assert not page.locator(".confidence-head").is_visible()
        assert not page.locator(".confidence-body").is_visible()
        assert not page.locator(".confidence-toggle").is_visible()
        assert page.locator(".confidence-toggle").get_attribute("aria-expanded") == "false"
        height = page.evaluate(
            "() => document.querySelector('#confidenceBanner').getBoundingClientRect().height"
        )
        assert height <= 38  # 28–34px strip (+ rounding tolerance)
        samples = page.evaluate(
            """() => {
              const cs = s => getComputedStyle(document.querySelector(s));
              return {
                observed: cs('.confidence-legend-sample--observed').borderTopStyle,
                inferred: cs('.confidence-legend-sample--inferred').borderTopStyle,
              };
            }"""
        )
        assert samples["observed"] == "solid"  # schematic conductor grammar
        assert samples["inferred"] == "dashed"
        # legend is labelled for AT
        assert page.locator(".confidence-legend").get_attribute("aria-label") == "Signal legend"
        browser.close()


def test_confidence_legend_conditional_items(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()

        def items(page):
            return page.locator(".confidence-legend-item").all_inner_texts()

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(_viewer(tmp_path, "success").as_uri())
        assert items(page) == ["observed", "inferred"]  # no unknown / not-reached lanes
        page.goto(_viewer(tmp_path, "worker-unobserved").as_uri())
        assert items(page) == ["observed", "inferred", "unknown"]  # 2 unknown lanes exist
        unknown_sample = page.evaluate(
            """() => {
              const s = document.querySelector('.confidence-legend-sample--unknown');
              return s && getComputedStyle(s).backgroundImage.includes('repeating-linear-gradient');
            }"""
        )
        assert unknown_sample  # hatched/hollow sample grammar
        page.goto(_viewer(tmp_path, "worker-fail").as_uri())
        assert items(page) == ["observed", "inferred", "not reached"]  # downstream lanes stopped
        dotted = page.evaluate(
            """() => getComputedStyle(
                 document.querySelector('.confidence-legend-sample--not-reached')
               ).borderTopStyle"""
        )
        assert dotted == "dotted"
        # no trace: the legend says so instead of implying grammar items
        page.evaluate("window.Funcviz.clear()")
        assert page.locator(".confidence-legend").text_content() == "No trace loaded"
        browser.close()


def test_confidence_legend_mode_switch_and_state(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-fail")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(html.as_uri())
        attrs_before = page.evaluate(
            "() => ({...document.querySelector('#confidenceBanner').dataset})"
        )
        page.locator("#inspectTab").click()
        # Inspect: compact hidden, full banner exactly available
        assert not page.locator(".confidence-legend").is_visible()
        assert page.locator(".confidence-head").is_visible()
        assert page.locator(".confidence-toggle").is_visible()
        assert "not reached" in page.locator(".confidence-oneline").text_content()
        assert not page.locator(".confidence-body-inner").is_visible()  # collapsed at rest
        page.locator(".confidence-toggle").click()  # Details expands
        page.wait_for_timeout(300)
        assert page.locator(".confidence-body-inner").is_visible()
        page.locator("#presentationTab").click()
        # Presentation again: full content hidden, legend back
        assert page.locator(".confidence-legend").is_visible()
        assert not page.locator(".confidence-head").is_visible()
        assert not page.locator(".confidence-body-inner").is_visible()
        page.locator("#inspectTab").click()
        # expansion state survived the round trip
        assert page.locator("#confidenceBanner").get_attribute("data-collapsed") == "false"
        assert page.locator(".confidence-toggle").get_attribute("aria-expanded") == "true"
        assert page.locator(".confidence-body-inner").is_visible()
        attrs_after = page.evaluate(
            "() => ({...document.querySelector('#confidenceBanner').dataset})"
        )
        attrs_after["collapsed"] = attrs_before["collapsed"]  # only the intended toggle delta
        assert attrs_after == attrs_before
        browser.close()


def test_confidence_legend_360_no_overflow(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    html = _viewer(tmp_path, "worker-unobserved")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 1600})
        page.goto(html.as_uri())
        assert page.locator(".confidence-legend").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth") == 360
        legend_w = page.evaluate(
            "() => document.querySelector('.confidence-legend').getBoundingClientRect().width"
        )
        assert legend_w <= 360
        page.locator("#inspectTab").click()
        assert page.evaluate("document.documentElement.scrollWidth") == 360
        browser.close()

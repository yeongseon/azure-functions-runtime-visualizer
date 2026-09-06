from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FUNCVIZ_E2E") != "1" or not os.environ.get("FUNCVIZ_PAGES_HTML"),
    reason="set FUNCVIZ_E2E=1 and FUNCVIZ_PAGES_HTML to run Pages smoke tests",
)


def test_pages_artifact_is_interactive_and_local_only():
    playwright = pytest.importorskip("playwright.sync_api")
    html = Path(os.environ["FUNCVIZ_PAGES_HTML"]).resolve()
    assert html.is_file()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))
        page.goto(html.as_uri())
        assert page.locator("body").get_attribute("data-view-mode") == "presentation"
        assert page.locator("#presentationEvent").text_content() == "Ready to replay"
        page.locator("#presentationNextBtn").click()
        assert page.locator("#presentationEvent").text_content() != "Ready to replay"
        page.locator("#inspectTab").click()
        assert page.locator("#lanes .lane").count() == 4
        page.locator("#presentationTab").click()
        note = page.locator(".local-only-note").text_content()
        assert "stay in this browser" in note
        assert all(url.startswith("file:") for url in requests)
        browser.close()

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def _chromium():
    """One Chromium process per session; per-test isolation comes from `browser`."""
    if os.environ.get("FUNCVIZ_E2E") != "1":
        pytest.skip("set FUNCVIZ_E2E=1 and install Chromium to run viewer browser tests")
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        chromium = pw.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def browser(_chromium):
    """Shared Chromium whose contexts and pages are all closed after each test."""
    yield _chromium
    for context in list(_chromium.contexts):
        context.close()

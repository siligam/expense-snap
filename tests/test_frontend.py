"""
Frontend (browser) tests using Playwright.

These tests start a real FastAPI server with mocked ML models so they run
without a GPU. They cover behaviour that lives entirely in the Vue frontend
and cannot be reached by the pytest/httpx tests.

Run:
    pytest tests/test_frontend.py -v
    pytest tests/test_frontend.py -v --headed   # open browser window
"""
import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import uvicorn
from playwright.sync_api import Page, expect

SAMPLES_DIR = Path(__file__).parent.parent / "samples"

# ---------------------------------------------------------------------------
# Shared mock extraction result — same fields for both uploads so that the
# generated filename would collide without the deduplication fix.
# ---------------------------------------------------------------------------
_MOCK_RESULT = {
    "date": "28/03/2026",
    "category": "food",
    "meal_type": "lunch",
    "total_amount": "100.00",
    "currency": "INR",
    "time": "12:00",
    "ocr_text": "mock ocr",
    "status": "ok",
    "provenance": "mock",
}


# ---------------------------------------------------------------------------
# Live-server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start the FastAPI app on a free port with ML models mocked out."""
    import bill_extractor.app as app_module
    from bill_extractor.config import Config

    tmp = tmp_path_factory.mktemp("fe_data")
    cfg = Config(
        history_file=tmp / "history.json",
        files_dir=tmp / "files",
    )

    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = {
        k: v for k, v in _MOCK_RESULT.items()
        if k not in ("status", "provenance", "ocr_text")
    }

    port = 18765
    fresh_app = app_module.create_app(cfg=cfg)

    with (
        patch.object(app_module, "_extractor", mock_extractor),
        patch.object(app_module, "_semaphore", asyncio.Semaphore(1)),
        patch("bill_extractor.app.ocr_process", return_value=["mock ocr"]),
    ):
        server_cfg = uvicorn.Config(fresh_app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(server_cfg)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait up to 5 s for the port to open
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)

        yield f"http://127.0.0.1:{port}"

        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _upload_and_wait(page: Page, base: str, filepath: Path, mock_result: dict) -> None:
    """Navigate to the upload tab, upload a file, and wait for the ok card."""
    page.goto(base)
    page.route(
        "**/extract",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(mock_result),
        ),
    )
    with page.expect_file_chooser() as fc_info:
        page.locator(".drop-zone").click()
    fc_info.value.set_files(str(filepath))
    # `.src-badge` is only rendered on the ok state card
    page.locator(".src-badge").first.wait_for(timeout=15_000)
    page.unroute("**/extract")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFilenameDeduplication:
    """Generated filenames must be unique even when extracted fields are identical."""

    def test_second_upload_gets_numeric_suffix(self, live_server: str, page: Page):
        """Two bills with same date/category/meal_type → filenames differ by _2 suffix."""
        base = live_server

        _upload_and_wait(page, base, SAMPLES_DIR / "food_01.jpeg", _MOCK_RESULT)
        _upload_and_wait(page, base, SAMPLES_DIR / "food_02.jpeg", _MOCK_RESULT)

        history = httpx.get(f"{base}/history").json()
        generated = [r["filename_generated"] for r in history]

        assert len(generated) == 2, f"Expected 2 history records, got: {generated}"
        assert len(set(generated)) == 2, (
            f"Both records have the same filename_generated: {generated}"
        )
        assert "28-03-2026_food_lunch.jpeg" in generated, generated
        assert "28-03-2026_food_lunch_2.jpeg" in generated, generated


class TestPdfHistoryPreview:
    """PDF entries in the history tab must show a rendered preview on hover."""

    def test_pdf_thumbnail_hover_shows_preview(self, live_server: str, page: Page):
        """Hovering over a PDF icon in history should make the preview overlay visible."""
        base = live_server
        pdf_result = {**_MOCK_RESULT, "category": "travel", "meal_type": ""}

        _upload_and_wait(page, base, SAMPLES_DIR / "trip_06.pdf", pdf_result)

        # Switch to History tab
        page.locator("button.tab", has_text="History").click()
        page.wait_for_timeout(500)

        # Hover over the PDF icon cell (parent div of the <i class="pi-file-pdf">)
        pdf_cell = page.locator("i.pi-file-pdf").first.locator("..")
        expect(pdf_cell).to_be_visible()
        pdf_cell.hover()

        # pdf.js renders asynchronously — allow up to 5 s
        preview_img = page.locator("div[style*='z-index:5000'] img, div[style*='z-index: 5000'] img")
        expect(preview_img).to_be_visible(timeout=5_000)

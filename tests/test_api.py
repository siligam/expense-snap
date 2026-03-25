"""
Tests for the FastAPI /extract endpoint.

Models are mocked — these tests cover the API layer (routing, validation,
response schema) not the ML pipeline (tested in test_ocr_integration.py).
"""
import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import bill_extractor.app as app_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_OCR_LINES = ["Total Payable: ₹226.00", "Date: 27/02/2026", "TIME: 09:36 PM"]

MOCK_FOOD_RESULT = {
    "total_amount": "226.00",
    "currency": "INR",
    "date": "27/02/2026",
    "time": "21:36",
    "category": "food",
    "meal_type": "dinner",
}

MOCK_TRAVEL_RESULT = {
    "category": "travel",
    "date": "27/02/2026",
    "time": "10:31",
    "amount": "42.32",
}


@pytest.fixture(scope="module")
def client():
    """TestClient with models mocked out — fast, no GPU needed."""
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = MOCK_FOOD_RESULT

    with patch.object(app_module, "_extractor", mock_extractor), \
         patch.object(app_module, "_semaphore", __import__("asyncio").Semaphore(1)), \
         patch("bill_extractor.app.ocr_process", return_value=MOCK_OCR_LINES):
        with TestClient(app_module.app, raise_server_exceptions=True) as c:
            yield c


def _jpeg_bytes() -> bytes:
    """Minimal valid JPEG bytes (1×1 white pixel)."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b"\x1e\x1e89\x02\x00\xff\xd9"
    )


def _pdf_bytes() -> bytes:
    """Minimal valid PDF bytes."""
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n" \
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" \
           b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n" \
           b"xref\n0 4\n0000000000 65535 f\n" \
           b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /extract — success cases
# ---------------------------------------------------------------------------

def test_extract_jpeg_returns_200(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert resp.status_code == 200


def test_extract_response_contains_ocr_text(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.jpeg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    data = resp.json()
    assert "ocr_text" in data
    assert isinstance(data["ocr_text"], list)


def test_extract_response_contains_status_ok(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.jpeg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert resp.json()["status"] == "ok"


def test_extract_response_contains_result_fields(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.jpeg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    data = resp.json()
    assert data["category"] == "food"
    assert data["total_amount"] == "226.00"
    assert data["currency"] == "INR"
    assert data["date"] == "27/02/2026"


def test_extract_png_accepted(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.png", io.BytesIO(_jpeg_bytes()), "image/png")},
    )
    assert resp.status_code == 200


def test_extract_webp_accepted(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.webp", io.BytesIO(_jpeg_bytes()), "image/webp")},
    )
    assert resp.status_code == 200


def test_extract_pdf_accepted(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
    )
    assert resp.status_code == 200


def test_extract_pdf_response_schema(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
    )
    data = resp.json()
    assert "ocr_text" in data
    assert "status" in data
    assert "category" in data


# ---------------------------------------------------------------------------
# POST /extract — error cases
# ---------------------------------------------------------------------------

def test_extract_unsupported_type_returns_415(client):
    resp = client.post(
        "/extract",
        files={"file": ("document.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 415


def test_extract_gif_returns_415(client):
    resp = client.post(
        "/extract",
        files={"file": ("image.gif", io.BytesIO(b"GIF89a"), "image/gif")},
    )
    assert resp.status_code == 415


def test_extract_no_file_returns_422(client):
    resp = client.post("/extract")
    assert resp.status_code == 422


def test_extract_empty_file_returns_400(client):
    resp = client.post(
        "/extract",
        files={"file": ("receipt.jpg", io.BytesIO(b""), "image/jpeg")},
    )
    assert resp.status_code == 400

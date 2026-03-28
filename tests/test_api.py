"""
Tests for the FastAPI endpoints.

Models are mocked — these tests cover the API layer (routing, validation,
response schema) not the ML pipeline (tested in test_ocr_integration.py).
"""
import io
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import bill_extractor.app as app_module
from bill_extractor.history import HistoryStore

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


@pytest.fixture()
def full_client(tmp_path):
    """Full-stack TestClient with mocked models and a temp HistoryStore."""
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = MOCK_FOOD_RESULT
    store = HistoryStore(tmp_path / "history.json", tmp_path / "files")

    with patch.object(app_module, "_extractor", mock_extractor), \
         patch.object(app_module, "_semaphore", __import__("asyncio").Semaphore(1)), \
         patch.object(app_module, "_store", store), \
         patch("bill_extractor.app.ocr_process", return_value=MOCK_OCR_LINES):
        with TestClient(app_module.app, raise_server_exceptions=True) as c:
            yield c, store


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


# ---------------------------------------------------------------------------
# History endpoints
# ---------------------------------------------------------------------------

def test_history_get_empty(full_client):
    c, _ = full_client
    resp = c.get("/history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_history_post_record(full_client):
    c, store = full_client
    rec = {"hash": "test1", "filename": "r.jpg", "category": "food"}
    resp = c.post("/history", data={"record": json.dumps(rec)})
    assert resp.status_code == 200
    assert resp.json()["hash"] == "test1"
    assert len(store.all()) == 1


def test_history_post_with_file(full_client):
    c, store = full_client
    rec = {"hash": "withfile", "filename": "r.jpg"}
    resp = c.post(
        "/history",
        data={"record": json.dumps(rec)},
        files={"file": ("r.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("original_file") == "withfile.jpg"
    assert store.get_file_path("withfile.jpg") is not None


def test_history_get_returns_records(full_client):
    c, store = full_client
    store.upsert({"hash": "h_get", "x": 1})
    resp = c.get("/history")
    assert resp.status_code == 200
    hashes = [r["hash"] for r in resp.json()]
    assert "h_get" in hashes


def test_history_delete_existing(full_client):
    c, store = full_client
    store.upsert({"hash": "h_del"})
    resp = c.delete("/history/h_del")
    assert resp.status_code == 200
    assert store.get("h_del") is None


def test_history_delete_missing(full_client):
    c, _ = full_client
    resp = c.delete("/history/no_such_hash")
    assert resp.status_code == 404


def test_history_delete_removes_file(full_client):
    c, store = full_client
    store.upsert({"hash": "h_with_file", "original_file": "h_with_file.jpg"})
    store.save_file("h_with_file.jpg", b"data")
    c.delete("/history/h_with_file")
    assert store.get_file_path("h_with_file.jpg") is None


def test_history_post_invalid_json_returns_422(full_client):
    c, _ = full_client
    resp = c.post("/history", data={"record": "not json"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Storage endpoint
# ---------------------------------------------------------------------------

def test_storage_returns_byte_counts(full_client):
    c, store = full_client
    store.upsert({"hash": "s1"})
    resp = c.get("/storage")
    assert resp.status_code == 200
    data = resp.json()
    assert "history_bytes" in data
    assert "files_bytes" in data
    assert "total_bytes" in data
    assert data["total_bytes"] >= 0


# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------

def test_get_file_returns_content(full_client):
    c, store = full_client
    store.save_file("serve_me.jpg", _jpeg_bytes())
    resp = c.get("/files/serve_me.jpg")
    assert resp.status_code == 200
    assert resp.content == _jpeg_bytes()


def test_get_file_missing_returns_404(full_client):
    c, _ = full_client
    resp = c.get("/files/ghost.jpg")
    assert resp.status_code == 404


def test_get_file_path_traversal_rejected(full_client):
    c, _ = full_client
    resp = c.get("/files/../secret.txt")
    # FastAPI will reject or reroute; either 400 or 404 is acceptable
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

def test_get_config_returns_fields(full_client):
    c, _ = full_client
    import bill_extractor.app as am
    import bill_extractor.config as cfg_mod
    mock_cfg = cfg_mod.Config()
    import unittest.mock as mock
    with mock.patch.object(am, "_config", mock_cfg):
        resp = c.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "data_dir" in data
    assert "ocr_servers" in data
    assert "port" in data
    assert isinstance(data["ocr_servers"], list)


def test_patch_config_ocr_servers(full_client, tmp_path):
    c, _ = full_client
    import bill_extractor.app as am
    import bill_extractor.config as cfg_mod
    mock_cfg = cfg_mod.Config(
        history_file=tmp_path / "history.json",
        files_dir=tmp_path / "files",
    )
    servers = [{"url": "local", "enabled": True}, {"url": "http://gpu:8080", "enabled": True}]
    import unittest.mock as mock
    with mock.patch.object(am, "_config", mock_cfg):
        resp = c.patch("/config", json={"ocr_servers": servers})
        assert resp.status_code == 200
        assert mock_cfg.ocr_servers == servers


def test_patch_config_ensures_local_entry(full_client, tmp_path):
    """Patching without a local entry should auto-insert one."""
    c, _ = full_client
    import bill_extractor.app as am
    import bill_extractor.config as cfg_mod
    mock_cfg = cfg_mod.Config(
        history_file=tmp_path / "history.json",
        files_dir=tmp_path / "files",
    )
    import unittest.mock as mock
    with mock.patch.object(am, "_config", mock_cfg):
        resp = c.patch("/config", json={"ocr_servers": [{"url": "http://gpu:8080", "enabled": True}]})
        assert resp.status_code == 200
        assert any(s["url"] == "local" for s in mock_cfg.ocr_servers)


def test_patch_config_unknown_field_rejected(full_client):
    c, _ = full_client
    resp = c.patch("/config", json={"history_file": "/tmp/evil.json"})
    assert resp.status_code == 422

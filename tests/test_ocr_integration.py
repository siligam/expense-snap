"""
Integration tests: OCR pipeline on real sample images.
These tests load the DocTR model but NOT the LLM.
Mark slow tests with: pytest -m slow
"""
import pytest
from pathlib import Path
from bill_extractor.ocr_reader import process

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


# ---------------------------------------------------------------------------
# Smoke tests — every sample image produces non-empty OCR output
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "food_01.jpeg", "food_02.jpeg", "food_03.jpeg",
    "food_04.jpeg", "food_05.jpeg", "food_06.jpeg", "food_07.jpeg",
    "hotel_01.jpeg",
    "trip_01.jpeg", "trip_02.jpeg", "trip_03.jpeg",
])
def test_ocr_produces_output(filename):
    lines = process(str(SAMPLES_DIR / filename))
    assert isinstance(lines, list)
    assert len(lines) > 0, f"OCR returned no lines for {filename}"
    assert all(isinstance(l, str) for l in lines)


# ---------------------------------------------------------------------------
# food_07.jpeg — Cafe Niloufer Airport (regression: 270.00 was corrupted)
# ---------------------------------------------------------------------------

def test_food07_amounts_not_corrupted(food_receipt_lines):
    """Regression: rupee-symbol fixer must not corrupt 270.xx amounts."""
    joined = "\n".join(food_receipt_lines)
    assert "270.00" in joined, "TOTAL AMT 270.00 missing or corrupted"
    assert "270.02" in joined, "GROSS AMT 270.02 missing or corrupted"
    assert "257.16" in joined, "NET AMT 257.16 missing or corrupted"
    # Ensure the corruption pattern is gone
    assert "₹0.00" not in joined
    assert "₹0.02" not in joined


def test_food07_date_and_time_present(food_receipt_lines):
    joined = "\n".join(food_receipt_lines)
    assert "28-FEB-2026" in joined or "28/02/2026" in joined
    assert "07:11" in joined or "19:11" in joined  # OCR may give 12h or 24h


def test_food07_total_amt_label_present(food_receipt_lines):
    joined = "\n".join(food_receipt_lines)
    assert "TOTAL AMT" in joined


# ---------------------------------------------------------------------------
# trip_01.jpeg — Auto ride receipt
# ---------------------------------------------------------------------------

def test_trip01_amount_present(trip_receipt_lines):
    joined = "\n".join(trip_receipt_lines)
    assert "42.32" in joined


def test_trip01_date_present(trip_receipt_lines):
    joined = "\n".join(trip_receipt_lines)
    assert "27 Feb" in joined or "27/02" in joined


# ---------------------------------------------------------------------------
# hotel_01.jpeg — Cocoon Hotel invoice
# ---------------------------------------------------------------------------

def test_hotel01_total_present(hotel_receipt_lines):
    joined = "\n".join(hotel_receipt_lines)
    assert "926.00" in joined


def test_hotel01_dates_present(hotel_receipt_lines):
    joined = "\n".join(hotel_receipt_lines)
    assert "23/02/2026" in joined   # check-in
    assert "28/02/2026" in joined   # check-out


def test_hotel01_noise_filtered(hotel_receipt_lines):
    """Email addresses and URLs should be stripped by the noise filter."""
    import re
    email_pattern = re.compile(r"\S+@\S+\.\S+")
    url_pattern = re.compile(r"https?://\S+")
    for line in hotel_receipt_lines:
        assert not email_pattern.search(line), f"Email leaked through: {line}"
        assert not url_pattern.search(line), f"URL leaked through: {line}"

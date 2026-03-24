"""Shared pytest fixtures."""
from pathlib import Path
import pytest

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


@pytest.fixture(scope="session")
def samples_dir():
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def food_receipt_lines():
    """OCR lines from food_07.jpeg (Cafe Niloufer, TOTAL AMT 270.00)."""
    from bill_extractor.ocr_reader import process
    return process(str(SAMPLES_DIR / "food_07.jpeg"))


@pytest.fixture(scope="session")
def trip_receipt_lines():
    """OCR lines from trip_01.jpeg (auto ride, 42.32)."""
    from bill_extractor.ocr_reader import process
    return process(str(SAMPLES_DIR / "trip_01.jpeg"))


@pytest.fixture(scope="session")
def hotel_receipt_lines():
    """OCR lines from hotel_01.jpeg (Cocoon Hotel, 926.00)."""
    from bill_extractor.ocr_reader import process
    return process(str(SAMPLES_DIR / "hotel_01.jpeg"))

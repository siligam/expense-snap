"""
Bill processing pipeline: image → OCR → structured JSON.

Usage:
    python main.py <image_path> [<image_path> ...]

Example:
    python main.py food_04.jpeg
    python main.py receipt1.jpg receipt2.jpg
"""
from __future__ import annotations

import json
import sys
import time

from .ocr_reader import process as ocr_process
from .bill_parser import BillingInformationExtractor


def process_bill(image_path: str, extractor: BillingInformationExtractor) -> tuple[dict, float, float]:
    t0 = time.perf_counter()
    lines = ocr_process(image_path)
    t1 = time.perf_counter()
    result = extractor.extract(lines)
    t2 = time.perf_counter()
    return result, t1 - t0, t2 - t1


def main():
    if len(sys.argv) < 2:
        print("Usage: bill-extractor-cli <image_path> [<image_path> ...]")
        sys.exit(1)

    t_load_start = time.perf_counter()
    extractor = BillingInformationExtractor()
    t_load_end = time.perf_counter()
    print(f"Model loaded in {t_load_end - t_load_start:.1f}s\n")

    for image_path in sys.argv[1:]:
        print(f"--- {image_path} ---")
        result, ocr_time, parse_time = process_bill(image_path, extractor)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"  OCR:   {ocr_time:.2f}s")
        print(f"  Parse: {parse_time:.2f}s")
        print(f"  Total: {ocr_time + parse_time:.2f}s\n")


if __name__ == "__main__":
    main()

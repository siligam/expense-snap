from __future__ import annotations

import re

from doctr.io import DocumentFile
from doctr.models import ocr_predictor

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = ocr_predictor(pretrained=True)
    return _model

# ---------------------------------------------------------------------------
# Noise patterns common on Indian receipts that carry no useful expense data
# ---------------------------------------------------------------------------
_NOISE_PATTERNS = [
    re.compile(r, re.IGNORECASE) for r in [
        r"^[A-Z0-9]{15}$",                          # bare GSTIN (e.g. 27AAKCN6710H1ZC)
        r"gstin?\s*[:\-]?\s*[A-Z0-9]{15}",          # "GST: 27AAKCN..."
        r"fssai",                                    # FSSAI licence line
        r"cin\s*(no\.?|number)?",                    # CIN No.
        r"pan\s*(no\.?|number)?",                    # PAN No.
        r"irn\s*(no\.?|number)?",                    # IRN No.
        r"^\+?[\d\s\-]{8,15}$",                      # standalone phone number
        r"https?://\S+",                             # URLs
        r"\S+@\S+\.\S+",                             # email addresses
        r"thank\s*you",                              # "Thank You Visit Again"
        r"visit\s*again",
        r"have\s*a\s*(nice|good|great|wonderful)",
        r"powered\s*by",
        r"printed\s*by",
    ]
]


def _is_noise(line: str) -> bool:
    """Return True if the line carries no useful expense information."""
    s = line.strip()
    if not s:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.search(s):
            return True
    return False


def filter_noise(lines: list[str]) -> list[str]:
    """Remove noise lines before sending OCR text to the LLM."""
    return [l for l in lines if not _is_noise(l)]


def _fix_rupee_symbol_misread(text: str) -> str:
    """
    Fix common OCR misreads of the rupee symbol (₹).

    Two patterns are handled:

    1. ₹ misread as "7": only fires when "7" starts a token of 3+ digits,
       so small prices like 74.00 or 76.00 are left untouched.
       Also requires the "7" is not preceded by "." or a digit, preventing
       false matches inside decimals like 10.76.
       Examples: "7500" → "₹500", "7226.00" → "₹226.00"

    2. ₹ misread as "1 " (one + space) after a label colon: e.g. OCR reads
       "Total Payable: ₹ 226.00" as "Total Payable: 1 226.00".
       Only fires when a standalone "1" immediately follows ": " and is
       followed by a 2+ digit number.
       Examples: "Total Payable: 1 226.00" → "Total Payable: ₹226.00"
    """
    # Pattern 1: "7" misread — two branches to avoid false positives on small
    # prices (74.00, 76.00) and decimal digits (10.76):
    #   branch A: 3+ consecutive digits  → handles 7500, 7226.00
    #   branch B: 1-2 digits then comma-thousands → handles 71,234.50
    text = re.sub(
        r'(?<![.\d])7(\d{3,}[\d,]*(?:\.\d+)?|\d{1,2},\d{3}(?:,\d{3})*(?:\.\d+)?)\b',
        r'₹\1',
        text
    )
    # Pattern 2: "1 NNN" after a colon — ₹ misread as "1 "
    text = re.sub(
        r'(:\s*)1\s+(\d{2,}[\d,]*(?:\.\d+)?)',
        r'\1₹\2',
        text
    )
    return text


def correct_ocr_errors(lines: list[str]) -> list[str]:
    """Apply post-OCR corrections for common misinterpretations."""
    return [_fix_rupee_symbol_misread(line) for line in lines]


# ---------------------------------------------------------------------------
# Core OCR functions
# ---------------------------------------------------------------------------

def readimage(image_path: str) -> dict:
    doc = DocumentFile.from_images(image_path)
    result = _get_model()(doc)
    return result.export()


def readpdf(pdf_path: str) -> dict:
    doc = DocumentFile.from_pdf(pdf_path)
    result = _get_model()(doc)
    return result.export()


def readimages(*image_paths: str) -> dict:
    doc = DocumentFile.from_images(*image_paths)
    result = _get_model()(doc)
    return result.export()


def extract_words(result_json: dict) -> list[dict]:
    words = []
    for page in result_json["pages"]:
        for block in page["blocks"]:
            for line in block["lines"]:
                for word in line["words"]:
                    (x1, y1), (x2, y2) = word["geometry"]
                    words.append({
                        "text":  word["value"],
                        "x":     (x1 + x2) / 2,
                        "y":     (y1 + y2) / 2,
                        "x_min": x1,
                    })
    return words


def cluster_lines(words: list[dict], y_threshold: float = 0.015) -> list[list[dict]]:
    """Group words into lines by proximity on the y-axis (top → bottom)."""
    words = sorted(words, key=lambda w: (w["y"], w["x"]))
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_y = None
    for word in words:
        if current_y is None:
            current_y = word["y"]
            current_line.append(word)
            continue
        if abs(word["y"] - current_y) < y_threshold:
            current_line.append(word)
        else:
            lines.append(current_line)
            current_line = [word]
            current_y = word["y"]
    if current_line:
        lines.append(current_line)
    for line in lines:
        line.sort(key=lambda w: w["x_min"])
    return lines


def getlines(lines: list[list[dict]]) -> list[str]:
    return [" ".join(w["text"] for w in line) for line in lines]


def process(file_path: str) -> list[str]:
    """Full pipeline: image or PDF → OCR → sorted lines → corrected → noise filtered."""
    if file_path.lower().endswith(".pdf"):
        data = readpdf(file_path)
    else:
        data = readimage(file_path)
    words = extract_words(data)
    lines = cluster_lines(words)
    texts = getlines(lines)
    texts = correct_ocr_errors(texts)
    return filter_noise(texts)


if __name__ == "__main__":
    import sys
    from pprint import pprint
    image = sys.argv[1] if len(sys.argv) > 1 else "food_04.jpeg"
    pprint(process(image))

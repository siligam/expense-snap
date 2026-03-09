from __future__ import annotations

import re

from doctr.io import DocumentFile
from doctr.models import ocr_predictor

model = ocr_predictor(pretrained=True)

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


# ---------------------------------------------------------------------------
# Core OCR functions
# ---------------------------------------------------------------------------

def readimage(image_path: str) -> dict:
    doc = DocumentFile.from_images(image_path)
    result = model(doc)
    return result.export()


def readimages(*image_paths: str) -> dict:
    doc = DocumentFile.from_images(*image_paths)
    result = model(doc)
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


def process(image_path: str) -> list[str]:
    """Full pipeline: image → OCR → sorted lines → noise filtered."""
    data  = readimage(image_path)
    words = extract_words(data)
    lines = cluster_lines(words)
    texts = getlines(lines)
    return filter_noise(texts)


if __name__ == "__main__":
    import sys
    from pprint import pprint
    image = sys.argv[1] if len(sys.argv) > 1 else "food_04.jpeg"
    pprint(process(image))

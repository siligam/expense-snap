#!/usr/bin/env python3
"""Extract bill summary from receipt images and app screenshots using EasyOCR.

Two extraction strategies, chosen automatically by detect_image_type():

  extract_receipt_summary()          -- physical receipts (scanned/photographed paper)
      Amount lives after a 'total' label (Grand Total, Total Fare, etc.).
      Fields: vendor, date, bill_no, grand_total.

  extract_trip_screenshot_summary()  -- mobile app trip screenshots (Uber/Ola etc.)
      Amount is a standalone ₹ line right after date/time; no label.
      Fields: service_type, driver, date, pickup, dropoff, grand_total.

Rupee symbol handling:
  EasyOCR on paper receipts:    ₹63.00  → '{63.00'  (₹ → '{', separated)
  EasyOCR on app screenshots:   ₹42.32  → '242.32'  (₹ → '2', merged)
  Fix: always strip the first character of the identified amount block, since
  that character is always the misread ₹ (whether '{', '2', '%', etc.).
"""

import re
import easyocr

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(['en'])
    return _reader


def _parse_amount(text):
    """Strip leading non-numeric chars and internal spaces, return float or None."""
    cleaned = re.sub(r'^[^0-9]+', '', text.strip()).replace(',', '.').replace(' ', '')
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def detect_image_type(results):
    """Infer image type from OCR text signals.

    Returns 'trip_screenshot', 'receipt', or 'unknown'.

    Screenshot signals (strong): 'trip details' title, 'receipt' + 'invoice'
    buttons appearing together.

    Receipt signals: total/fare/booking/bill keywords typical of printed slips.
    """
    all_text = ' '.join(t.lower() for _, t, _ in results)

    if 'trip details' in all_text:
        return 'trip_screenshot'
    if re.search(r'\breceipt\b', all_text) and re.search(r'\binvoice\b', all_text):
        return 'trip_screenshot'
    if re.search(r'grand\s+total|total\s+fare|sub\s*total|booking\s+detail|bill\s*no|fare\s+detail', all_text):
        return 'receipt'

    return 'unknown'


# ---------------------------------------------------------------------------
# Core extraction logic (operate on pre-fetched EasyOCR results)
# ---------------------------------------------------------------------------

# Labels indicating a final total; exclude intermediate lines
_TOTAL_LABEL_RE = re.compile(r'\btotal\b', re.IGNORECASE)
_EXCLUDE_TOTAL_RE = re.compile(
    r'sub\s*total|total\s*qty|qty.*total|total\s*tax|total\s*range|distance\s*range',
    re.IGNORECASE,
)

# Date patterns for screenshots: "27 Feb 10.31AM", "28 Feb 1243PM" (no separator)
_TRIP_DATE_RE = re.compile(
    r'\d{1,2}\s+\w+\s+\d{2,4}(?:[.:]\d{2})?\s*[AP]M',
    re.IGNORECASE,
)
_TIME_ONLY_RE = re.compile(r'^\d{1,2}[.:]\d{2}\s*[AP]M$', re.IGNORECASE)
_SERVICE_RE = re.compile(r'\b(auto|cab|bike|moto|electric)\s+ride\b', re.IGNORECASE)


def _extract_receipt(results):
    summary = {'type': 'receipt', 'vendor': None, 'date': None, 'bill_no': None, 'grand_total': None}
    total_candidates = []

    for i, (bbox, text, prob) in enumerate(results):
        t = text.strip()
        tl = t.lower()

        # Vendor: first high-confidence block
        if summary['vendor'] is None and prob >= 0.85:
            summary['vendor'] = t

        # Date: DD/MM/YY, DD/MM/YYYY, or YYYY-MM-DD (ISO)
        if summary['date'] is None:
            m = re.search(r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{2,4})', t)
            if m:
                summary['date'] = m.group(1)

        # Bill/trip reference number: inline or in the immediately following block
        if summary['bill_no'] is None:
            m = re.search(r'(?:bill|trip)\s*(?:no|#)[.:;=\s]+(\S+)', tl)
            if m:
                summary['bill_no'] = m.group(1)
            elif re.search(r'(?:bill|trip)\s*(?:no|#)', tl) and i + 1 < len(results):
                _, nxt, _ = results[i + 1]
                m = re.search(r'(\S+)', nxt)
                if m:
                    summary['bill_no'] = m.group(1)

        # Total label: collect candidates, keep the last (Grand Total > Sub Total)
        if _TOTAL_LABEL_RE.search(t) and not _EXCLUDE_TOTAL_RE.search(t):
            for j in range(i + 1, min(i + 4, len(results))):
                _, amt_text, _ = results[j]
                amount = _parse_amount(amt_text)
                if amount is not None and amount > 0:
                    total_candidates.append(amount)
                    break

    if total_candidates:
        summary['grand_total'] = total_candidates[-1]
    return summary


def _extract_trip_screenshot(results):
    summary = {
        'type': 'trip_screenshot',
        'service_type': None, 'driver': None, 'date': None,
        'pickup': None, 'dropoff': None, 'grand_total': None,
    }
    date_index = None

    for i, (bbox, text, prob) in enumerate(results):
        t = text.strip()

        # Service type + driver.
        # Handles two layouts:
        #   "Auto ride with dattatray"  → single block
        #   "Auto ride with" + "Chandrakant" → two blocks (split at line break)
        #   "Auto ride" + "with dattatray" → two blocks
        if summary['service_type'] is None and _SERVICE_RE.search(t):
            service = t
            if i + 1 < len(results):
                _, nxt, _ = results[i + 1]
                nxt = nxt.strip()
                if re.search(r'^with\s+\w+', nxt, re.IGNORECASE):
                    # next block is "with <name>"
                    service = t + ' ' + nxt
                    summary['driver'] = re.sub(r'^with\s+', '', nxt, flags=re.IGNORECASE)
                elif t.lower().rstrip().endswith('with'):
                    # current block ends with "with", next block is the driver name
                    service = t + ' ' + nxt
                    summary['driver'] = nxt
            summary['service_type'] = service

        # Date/time line — also matches formats without separator (e.g. "1243PM")
        if summary['date'] is None and _TRIP_DATE_RE.search(t):
            summary['date'] = t
            date_index = i

        # Amount: first short block after the date line.
        # Always strip the leading character — it is always the ₹ symbol,
        # whether EasyOCR read it as '2', '{', or '%'.
        if date_index is not None and summary['grand_total'] is None and i > date_index:
            if len(t) > 20 or _TIME_ONLY_RE.match(t):
                continue
            amount = _parse_amount(t[1:]) if len(t) > 1 else None
            if amount is None:
                amount = _parse_amount(t)  # fallback if stripping first char fails
            if amount is not None and 1 <= amount <= 10000:
                summary['grand_total'] = amount

        # Pickup/dropoff: address blocks that contain an inline time
        if len(t) > 15 and re.search(r'\d{1,2}[.:]\d{2}\s*[AP]M', t, re.IGNORECASE):
            addr = re.sub(r'\s*\d{1,2}[.:]\d{2}\s*[AP]M\s*', '', t, flags=re.IGNORECASE).strip().rstrip(';,')
            if summary['pickup'] is None:
                summary['pickup'] = addr
            elif summary['dropoff'] is None:
                summary['dropoff'] = addr

    return summary


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_receipt_summary(file_path):
    """Extract summary from a scanned/photographed paper receipt."""
    return _extract_receipt(get_reader().readtext(file_path))


def extract_trip_screenshot_summary(file_path):
    """Extract summary from a mobile app trip screenshot (Uber/Ola etc.)."""
    return _extract_trip_screenshot(get_reader().readtext(file_path))


def extract_summary(file_path, image_type='auto'):
    """Extract bill summary, auto-detecting image type when image_type='auto'.

    Args:
        file_path:  path to the image file.
        image_type: 'auto' (default), 'receipt', or 'trip_screenshot'.

    Returns a dict whose keys depend on the detected type.
    """
    results = get_reader().readtext(file_path)

    if image_type == 'auto':
        image_type = detect_image_type(results)

    if image_type == 'trip_screenshot':
        return _extract_trip_screenshot(results)
    elif image_type == 'receipt':
        return _extract_receipt(results)
    else:
        return {'type': 'unknown', 'raw_text': ' '.join(t for _, t, _ in results)}


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------

def print_summary(file_path, image_type='auto', expected=None):
    print(f"\n{'='*60}")

    s = extract_summary(file_path, image_type)
    detected = s['type']
    print(f"File : {file_path}")
    print(f"Type : {detected}")
    print('-'*60)

    if detected == 'receipt':
        print(f"  Vendor      : {s['vendor']}")
        print(f"  Date        : {s['date']}")
        print(f"  Bill No.    : {s['bill_no']}")
        print(f"  Grand Total : ₹{s['grand_total']}")
    elif detected == 'trip_screenshot':
        print(f"  Service     : {s['service_type']}")
        print(f"  Driver      : {s['driver']}")
        print(f"  Date        : {s['date']}")
        print(f"  Pickup      : {s['pickup']}")
        print(f"  Dropoff     : {s['dropoff']}")
        print(f"  Grand Total : ₹{s['grand_total']}")
    else:
        print(f"  (unknown image type)")

    if expected is not None:
        match = s.get('grand_total') is not None and abs(s['grand_total'] - expected) < 0.01
        print(f"  Expected    : ₹{expected}")
        print(f"  Match       : {'✓ YES' if match else '✗ NO'}")

    print('='*60)
    return s


if __name__ == '__main__':
    BASE = '/Users/pasili001/Downloads/pranitha_bill_app'

    test_cases = [
        (f'{BASE}/food_01.jpeg',  63.00),
        (f'{BASE}/food_02.jpeg', 231.00),
        (f'{BASE}/trip_01.jpeg',  42.32),
        (f'{BASE}/trip_02.jpeg', 178.50),
        (f'{BASE}/trip_03.jpeg', 983.00),
    ]

    for path, expected in test_cases:
        print_summary(path, expected=expected)

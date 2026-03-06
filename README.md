# expense-snap

Extract expense summaries from receipt photos and mobile app trip screenshots using EasyOCR.

## Supported image types

| Type | Examples | Detected by |
|------|----------|-------------|
| `receipt` | Restaurant bills, prepaid taxi slips | "Grand Total", "Total Fare", "Sub Total" labels |
| `trip_screenshot` | Uber/Ola trip detail screenshots | "Trip details" heading, Receipt + Invoice buttons |

## Installation

```bash
pip install .
```

## Usage

### Web app
```bash
bill-extractor
# open http://127.0.0.1:5050
```

### Python API
```python
from bill_extractor import extract_summary

summary = extract_summary('food_01.jpeg')           # auto-detect type
summary = extract_summary('trip_01.jpeg', 'trip_screenshot')  # explicit type

print(summary['grand_total'])  # e.g. 63.0
```

## Requirements

- Python >= 3.8
- Flask >= 3.0
- EasyOCR >= 1.7
- Pillow >= 10.0

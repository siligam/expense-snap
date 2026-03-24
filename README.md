# Bill Extractor

Automatically extract structured expense data from receipt photos and PDFs using a two-stage AI pipeline: **DocTR** for OCR and **Qwen2.5-1.5B-Instruct** for structured field extraction. Results are served through a web interface with drag-and-drop upload, session history, filtering, and manual correction support.

---

## How it works

```
Receipt photo or PDF  →  DocTR OCR  →  Qwen2.5-1.5B LLM  →  Structured JSON
```

1. **DocTR** reads the receipt image or PDF and extracts raw text lines
2. A two-step LLM pipeline first classifies the receipt category (food / travel / hotel), then extracts the relevant fields for that category
3. Results are displayed in the web UI and persisted across sessions

### Extracted fields

| Category | Fields |
|----------|--------|
| **Food** | date, time, total amount, currency, meal type (breakfast / lunch / dinner — inferred from time) |
| **Travel** | date, time, amount |
| **Hotel** | guest name, check-in, check-out, stay duration (days), amount, currency |

---

## Requirements

- Python 3.10 or later
- [Conda](https://docs.conda.io/) (recommended) or any Python virtual environment
- ~4 GB disk space for model weights
- Apple Silicon (MPS), NVIDIA GPU (CUDA), or CPU — auto-detected at runtime

---

## Quick start

### 1. Create a conda environment

```bash
conda create -n ocr python=3.11 -y
conda activate ocr
```

### 2. Install the package

From the repo root:

```bash
pip install -e .
```

> **NVIDIA GPU users** — install a CUDA-enabled PyTorch wheel *before* the above step:
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cu121
> ```

### 3. Download the models (one-time setup)

This downloads the DocTR OCR models and Qwen2.5-1.5B-Instruct weights (~3.5 GB total) for offline use:

```bash
bill-extractor-download
```

Run this once. After the first download the app runs fully offline.

### 4. Start the web app

```bash
bill-extractor
```

Open your browser at **http://localhost:8080**

---

## Web interface

- **Drag and drop** receipt images or PDFs anywhere on the page (or click to browse)
- **Multiple files** can be uploaded at once — each is processed in order
- **Duplicate detection** — the same image is never processed twice; cached results are returned instantly
- **Current Session tab** — live results with extracted fields, plain text (copy-paste ready), and raw OCR text
- **History tab** — all past sessions with sort (by date / category) and filter (date range, category, amount) controls
- **Good Result / Bad Result** — mark each extraction; Bad Result opens a correction textarea whose content is persisted
- **Reset** — saves new items to history and clears the current session

---

## Command-line interface

Process one or more images directly without the web UI:

```bash
bill-extractor-cli samples/food_01.jpeg samples/trip_01.jpeg
```

Output includes structured JSON and per-image timing:

```
Model loaded in 4.8s

--- food_01.jpeg ---
{
  "total_amount": "63.00",
  "currency": "INR",
  "date": "24/02/2026",
  "time": "19:55",
  "category": "food",
  "meal_type": "dinner"
}
  OCR:   1.7s
  Parse: 6.2s
  Total: 7.9s
```

---

## Project structure

```
bill_extractor/
├── bill_extractor/          # Python package
│   ├── __init__.py          # package version
│   ├── app.py               # Flask web application
│   ├── bill_examples.py     # few-shot OCR examples for LLM prompts
│   ├── bill_parser.py       # LLM-based field extraction
│   ├── download_models.py   # one-time model download script
│   ├── main.py              # command-line pipeline
│   ├── ocr_reader.py        # DocTR OCR wrapper
│   └── templates/
│       └── index.html       # single-page web UI
├── tests/                   # pytest unit and integration tests
├── samples/                 # test receipt images and PDFs (git-ignored)
└── pyproject.toml           # package metadata and dependencies
```

---

## Entry points

| Command | Description |
|---------|-------------|
| `bill-extractor` | Start the web app on port 8080 |
| `bill-extractor-download` | Download all models for offline use |
| `bill-extractor-cli <image>…` | Run the extraction pipeline from the terminal |

---

## Dependencies

| Library | Purpose |
|---------|---------|
| `flask` | Web framework |
| `python-doctr[torch]` | OCR — text detection and recognition |
| `pypdfium2` | PDF page rendering for DocTR |
| `torch` | Deep learning runtime (MPS / CUDA / CPU) |
| `transformers` | Qwen2.5-1.5B-Instruct model loading and inference |
| `accelerate` | Device placement for transformer models |
| `Pillow` | Image loading |
| `opencv-python-headless` | Image pre-processing for DocTR |

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
- ~4 GB disk space for model weights
- Apple Silicon (MPS), NVIDIA GPU (CUDA), or CPU — auto-detected at runtime

---

## Quick start

### 1. Install uv (one-time)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
```

### 2. Create an environment and install

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .
```

> **Linux without an NVIDIA GPU** — the default PyPI `torch` wheel on Linux includes CUDA libraries
> (~1.5 GB). Install CPU-only wheels first to avoid this:
> ```bash
> uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
> uv pip install -e .
> ```
>
> **NVIDIA GPU (CUDA)** — install CUDA-enabled wheels instead:
> ```bash
> uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
> uv pip install -e .
> ```
> `torch` and `torchvision` must always come from the same index.

### 3. Initialise (one-time)

Downloads both models and creates the data directory (~3.5 GB):

```bash
bill-extractor init
```

Safe to re-run — already-cached files are skipped automatically.

### 4. Start the web app

```bash
bill-extractor serve
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

Extract a single file without the web UI:

```bash
bill-extractor extract samples/food_01.jpeg
```

When stdout is a terminal, results are shown as a formatted table. When piped, raw JSON is emitted so the command stays scriptable:

```bash
bill-extractor extract receipt.jpg | jq .total_amount
```

Save the result to history and `files/` (same as saving from the web UI):

```bash
bill-extractor extract receipt.jpg --save
```

Send to a specific remote server:

```bash
bill-extractor extract receipt.jpg --server http://gpu-box:8080
```

---

## Project structure

```
bill_extractor/
├── bill_extractor/          # Python package
│   ├── __init__.py          # package version
│   ├── app.py               # FastAPI application + CLI entry point
│   ├── bill_examples.py     # few-shot OCR examples for LLM prompts
│   ├── bill_parser.py       # LLM-based field extraction
│   ├── config.py            # Config dataclass + loader
│   ├── download_models.py   # one-time model download script
│   ├── history.py           # server-side history store
│   ├── ocr_reader.py        # DocTR OCR wrapper
│   └── templates/
│       └── index.html       # Vue 3 single-page web UI
├── docs/                    # MkDocs documentation source
├── tests/                   # pytest unit and integration tests
├── samples/                 # test receipt images and PDFs (git-ignored)
└── pyproject.toml           # package metadata and dependencies
```

---

## Entry points

| Command | Description |
|---------|-------------|
| `bill-extractor init` | Download models and initialise data directory (run once after install) |
| `bill-extractor serve` | Start the web app on port 8080 |
| `bill-extractor serve --headless` | OCR endpoint only (no UI, for GPU servers) |
| `bill-extractor extract <file>` | Extract a single file from the terminal |

---

## Dependencies

| Library | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | Web framework and server |
| `python-doctr[torch]` | OCR — text detection and recognition |
| `pypdfium2` | PDF page rendering for DocTR |
| `torch` | Deep learning runtime (MPS / CUDA / CPU) |
| `transformers` | Qwen2.5-1.5B-Instruct model loading and inference |
| `accelerate` | Device placement for transformer models |
| `Pillow` | Image loading |
| `opencv-python-headless` | Image pre-processing for DocTR |

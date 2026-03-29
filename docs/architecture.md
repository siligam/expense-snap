# Bill Extractor — Architecture & State Snapshot

> Compact reference for onboarding and future development planning.
> Last updated: 2026-03-29 · Version 0.5.0 · 33 commits

---

## What it does

Processes receipt photos (JPEG/PNG/WEBP) and PDFs, extracts structured expense
data, and persists results through a web UI. Runs fully offline after a one-time
model download, or can offload OCR/LLM inference to a remote server on the network.

**Extracted fields by category:**

| Category | Fields |
|----------|--------|
| Food     | date, time, total_amount, currency, meal_type |
| Travel   | date, time, amount |
| Hotel    | date (= check_in), name, check_in, check_out, stay_duration_days, amount, currency |

---

## Pipeline

```
File (image or PDF)
  │
  ▼
DocTR OCR                          ← neural network (db_resnet50 + crnn_vgg16_bn)
  │  raw words with geometry
  ▼
Word clustering (y-axis proximity) ← groups words into reading-order lines
  │  list[str] lines
  ▼
OCR error correction               ← regex fixes for ₹ misread as "7" or "1 "
  │
  ▼
Noise filter                       ← strips GSTIN, phone, email, URL, boilerplate
  │  cleaned list[str]
  ▼
Router LLM (Qwen2.5-1.5B)         ← classifies: food / travel / hotel
  │  category
  ▼
Extractor LLM (Qwen2.5-1.5B)      ← extracts fields for that category
  │  raw JSON
  ▼
Post-processing helpers            ← normalize dates, times, amounts
  │
  ▼
Structured JSON result + provenance metadata
```

OCR can run locally or be forwarded to a configured remote server. The LLM
always runs locally (remote LLM is not supported).

---

## Deployment modes

| Mode | Command | Routes served |
|------|---------|---------------|
| **Full stack** (default) | `bill-extractor serve` | All routes: `/extract`, `/history`, `/files`, `/config`, `/storage`, UI |
| **Headless** (GPU server) | `bill-extractor serve --headless` | `/extract` only — no UI, no history, no file storage |
| **CLI** | `bill-extractor extract <file>` | No server — runs extraction and prints result |

In full-stack mode, the browser opens automatically on startup. In headless mode
the server is intended to be targeted by another full-stack instance as a remote
OCR server.

---

## Repository layout

```
bill_extractor/
├── __init__.py          # package version (0.5.0)
├── app.py               # FastAPI application + CLI entry point  (~760 lines)
├── bill_examples.py     # static few-shot examples for LLM prompts  (124 lines)
├── bill_parser.py       # prompt builders + BillingInformationExtractor  (~582 lines)
├── config.py            # Config dataclass + JSON/YAML loader  (~100 lines)
├── download_models.py   # one-time model download (run via `bill-extractor init`)
├── history.py           # server-side history store (JSON file + files/ dir)
├── ocr_reader.py        # DocTR wrapper + post-processing  (~173 lines)
└── templates/
    └── index.html       # Vue 3 single-page web UI  (~1614 lines)

tests/
├── conftest.py              # session-scoped OCR fixtures
├── test_api.py              # 29 API tests — FastAPI routes with mocked ML
├── test_bill_parser.py      # 52 unit tests — pure helpers
├── test_config.py           # 8 unit tests — config loading
├── test_frontend.py         # 2 Playwright browser tests — PDF preview + filename dedup
├── test_history.py          # 12 unit tests — history store
├── test_ocr_integration.py  # 12 integration tests — real sample images (GPU/CPU)
└── test_ocr_reader.py       # 40 unit tests — OCR corrections + noise filter

docs/                    # MkDocs source (deployed to GitHub Pages)
.github/
├── workflows/
│   ├── ci.yml           # pytest on push/PR (skips frontend + OCR integration)
│   └── docs.yml         # mkdocs gh-deploy on push to main
└── ISSUE_TEMPLATE/      # bug report + feature request templates
```

**Test count:** 155 total · CI runs 141 (skips frontend and OCR integration tests).

---

## Key modules in detail

### `ocr_reader.py`

- `process(file_path)` is the single entry point; detects `.pdf` extension and
  dispatches to `DocumentFile.from_pdf()` or `from_images()`.
- `_fix_rupee_symbol_misread()` has two patterns:
  - Pattern 1: `(?<![.\d])7(\d{3,}...)` — `7` misread, requires 3+ digits to
    avoid corrupting small prices like `74.00`.
  - Pattern 2: `(:\s*)1\s+(\d{2,}...)` — `₹` misread as `1 ` after a label
    colon (e.g. `Total Payable: 1 226.00` → `₹226.00`).
- `_is_noise()` strips ~14 regex patterns: GSTIN, PAN, CIN, phone, email, URL,
  thank-you phrases.
- DocTR model is loaded lazily on first call to `process()`, not at import time.

### `bill_parser.py`

- `BillingInformationExtractor` loads Qwen2.5-1.5B-Instruct once; auto-selects
  MPS / CUDA / CPU with float16/float32 accordingly.
- Two-stage inference: `route_category()` (128 max tokens) then
  `extract_{food|travel|hotel}()` (512 max tokens). Both use `do_sample=False`.
- Post-processing helpers are pure functions (tested independently):
  - `_normalize_date()` — handles DD/MM/YYYY, DD/MM/YY, "27 Feb 2026", "27 Feb"
  - `_normalize_time()` — converts 12h AM/PM to 24h
  - `_extract_number_string()` — extracts first numeric value, strips commas
  - `_infer_meal_type_from_time()` — time-window based: breakfast 05:00–10:59,
    lunch 11:00–15:59, dinner 18:00–23:59; `unknown` outside these windows
- 1 static few-shot example per category in `bill_examples.py`.

### `app.py`

- Built on **FastAPI** with uvicorn; replaced Flask in 0.4.x.
- REST API endpoints:
  - `POST /extract` — upload file, run OCR + LLM, return structured JSON + provenance
  - `GET /history` — all records as JSON array
  - `POST /history` — upsert a record (with optional file upload)
  - `DELETE /history/{hash}` — delete a record and its stored file
  - `GET /files/{filename}` — serve a stored original file
  - `GET /storage` — disk usage stats
  - `GET /config` — current config (data dir, OCR servers)
  - `PATCH /config` — update data dir or OCR server list at runtime
  - `GET /health` — liveness check
  - `GET /` — serves `index.html`
- **Duplicate detection**: MD5 hash of raw file bytes before any processing.
- **Files** saved to configured `files_dir` (default `~/.bill_extractor/files/`)
  with generated names: `YYYY-MM-DD_category_mealtype.ext`, counter-suffixed
  (`_2`, `_3`, …) when fields collide.
- **Provenance**: every result includes `submitted_at`, `completed_at`,
  `ocr_server`, `doctr_version`, `model_name`.
- **Lazy model loading**: models load on the first `/extract` request if not
  already loaded; a semaphore serialises concurrent inference.
- **Structured logging**: loguru with colored console output and a rotating file
  log at `{data_dir}/bill_extractor.log` (5 MB, 3 files).

### Remote OCR server support

- Full-stack instances can delegate `/extract` calls to one or more remote
  headless servers configured via `config.json` or the `/config` PATCH endpoint.
- Round-robin across enabled remote servers; falls back to local processing if
  all remotes are unreachable.
- Config is persisted atomically to `{data_dir}/config.json`.

### `history.py`

- Flat JSON file store (`history.json`) — one record per file processed.
- Each record: `hash`, `filename`, `filename_generated`, `result`, `ocr_text`,
  `provenance`, `correction`, `action`, `timestamp`, `original_file`.
- `action` is `"good"` / `"bad"` / `""` (user feedback).
- `correction` is free-text override saved by the user.

### `config.py`

- Supports JSON and YAML config files (YAML requires `pyyaml` optional dep).
- Config discovered at `~/.bill_extractor/config.json` by default.
- Backward-compatible: old `ocr_url` string field migrated to `ocr_servers` list.

### `index.html` (Vue 3 SPA)

- Vue 3 Composition API, loaded via CDN — no build step.
- Drag-and-drop zone accepts JPEG, PNG, WEBP, and PDF.
- **Upload tab**: live results per file with thumbnail, extracted fields, OCR
  text, Good/Bad marking, correction textarea, reprocess button.
- **History tab**: all records — sortable columns (date, amount, category),
  date-range and amount filters, column drag-to-reorder, pagination.
- PDF thumbnails in history rendered via pdf.js hover preview (first page);
  cached per hash to avoid re-fetching.
- All history lives server-side (JSON + files/). No IndexedDB or FSA usage.

---

## Runtime characteristics

| Metric | Value |
|--------|-------|
| Model load time | ~4–5 s (MPS, float16) |
| OCR per image | ~1.5–2 s |
| LLM extraction | ~5–8 s (router + extractor) |
| Total per receipt | ~7–10 s |
| Model footprint | ~3.5 GB disk, ~2 GB RAM (float16) |
| Supported devices | Apple MPS, NVIDIA CUDA, CPU |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | ≥0.111.0 | Web framework |
| `uvicorn[standard]` | ≥0.29.0 | ASGI server |
| `python-multipart` | ≥0.0.9 | File upload support for FastAPI |
| `httpx` | ≥0.27.0 | Async HTTP client (remote OCR proxy) |
| `loguru` | ≥0.7.0 | Structured logging |
| `rich` | ≥13.0 | CLI output formatting |
| `python-doctr` | ≥0.9.0 | OCR — detection + recognition |
| `pypdfium2` | ≥4.0 | PDF page rendering for DocTR |
| `torch` | ≥2.1.0 | Deep learning runtime |
| `transformers` | ≥4.40.0 | Qwen2.5-1.5B loading + inference |
| `accelerate` | ≥0.27.0 | Device placement |
| `Pillow` | ≥10.0 | Image loading |
| `opencv-python-headless` | ≥4.8.0 | Image pre-processing |
| `pytest` | ≥8.0 | Test runner (dev) |
| `pytest-playwright` | ≥0.5 | Browser tests (dev) |
| `pyyaml` | ≥6.0 | YAML config support (optional) |

---

## Strengths

| Area | Detail |
|------|--------|
| **Offline-first** | All inference runs locally after `bill-extractor init`; no API calls at runtime |
| **Remote offload** | Can delegate OCR/LLM to a headless server on the local network |
| **Two-stage LLM** | Routing step keeps extractor prompts focused; extensible to new categories |
| **PDF support** | Native via DocTR + pypdfium2; multi-page PDFs produce combined OCR output |
| **Duplicate detection** | MD5 on raw bytes; re-upload is instant with zero re-inference |
| **Provenance tracking** | Every result records which server processed it and model versions |
| **Manual correction** | Bad results can be corrected in-place and persisted |
| **Test coverage** | 155 tests including regression tests for every bug fixed to date |
| **Pure helper functions** | Date/time/amount normalisation are pure functions, easy to test and maintain |

---

## Weaknesses & fragile areas

### 1. Regex-based OCR correction — most fragile part

Three iterations in one week show this is the most error-prone area. Each receipt
printer renders `₹` slightly differently; OCR misreads it as `7`, `1`, `?`, or
omits it entirely. Pattern matching cannot reliably distinguish a misread symbol
from a legitimate number starting with `7` (e.g., `74.00` is a valid price).

### 2. Single static few-shot example per category

The LLM has exactly 1 example to learn from per category. When a receipt deviates
from that template (different label names: `NET AMT` vs `Grand Total` vs
`Total Payable`), extraction degrades. The prompt rule list is growing reactively.

### 3. Amount extraction has no verification step

The LLM output for `total_amount` is taken at face value. There is no check that
the returned value actually appears in the OCR text. Hallucinated or misread
values pass through silently.

### 4. Word clustering is layout-unaware

`cluster_lines()` groups words purely by y-axis proximity. Multi-column receipt
layouts (item | qty | rate | total) get merged into a single noisy line, which
confuses the LLM.

### 5. Small model with no fallback

Qwen2.5-1.5B is pushed to its limits on complex hotel invoices. There is no
retry, no confidence threshold, and no fallback to a larger model or rule-based
extraction when the LLM returns null fields.

### 6. `meal_type` is time-based only

Content-based signals in the receipt text (e.g., "breakfast combo", "lunch
thali") are ignored. Times outside the defined windows return `unknown`.

---

## Ideas to reduce fragility with ML

### Near-term (without changing the core architecture)

**A. Post-extraction amount validation**
After the LLM returns `total_amount`, scan the cleaned OCR lines for that value.
If not found verbatim (or within ±0.01), flag the result as low-confidence and
surface a warning in the UI.

**B. Dynamic few-shot examples**
Store confirmed Good Result extractions in a small local vector store. At
inference time, retrieve the 2–3 most similar receipts by OCR text similarity
and use them as few-shot examples instead of the static ones.

**C. Confidence field in LLM output**
Add `"confidence": "high|medium|low"` to the extraction schema. Auto-flag
low-confidence results for manual review.

### Medium-term (targeted ML additions)

**D. Lightweight amount-detector model**
Replace `_fix_rupee_symbol_misread` and the LLM's amount-extraction with a small
sequence-labelling model trained specifically on Indian receipt OCR text.
~500 labelled receipts would be enough to get high accuracy.

**E. Receipt layout analysis before clustering**
Use DocTR's bounding-box geometry to detect column structure before clustering.
Group words by x-band first, then y-proximity within each column.

### Longer-term

**F. Fine-tune Qwen on confirmed extractions**
Every Good Result or user correction is a supervised training pair. After ~200–300
confirmed examples, LoRA fine-tuning would likely outperform the current few-shot
prompting approach on your specific receipt types.

---

## Known issues / open gaps

- Phone numbers embedded mid-line (e.g., `"Ph: 8262818668"`) survive the noise
  filter because the phone regex only matches standalone lines.
- The `₹` symbol can also be misread as `?`, `*`, or `R` by DocTR on low-res
  images; no patterns handle these yet.
- Multi-page PDFs: all pages are concatenated into a single OCR pass; if the
  total appears on page 2, the LLM sees both pages' text which may confuse it.
- No file size validation on `/extract`.
- Remote LLM inference is not supported; only OCR can be offloaded.

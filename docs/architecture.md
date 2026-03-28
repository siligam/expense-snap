# Bill Extractor — Architecture & State Snapshot

> Compact reference for onboarding and future development planning.
> Last updated: 2026-03-25 · Version 0.4.0 · 12 commits

---

## What it does

Processes receipt photos (JPEG/PNG/WEBP) and PDFs, extracts structured expense
data, and persists results through a web UI. Runs fully offline after a one-time
model download.

**Extracted fields by category:**

| Category | Fields |
|----------|--------|
| Food     | date, time, total_amount, currency, meal_type |
| Travel   | date, time, amount |
| Hotel    | name, check_in, check_out, stay_duration_days, amount, currency |

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
Structured JSON result
```

---

## Repository layout

```
bill_extractor/
├── __init__.py          # version (0.4.0)
├── app.py               # Flask web server + REST API  (352 lines)
├── bill_examples.py     # static few-shot examples for LLM prompts  (124 lines)
├── bill_parser.py       # prompt builders + BillingInformationExtractor  (582 lines)
├── download_models.py   # one-time model download  (37 lines)
├── main.py              # CLI entry point  (50 lines)
├── ocr_reader.py        # DocTR wrapper + post-processing  (173 lines)
└── templates/
    └── index.html       # single-page web UI (vanilla JS)  (1597 lines)

tests/
├── conftest.py          # session-scoped OCR fixtures
├── test_bill_parser.py  # 47 unit tests — pure helpers
├── test_ocr_reader.py   # 29 unit tests — OCR corrections + noise
└── test_ocr_integration.py  # 39 integration tests — 12 sample images
```

**Test count:** 115 passing · no external mocking · uses real sample images.

---

## Key modules in detail

### `ocr_reader.py`

- Loads DocTR model **at module level** (unavoidable import cost).
- `process(file_path)` is the single entry point; detects `.pdf` extension and
  dispatches to `DocumentFile.from_pdf()` or `from_images()`.
- `_fix_rupee_symbol_misread()` has two patterns:
  - Pattern 1: `(?<![.\d])7(\d{3,}...)` — `7` misread, requires 3+ digits to
    avoid corrupting small prices like `74.00` or `76.00`.
  - Pattern 2: `(:\s*)1\s+(\d{2,}...)` — `₹` misread as `1 ` after a label
    colon (e.g. `Total Payable: 1 226.00` → `₹226.00`).
- `_is_noise()` strips ~14 regex patterns: GSTIN, PAN, CIN, phone, email, URL,
  thank-you phrases.

### `bill_parser.py`

- `BillingInformationExtractor` loads Qwen2.5-1.5B-Instruct once; auto-selects
  MPS / CUDA / CPU with float16/float32 accordingly.
- Two-stage inference: `route_category()` (128 max tokens) then
  `extract_{food|travel|hotel}()` (512 max tokens). Both use `do_sample=False`.
- Post-processing helpers are pure functions (tested independently):
  - `_normalize_date()` — handles DD/MM/YYYY, DD/MM/YY, "27 Feb 2026", "27 Feb"
  - `_normalize_time()` — converts 12h AM/PM to 24h
  - `_extract_number_string()` — extracts first numeric value, strips commas
  - `_infer_meal_type_from_time()` — time-window based (not content-based)
- 1 static few-shot example per category in `bill_examples.py` (already
  de-identified).

### `app.py`

- REST API: `POST /api/process`, `GET/DELETE /api/cache`, `GET/DELETE
  /api/history`, `PATCH /api/item/<hash>`, `POST /api/reset`, `POST
  /api/export`.
- Duplicate detection: MD5 hash of raw file bytes before any processing.
- Files saved to `uploads/` with human-readable names:
  `YYYY-MM-DD_category_mealtype.ext` (counter-suffixed on collision).
- Export produces a zip with all selected files + `summary.csv`.
- History migrates automatically from old session-based format to flat list.

### `index.html`

- Vanilla JS, no framework. ~1600 lines.
- Drag-and-drop zone accepts `image/*` and `.pdf`.
- PDF thumbnails rendered as a clickable `<i class="fa-file-pdf">` icon (links
  to raw file) rather than a broken `<img>`.
- Two tabs: Current Session (cache) and History (all past sessions).
- Sort, date-range filter, amount filter on History tab.
- Mark Good/Bad, manual correction textarea, export selected items.

---

## Commit history

```
61d6402  Fix rupee-symbol fixer false positives and add ₹→1 pattern
fd6e104  Add tests, fix PII in examples, sync project metadata
237c6c0  Fix rupee-symbol fixer corrupting amounts containing 7
03abd0a  Add PDF support for bill processing
dc6b85c  Anonymize PII in few-shot examples
5469ec7  Fix OCR misinterpretation of rupee symbol as '7'
f16a2b0  Fix pyproject.toml build backend
1d75d0d  Add summary table, auto-rename, and export features
88fcbe9  Add OCR noise filtering and fast tokenizer
a48def1  Refactor into proper Python package with full web UI and CLI
a0fb4ee  Add image lightbox and copy-to-clipboard
4508352  Initial commit
```

---

## Strengths

| Area | Detail |
|------|--------|
| **Offline-first** | All inference runs locally after `bill-extractor-download`; no API calls at runtime |
| **Two-stage LLM** | Routing step keeps extractor prompts focused; extensible to new categories |
| **PDF support** | Native via DocTR + pypdfium2; multi-page PDFs produce combined OCR output |
| **Duplicate detection** | MD5 on raw bytes; re-upload is instant with zero re-inference |
| **Data persistence** | Cache + history survive restarts; automatic format migration |
| **Manual correction** | Bad results can be corrected in-place; corrections are exported in CSV |
| **Test coverage** | 115 tests including regression tests for every bug fixed to date |
| **Pure helper functions** | Date/time/amount normalisation are pure functions, easy to test and maintain |

---

## Weaknesses & fragile areas

### 1. Regex-based OCR correction — most fragile part

Three iterations in one week (commits `5469ec7`, `237c6c0`, `61d6402`) show
this is the most error-prone area. Each receipt printer renders `₹` slightly
differently; OCR misreads it as `7`, `1`, `?`, or omits it entirely. Pattern
matching cannot reliably distinguish a misread symbol from a legitimate number
starting with `7` (e.g., `74.00` is a valid price). New receipt formats will
keep breaking this.

### 2. Single static few-shot example per category

The LLM has exactly 1 example to learn from per category. When a receipt deviates
from that template (different label names: `NET AMT` vs `Grand Total` vs
`Total Payable`), extraction degrades. The prompt rule list is growing as an
ad-hoc fix (`Total AMT`, `Gross AMT` added reactively).

### 3. Amount extraction has no verification step

The LLM output for `total_amount` is taken at face value. There is no check
that the returned value actually appears in the OCR text. If the model
hallucinates or misreads (e.g., `1226` instead of `226`), it passes through
silently.

### 4. Word clustering is layout-unaware

`cluster_lines()` groups words purely by y-axis proximity. Multi-column receipt
layouts (item | qty | rate | total) get merged into a single noisy line, which
confuses the LLM. Example: `"21069099  Dal Muth 150g  1.000 No  57.00"` on one
line makes the LLM see `57.00` as an ambiguous amount.

### 5. Small model with no fallback

Qwen2.5-1.5B is pushed to its limits on complex hotel invoices and receipts with
many line items. There is no retry, no confidence threshold, and no fallback to
a larger model or rule-based extraction when the LLM returns null fields.

### 6. `meal_type` is time-based only

A 2pm meal is classified as `unknown` (falls between lunch 15:59 and dinner
18:00 cutoff). Content-based signals (e.g., "breakfast combo", "lunch thali")
in the receipt text are ignored.

### 7. Module-level DocTR model loading

`model = ocr_predictor(pretrained=True)` runs at module import time in
`ocr_reader.py`. Every test that imports from this module pays the full model
load cost, making the test suite slower than necessary.

---

## Ideas to reduce fragility with ML

### Near-term (without changing the core architecture)

**A. Post-extraction amount validation**
After the LLM returns `total_amount`, scan the cleaned OCR lines for that
value using regex. If the value is not found verbatim (or within ±0.01 rounding),
flag the result as low-confidence and surface a warning in the UI. This catches
the `1226` vs `226` class of errors without any model changes.

**B. Dynamic few-shot examples**
Store confirmed Good Result extractions (user-marked) in a small local vector
store (e.g., sqlite-vec or FAISS). At inference time, retrieve the 2-3 most
similar receipts (by OCR text similarity) and use them as few-shot examples
instead of the static ones. This would make the LLM progressively better as
more receipts are processed.

**C. Confidence field in LLM output**
Add `"confidence": "high|medium|low"` to the extraction schema. Instruct the
model to set it low when amounts are ambiguous. Auto-flag low-confidence results
for manual review without changing anything else.

### Medium-term (targeted ML additions)

**D. Lightweight amount-detector model**
Replace `_fix_rupee_symbol_misread` and the LLM's amount-extraction step with a
small sequence-labelling model (e.g., a fine-tuned DistilBERT or even a
rule-based CRF) trained specifically to tag currency amounts in Indian receipt
OCR text. This would be trained on real examples labelled with the correct
total. ~500 labelled receipts would be enough to get high accuracy.

**E. Receipt layout analysis before clustering**
Use DocTR's bounding-box geometry (already available in `extract_words()`) to
detect column structure before clustering. Group words by x-band first, then
y-proximity within each column. This would separate "item name" column from
"price" column, drastically reducing noise in the text fed to the LLM.

### Longer-term

**F. Fine-tune Qwen on confirmed extractions**
Every time a user marks a result as Good or corrects it, that becomes a
supervised training pair. After accumulating ~200-300 confirmed examples, LoRA
fine-tuning on the 1.5B model for the extraction task would likely outperform
the current few-shot prompting approach on your specific receipt types.

---

## Runtime characteristics

| Metric | Value |
|--------|-------|
| Model load time | ~4-5s (MPS, float16) |
| OCR per image | ~1.5-2s |
| LLM extraction | ~5-8s (router + extractor) |
| Total per receipt | ~7-10s |
| Model footprint | ~3.5 GB disk, ~2 GB RAM |
| Supported devices | Apple MPS, NVIDIA CUDA, CPU |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `python-doctr[torch]` | ≥0.9.0 | OCR — detection + recognition |
| `pypdfium2` | ≥4.0 | PDF page rendering for DocTR |
| `torch` | ≥2.1.0 | Deep learning runtime |
| `transformers` | ≥4.40.0 | Qwen2.5-1.5B loading + inference |
| `accelerate` | ≥0.27.0 | Device placement |
| `flask` | ≥3.0 | Web server |
| `Pillow` | ≥10.0 | Image loading |
| `opencv-python-headless` | ≥4.8.0 | Image pre-processing |
| `pytest` | ≥8.0 | Test runner (dev) |

---

## Known issues / open gaps

- Phone numbers embedded mid-line (e.g., `"Ph: 8262818668"`) survive the noise
  filter because the phone regex only matches standalone lines.
- The `₹` symbol can also be misread as `?`, `*`, or `R` by DocTR on low-res
  images; no patterns handle these yet.
- Multi-page PDFs: all pages are concatenated into a single OCR pass; if the
  total appears on page 2, the LLM sees both pages' text which may confuse it.
- `bill-extractor-cli` accepts images but no PDFs (the web UI handles PDFs,
  but `main.py` has no special handling needed since `ocr_reader.process()`
  already auto-detects `.pdf`).
- No rate-limiting or file size validation on `/api/process`.

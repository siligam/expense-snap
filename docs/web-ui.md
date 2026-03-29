# Web UI

The web interface is a single-page Vue 3 app served by the Bill Extractor server at `http://localhost:8080`.

---

## Upload tab

### Dropping files

Drag and drop receipt images or PDFs anywhere on the page, or click **Choose files** to browse. Multiple files can be dropped at once — each is processed concurrently and cards appear as results come in.

Supported formats: JPEG, PNG, WEBP, PDF.

### Session cards

Each uploaded file gets a card:

**Processing** — spinner while OCR and LLM inference run.

**New result** — extraction succeeded. The card shows:
- Generated filename (e.g. `27-02-2026_food_dinner.jpg`) with a green **NEW** badge
- Original filename in italic below if it differs (`from receipt_scan.jpg`)
- Category pill, extracted fields (date, time, amount, meal type, hotel name)
- **Good** / **Bad** buttons to mark quality
- Optional correction note — free text saved alongside the result
- **Download renamed copy** — download the file with the generated name
- **Save correction** — persist the correction note to history

**Duplicate** — the same file (by MD5 hash) was already processed. The card shows:
- When it was previously processed
- What was found last time (category, date, amount, meal type) in a summary block
- **View in history** — jump to the History tab
- **Process anyway** — force a fresh extraction, replacing the old record

**Error** — extraction failed. The error message is shown inline.

---

## History tab

A sortable, filterable table of all past extractions.

### Columns

Toggle columns on/off using the chip buttons above the table. Column order can be changed by dragging headers. Preferences are saved in `localStorage`.

| Column | Notes |
|--------|-------|
| Thumbnail | Loaded from the saved original file. PDFs show a PDF icon. Hover to enlarge 2×; click to open full-size lightbox. |
| Date | Extraction date from the receipt |
| Category | food / travel / hotel |
| Amount | Total with currency |
| Meal type | breakfast / lunch / dinner (food only) |
| Time | Receipt time |
| Filename | Generated name (e.g. `27-02-2026_food_dinner.jpg`) |
| Status | good / bad / none |
| OCR text | Raw lines from DocTR (hidden by default; never exported to CSV) |

### Date range filter

A month-level slider filters records by receipt date. Grab either handle to move an endpoint; grab the fill bar to drag the whole window.

Preset buttons: **1M**, **3M**, **6M**, **YTD**, **All**. The active preset is remembered across sessions.

### Other filters

Click the **Filters** button to open the filter panel:
- Category (food / travel / hotel / all)
- Amount comparison (≥, ≤, =)

The active filter count is shown on the button badge.

### Bulk actions

Select rows with the checkboxes (or **Select page**) then:
- **Delete selected** — removes records and their original files from the server

### Export CSV

Exports all **visible** records (respecting date range and filters) as CSV. OCR text is never included even if that column is visible.

---

## Settings tab

### Cache folder

Shows the current data directory as a folder tree:

```
~/.bill_extractor/
├─ history.json    history database
├─ files/          renamed original receipts
└─ bill_extractor.log  server log
```

Click **Change** to enter a new path. The change is applied immediately — no restart needed.

### OCR servers

A list of servers used for extraction. Each entry has a URL and an enabled toggle.

- **local** — the locally running models. Always present; cannot be removed.
- **http://...** — a remote `bill-extractor serve --headless` instance.

Click **+ Add server** to add a remote URL. Enabled servers are tried in order with round-robin load balancing; if all remotes fail, the local models are used automatically.

### OCR health

A live status indicator shows whether the local OCR engine is ready (`Model loaded`) or still loading.

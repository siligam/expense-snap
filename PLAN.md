# Bill Extractor — Restructuring Plan

> Status: active · last updated 2026-03-27
> Branch: `dev`

---

## Context

Two distinct user profiles drive the design:

- **Developer / power user** — wants a clean `POST /extract` → JSON endpoint,
  nothing more. Calls the service programmatically.
- **End users (Windows, non-technical)** — perceive the app entirely through
  the frontend. Think in terms of buttons and screens. Their real workflow is:
  take receipt photo → extract data → manually enter into Oracle expense report.
  The app accelerates step 1 of that manual process.

**Key constraints:**
- The server does not need to store anything. No database, no uploaded files,
  no history.
- All state (history, deduplication, export data) lives in the user's browser
  via `localStorage`.
- Each user's browser is their own isolated record — no sharing, no auth needed.
- The Oracle expense report is the real destination, but no API details are
  known yet. Oracle integration is deferred.

---

## Target architecture

```
Server (FastAPI)
│
│  POST /extract
│  ← multipart file (image or PDF)
│  → { category, date, time, total_amount, currency, meal_type, ... }
│
│  Single endpoint. Stateless. No storage.

Browser (single HTML file or static site)
│
│  - File picker / drag-drop (image + PDF)
│  - Calls POST /extract → receives JSON
│  - Stores result in localStorage (hash → record)
│  - Flags duplicates before sending (client-side MD5)
│  - History view from localStorage
│  - Manual correction, mark good/bad
│  - Client-side CSV export
│  - [ Phase 3 ] Oracle ergonomics
```

---

## What changes vs. today

| Concern | Current | Target |
|---------|---------|--------|
| Web framework | Flask | FastAPI |
| Server storage | `cache.json`, `history.json`, `uploads/` | None |
| History | Server-side JSON files | `localStorage` in browser |
| Duplicate detection | MD5 in server cache | MD5 in browser before upload |
| Export | Server builds zip + CSV | Browser builds CSV from `localStorage` |
| File retention | Server keeps uploaded images | Nothing retained server-side |
| Multi-user isolation | One shared global history | Each browser is independent |
| Auth | None | None needed |

---

## Development rules

- Run `python -m pytest` before every commit — commit only on green
- Commit at natural checkpoints (end of a phase, before a significant
  refactor, before any change that would be hard to reverse)
- Keep `main` stable — it has a live user (Pranitha). All work on `dev`
  or feature branches off `dev`. Merge to `main` only when a phase is
  complete and tested.
- Do not start the next phase until the current phase checklist is fully
  checked off

---

## Phases

### Phase 1 — Clean server (FastAPI)

**Goal:** strip the server down to a single stateless extraction endpoint.

**Changes:**
- Replace Flask with FastAPI
- Single endpoint: `POST /extract`
  - Accepts: multipart file (image or PDF)
  - Returns: structured JSON (same schema as today)
  - No file saved to disk, no cache written, no history touched
- Move model loading to FastAPI lifespan startup event (not module-level)
- Add a simple request queue in front of inference to serialise GPU access
  (PyTorch inference is not thread-safe; even for a single user this prevents
  issues if the browser sends concurrent requests)
- Keep `ocr_reader.py` and `bill_parser.py` untouched — they are already
  stateless and become the service's internal implementation
- Remove from `app.py`: all persistence helpers, history routes, cache routes,
  reset, export, file-serving
- Add CORS middleware — allow configurable origins

**Deliverable:** a FastAPI app with one endpoint that any HTTP client can call.
Existing CLI (`bill-extractor-cli`) continues to work unchanged.

**Checklist:**
- [x] FastAPI app created with lifespan model loading
- [x] `POST /extract` accepts image and PDF, returns correct JSON schema
- [x] Request queue in place — concurrent requests serialised
- [x] CORS configured
- [x] All existing tests pass (`python -m pytest`) — 128 passed
- [x] New tests for the `/extract` endpoint (upload image → check response schema)
- [x] New tests for the `/extract` endpoint (upload PDF → check response schema)
- [x] CLI (`bill-extractor-cli`) still works unchanged
- [x] `flask` removed from dependencies, `fastapi` + `uvicorn` added to `pyproject.toml`
- [x] Commit: *"Phase 1 complete — FastAPI stateless extraction service"*

---

### Phase 2 — Client-side frontend (Vue.js + PrimeVue)

**Goal:** feature-equivalent frontend to today, rebuilt in Vue + PrimeVue,
with all state in a user-chosen file via the File System Access API.

**Changes:**
- Vue.js + PrimeVue (CDN, no build step — ships as a single `.html` file)
- File System Access API for history file (read/write a user-chosen JSON file)
- History record schema:
  ```json
  {
    "hash": "...",
    "filename": "...",
    "filename_generated": "...",
    "thumbnail": "<base64 ~10KB resized>",
    "ocr_text": ["..."],
    "result": { ... },
    "correction": "",
    "action": "",
    "timestamp": "..."
  }
  ```
- Duplicate detection: MD5 computed in browser before upload; checked against
  full history file — skip server call if already processed
- History view: PrimeVue DataTable with toggleable columns (date, thumbnail,
  category, amount, meal type, time, filename, status, raw OCR text)
- Date range slider: month-level, presets 1M / 3M / 6M / YTD / All
- Export: client-side CSV respecting current slider range
- Manual correction and good/bad marking write back to history file
- Settings panel: server URL, default date range, export format, file naming,
  column visibility
- Optional secondary file: load read-only overlay for viewing old history
- CORS-friendly: works from `file://`, `localhost`, and company intranet URL

**Checklist:**
- [x] Vue + PrimeVue scaffolded, single `.html` file loads from CDN
- [x] Settings panel — server URL saved to `localStorage`
- [x] File System Access API — first-time setup, reopen on launch
- [x] `POST /extract` called from browser, result displayed
- [x] Thumbnail generated client-side (~10KB) and stored in history file
- [x] Raw OCR text stored in every record
- [x] Duplicate detection working (MD5 in browser)
- [x] History table with toggleable columns
- [x] Date range slider with month snapping and presets
- [x] Export CSV respects current date range
- [x] Manual correction and good/bad marking persisted to file
- [ ] Optional secondary file load (read-only overlay)
- [x] All existing backend tests still pass (`python -m pytest`) — 105 passed
- [ ] Manual smoke test: upload image → result shown → appears in history → duplicate blocked
- [ ] Manual smoke test: upload PDF → same flow
- [ ] Manual smoke test: close and reopen browser → history intact
- [ ] Manual smoke test: open in second browser → independent history
- [ ] Commit: *"Phase 2 complete — Vue frontend with client-side history"*

---

### Phase 2.5 — Server-side history + unified process model

**Goal:** eliminate browser-tied storage. History lives on the user's local disk,
managed by the app server. Any browser works identically. CLI and web UI share
the same history file automatically.

**Why this supersedes the Phase 2 storage approach:**
- IndexedDB and FSA are browser-specific — switching browsers loses all history
- Export/import is an extra burden users should not need for routine use
- Brave blocks `showDirectoryPicker`; `navigator.storage.estimate()` unreliable
- A locally-running server already has full disk access — use it directly

---

#### Architecture

One FastAPI process, two modes:

```
bill-extractor serve               (full local stack)
├── POST /extract                  OCR + inference  (models loaded at startup)
├── GET  /history                  returns all records as JSON
├── POST /history                  append or update a record
├── DELETE /history/{hash}         delete a record
├── GET  /files/{hash}             serve original file from disk
└── GET  /  (+ static)             serve the web UI

bill-extractor serve --headless    (remote / GPU server)
└── POST /extract                  OCR + inference only — no UI, no history
```

The browser always talks to the local app server on `localhost`. The local server
either handles `/extract` with its own models, or proxies the request to a
configured remote OCR server. The browser never needs a CORS exemption and
never knows whether processing is local or remote.

---

#### Config file

Auto-created on first run at `~/.bill_extractor/config.yaml`
(JSON also accepted — detected by extension).

```yaml
history_file: ~/.bill_extractor/history.json
files_dir:    ~/.bill_extractor/files/
ocr_url:      null          # null = use local models; set to remote URL to proxy
port:         8080
```

All paths expand `~`. `ocr_url` can also be set via `--ocr-url` flag on `serve`
or overridden per-call with `--server` on `extract`.

---

#### OCR resolution order

1. `ocr_url` configured and reachable → proxy request to remote server
2. Remote unreachable → fall back to local models
   - If models already loaded (no remote was configured at startup): immediate
   - If models not yet loaded (remote was configured): lazy-load on first fallback
     request; caller receives a 503 with `Retry-After: 15` while loading
3. Neither available → 503 with clear error message

**Model loading policy:**
- `serve` with no `ocr_url` → load models at startup (slow start, ~10s, always ready)
- `serve` with `ocr_url` set → skip model loading at startup (fast start, ~1s);
  load lazily only if remote fails
- `serve --headless` → always load models at startup

---

#### CLI interface

```
bill-extractor serve [--headless] [--port N] [--ocr-url URL]
    Start the server. Without --headless: opens browser automatically.
    --headless: OCR endpoint only, no UI or history routes.
    --ocr-url: override ocr_url from config for this session.

bill-extractor extract FILE [--server URL]
    Extract a single file. No local server required.
    --server: send directly to this URL.
    Fallback: if --server unreachable, tries local server on default port.
    Neither available: exits with error.

bill-extractor stop
    Graceful shutdown of local server (or Ctrl+C on serve).
```

---

#### Privacy contract (important for --headless remote deployments)

The server is stateless with respect to extracted content:
- Receives file bytes → runs OCR + inference → returns JSON → discards everything
- No file written to disk, no result cached, no history touched
- This behaviour is unchanged from Phase 1 and is preserved in `--headless` mode

**What the remote server sees** (from standard uvicorn access log):
- HTTP method, endpoint path (`POST /extract`), status code, response time
- Filename from the multipart `Content-Disposition` header
- Filetype inferred from extension or MIME type
- Timestamp of each request

**What the remote server does NOT see:**
- File contents, raw OCR text, extracted amounts, dates, vendor names, or any PII
- History records — these are written only by the local app server, never sent remotely

**Statistics derivable from logs (acceptable):**
- Requests per day / busy hours
- File type distribution (image vs PDF)
- Error rate and latency

---

#### Web UI changes

- Remove all IndexedDB / FSA / File System Access code (significant simplification)
- Remove browser-side storage estimate — server can report disk usage directly
- History reads/writes → `GET /history`, `POST /history`, `DELETE /history/{hash}`
- Original file downloads → `GET /files/{hash}` (replaces IDB `files` store)
- Settings panel: OCR server status indicator, external URL input, Start/Stop button
- No setup wizard on first launch — server handles file creation

**History record schema** (unchanged, now stored server-side as JSON):
```json
{
  "hash": "...",
  "filename": "...",
  "filename_generated": "...",
  "thumbnail": "<base64 jpeg, 800px>",
  "ocr_text": ["..."],
  "result": { ... },
  "correction": "",
  "action": "",
  "timestamp": "...",
  "original_file": "hash.ext"
}
```

---

#### Checklist

- [x] Config loader: reads `~/.bill_extractor/config.{yaml,json}`, creates defaults on first run
- [x] History endpoints: `GET /history`, `POST /history`, `DELETE /history/{hash}`
- [x] File storage: save original on `POST /history`; serve on `GET /files/{hash}`
- [x] Proxy + fallback: `POST /extract` proxies to `ocr_url` if set; falls back to local on failure
- [x] Model loading policy: eager if no `ocr_url`; lazy otherwise; `--headless` always eager
- [x] `serve --headless`: registers `/extract` only; skips UI/history routes
- [x] `serve` (full): registers all routes; auto-opens browser on startup
- [x] `extract --server URL`: direct call, no local server required; fallback to local
- [x] Frontend: IDB/FSA code removed; history via API
- [x] Frontend: OCR server status + external URL panel in Settings
- [x] Frontend: disk usage reported by server (replaces `navigator.storage.estimate`)
- [x] All existing tests pass (`python -m pytest`) — 157 passed
- [x] New tests: history CRUD endpoints
- [x] New tests: config loading and defaults
- [ ] New tests: proxy + fallback behaviour (mock remote)
- [x] Commit: *"Phase 2.5 complete — server-side history, unified process model"*

---

### Phase 2.6 — Polish & UX *(complete)*

**Goal:** quality-of-life improvements following Phase 2.5 rollout.

**Completed:**
- [x] Favicon (`GET /favicon.ico` — inline SVG, no file dependency)
- [x] Timestamps on all console log lines; persistent `RotatingFileHandler` log to `~/.bill_extractor/bill_extractor.log`
- [x] Stale code removal — cleaned `bill_parser.py`, `app.py` of Flask/Phase-1 remnants
- [x] Settings page rework — removed Storage, Original Files, History Defaults, File Naming sections; folder tree display for data dir; inline "Change" input (no always-editable field)
- [x] Multi-server round-robin OCR — `ocr_servers` list replaces single `ocr_url`; checkbox per server; auto-insert local entry; backward-compat migration of old `ocr_url` config
- [x] Data folder change takes effect immediately (no server restart) — `PATCH /config` with `data_dir` reinits `_store` in-place
- [x] Provenance metadata on every extraction — `submitted_at`, `completed_at`, `ocr_server`, `doctr_version`, `model_name`
- [x] Hotel date fix — `extract_hotel` now returns `"date": check_in`; `_normalize_date` strips trailing time component (`"23/02/2026 18:58"` → `"23/02/2026"`)
- [x] Thumbnail removed from history.json — history table loads preview from `/files/{original_file}`; PDF records show PDF icon linking to file; session cards still use client-side `_thumb`
- [x] OCR text excluded from CSV export always, regardless of column visibility
- [x] Date range preset persisted to `localStorage` automatically
- [x] Slider window drag — grab the fill bar to move both handles together
- [x] Upload tab source hints — "New" / "Reprocessed" badge; renamed file shown with `from original.jpg` note
- [x] Duplicate card shows previous extraction summary (category, date, amount, meal type) inline
- [x] Config and API tests updated for `ocr_servers` / `data_dir` schema (37 tests passing)

---

### Phase 3 — Expense system integration *(deferred — do not start)*

**Status:** on hold — key information missing. Do not plan implementation
until the questions below are answered.

**Important finding (2026-03-25):** Web research suggests Hitachi Solutions
India is a Microsoft Dynamics 365 shop, not Oracle. Their payroll and expense
management is built on **Microsoft Dynamics 365 Finance & Operations**. The
"Oracle" name may be a misidentification by the end user — very common with
enterprise software.

**Action required — ask Pranitha:**
- Check the URL and logo on the expense submission page — is it Dynamics 365 /
  D365, or genuinely Oracle?
- Can she share a screenshot of the expense entry form (fields, column names)?
- Is there a CSV/Excel import option anywhere in the form?

**Why this matters:**
- If it is **D365 Finance & Operations**: it has documented OData REST APIs and
  Power Automate connectors — programmatic integration may be feasible
- If it is **Oracle Fusion/ERP Cloud**: also has REST APIs but a different
  integration path
- If it is a locked-down web form with no import: browser extension or
  clipboard formatter is the only option

**Potential directions once the above is confirmed:**

- **Template view:** arrange extracted fields in the same order as the expense
  form — user reads top-to-bottom and types, no hunting for fields
- **Clipboard formatter:** "Copy for expense form" button puts a tab-separated
  row on the clipboard, paste-able directly into the form or a spreadsheet feeder
- **CSV export shaped to the system:** if the expense tool accepts CSV imports,
  export in the exact column layout it expects
- **Browser extension:** if the expense tool is a web app, an extension could
  read the extracted JSON and auto-fill form fields directly
- **API integration:** if D365/Oracle REST APIs are accessible, submit expense
  line items directly from the bill extractor frontend

---

## Frontend design decisions

### Storage — File System Access API

History is stored in a **single JSON file on the user's machine**, not in
`localStorage`. `localStorage` holds only a tiny pointer to that file (the
file handle) and user preferences.

- On first launch: one-time prompt — "choose where to save your history file"
- On subsequent launches: file reopens silently (permission persists per browser)
- All new extraction results are appended to this file automatically
- The user can save the file to OneDrive/SharePoint for automatic cross-device
  and cross-browser sync (likely already available at Hitachi)

**Why not `localStorage`:**
- 5–10 MB cap would fill quickly
- Data is trapped inside one browser — switching browsers loses history
- File on disk is portable, user-controlled, and backupable

**Optional secondary file:**
The user can load any other history file on demand (read-only overlay). The
app shows records from both files in the same view. Useful for reviewing an
old backup or a colleague's exported file. No limit on how many can be loaded,
but only the primary file receives new records.

---

### History view — Date range slider

A single **month-level range slider** filters the history view by date.

```
[1M]  [3M]  [6M]  [YTD]  [All]
[Jan 2026 ──●───────────── Mar 2026]
Showing 23 records
```

- Preset buttons: 1M, 3M, 6M, YTD, All
- Slider snaps to month boundaries
- Default view on open: last 3 months (configurable in settings)
- Export respects the current slider range — exports what is visible
- Duplicate detection always checks the full file regardless of slider position
- Future: "last X days" slider can be added if requested

---

### Configuration section

A settings panel (accessible via a gear icon or dedicated tab) exposes:

```
Settings
├── Server
│   └── Extraction service URL     ← points browser at the shared backend
│
├── History file
│   ├── Current file: [path]  [Change]
│   └── Default date range on open  (1M / 3M / 6M / All)
│
├── Export
│   ├── Date format  (DD/MM/YYYY · MM/DD/YYYY · YYYY-MM-DD)
│   ├── CSV delimiter  (comma · semicolon · tab)
│   └── Fields to include  (checkboxes)
│
└── File naming  (for "download renamed copy" after extraction)
    ├── Include date    [toggle]
    ├── Include category  [toggle]
    └── Include meal type  [toggle]
```

All settings stored in `localStorage` (they are small preferences, not data).

---

### Always store raw OCR text

Every history record stores the full raw OCR text alongside the structured
fields — always, unconditionally. Reasons:

- If extraction is wrong or incomplete, the receipt content is still readable
- Useful for debugging and future re-extraction if the model improves
- Makes the app valuable even when the LLM falls short
- Enables future features like full-text search across history

The raw OCR text is never shown by default — it is a stored safety net, not
a primary display field.

---

### Column visibility

The history view is a table. Users choose which columns are visible via a
column picker (a small toggle panel, common in data table UIs).

**Always visible (cannot be hidden):**
- Date
- Thumbnail

**Toggleable (user preference, saved in `localStorage`):**
- Category
- Amount / currency
- Meal type
- Time
- Filename
- Status (good / bad / unchecked)
- Raw OCR text (collapsed by default when shown, expandable inline)

This serves both user profiles cleanly — Pranitha sees the structured fields
she cares about for D365 entry; Vinay could turn off most columns and just
use the app as a timestamped receipt archive.

---

## Open decisions

- [ ] Gather expense system details from Pranitha before Phase 3 planning
      (confirm D365 vs Oracle, get screenshot of expense form fields)
- [ ] Generalisation — see note below

---

## Future consideration — generalising for different users / organisations

**Background:** a potential second user (Vinay, different company, different
country) showed strong interest after a quick demo. His immediate use case is
simpler — drop a bill in as soon as he gets it so it is not lost — but his
expense reporting workflow (Excel sheets) and required fields may differ from
Pranitha's (D365/Oracle form).

**The tension:** the current extraction schema is tailored specifically to
Pranitha's categories (food / travel / hotel) and Hitachi's expense fields.
Vinay may need different categories, different fields, or a different export
format. A third user from a third company could need something else entirely.

**Do not act on this yet.** Pranitha's requirements are the immediate
priority. But keep this in mind as a design constraint — avoid hard-coding
assumptions that would make the app difficult to adapt later:

- Category list (food / travel / hotel) should not be buried deep in prompts
  as if it were universal
- Extracted field set per category should be configurable or at least easy
  to extend
- Export format should be decoupled from the extraction schema
- The settings panel is a natural place for a future "configure your fields"
  section

A likely path when the time comes: the Settings panel gains a
"What do you need extracted?" section where users or admins can define
categories and fields without touching server code. The LLM prompt is then
assembled dynamically from that configuration.

---

## Resolved decisions

**OCR model — doctr is sufficient; GLM-OCR explored and set aside**

GLM-OCR (zai-org/GLM-OCR, 0.9B vision-language model) was evaluated against
all 15 sample receipts using Ollama as the local inference backend.
Both OCR outputs were fed through the same Qwen2.5 extraction pipeline and
the structured JSON results compared field by field.

Findings:
- 13/15 images: identical extraction output regardless of OCR backend
- 1 regression (food_04, a hotel POS thermal slip): GLM-OCR drops the
  receipt header entirely, causing mis-routing and empty extraction;
  doctr handles it correctly
- 1 minor difference (hotel_01 guest name, food_06 delivery time): marginal,
  no practical impact on expense reporting

GLM-OCR does produce cleaner OCR text on noisy receipts and correctly reads
the ₹ symbol without the post-processing fix doctr requires. However these
improvements do not translate into better field extraction — Qwen2.5 is
robust enough to handle doctr's minor noise. GLM-OCR also adds latency
(~4–5s/image on CPU via Ollama vs ~2s for doctr) and requires a separate
inference server.

Decision: keep doctr + Qwen2.5. Do not replace with a vision-language model
at this stage. Revisit only if doctr accuracy becomes a real user-reported
problem on a class of receipts it cannot handle.

**Image thumbnails in history file** — yes, store as base64 in the JSON
history file. Store a resized/compressed thumbnail (~10–15 KB, ~200×200px),
not the original image. The original stays on the user's device. Keeps the
history file lean while still showing a visual beside each record.

**Frontend framework — Vue.js + PrimeVue**
- Vue.js: component model suits this UI naturally; can be loaded from CDN
  with no build step (entire frontend can ship as a single `.html` file)
- PrimeVue: enterprise-feel UI library with the date range slider, data
  tables, file upload, and CSV export utilities built in. Professional and
  polished out of the box — appropriate for an office/enterprise context.

**Deployment model — two separate installations, loosely coupled via config**

```
Backend (FastAPI)                Frontend (Vue + PrimeVue)
─────────────────                ─────────────────────────
Company internal server   ←URL─  Company intranet / SharePoint
                                 OR employee opens .html directly
                                 OR employee runs a local static server

Developer (you):
  FastAPI on localhost:8000
  Frontend opened locally in browser
```

- The server URL is set in the frontend's Settings panel
- A self-hosting employee just needs the correct server URL in config
- CORS must be configured on the FastAPI backend to allow requests from all
  expected origins (company intranet URL, localhost, file:// for direct open)
- File System Access API works from local `file://` as well as `http://`

# Bill Extractor — Restructuring Plan

> Status: draft · last updated 2026-03-25
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
- [ ] FastAPI app created with lifespan model loading
- [ ] `POST /extract` accepts image and PDF, returns correct JSON schema
- [ ] Request queue in place — concurrent requests serialised
- [ ] CORS configured
- [ ] All existing tests pass (`python -m pytest`)
- [ ] New tests for the `/extract` endpoint (upload image → check response schema)
- [ ] New tests for the `/extract` endpoint (upload PDF → check response schema)
- [ ] CLI (`bill-extractor-cli`) still works unchanged
- [ ] `flask` removed from dependencies, `fastapi` + `uvicorn` added to `pyproject.toml`
- [ ] Commit: *"Phase 1 complete — FastAPI stateless extraction service"*

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
- [ ] Vue + PrimeVue scaffolded, single `.html` file loads from CDN
- [ ] Settings panel — server URL saved to `localStorage`
- [ ] File System Access API — first-time setup, reopen on launch
- [ ] `POST /extract` called from browser, result displayed
- [ ] Thumbnail generated client-side (~10KB) and stored in history file
- [ ] Raw OCR text stored in every record
- [ ] Duplicate detection working (MD5 in browser)
- [ ] History table with toggleable columns
- [ ] Date range slider with month snapping and presets
- [ ] Export CSV respects current date range
- [ ] Manual correction and good/bad marking persisted to file
- [ ] Optional secondary file load (read-only overlay)
- [ ] All existing backend tests still pass (`python -m pytest`)
- [ ] Manual smoke test: upload image → result shown → appears in history → duplicate blocked
- [ ] Manual smoke test: upload PDF → same flow
- [ ] Manual smoke test: close and reopen browser → history intact
- [ ] Manual smoke test: open in second browser → independent history
- [ ] Commit: *"Phase 2 complete — Vue frontend with client-side history"*

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

# REST API

The Bill Extractor server exposes a JSON REST API. All endpoints are available when running in full mode (`bill-extractor serve`). Only `POST /extract` is available in headless mode.

Base URL: `http://localhost:8080` (default port)

---

## Extraction

### `POST /extract`

Run OCR and LLM extraction on a receipt image or PDF.

**Request** — multipart form:

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | Receipt image (JPEG, PNG, WEBP) or PDF |

**Response** `200 OK`:

```json
{
  "status": "ok",
  "ocr_text": ["Total Payable: ₹226.00", "Date: 27/02/2026", "TIME: 09:36 PM"],
  "category": "food",
  "date": "27/02/2026",
  "time": "21:36",
  "total_amount": "226.00",
  "currency": "INR",
  "meal_type": "dinner",
  "provenance": {
    "submitted_at": "2026-03-27T10:00:00.000Z",
    "completed_at": "2026-03-27T10:00:07.234Z",
    "ocr_server": "local",
    "doctr_version": "0.9.0",
    "model_name": "Qwen/Qwen2.5-1.5B-Instruct"
  }
}
```

Additional fields by category:

| Category | Extra fields |
|----------|-------------|
| food | `total_amount`, `currency`, `meal_type` |
| travel | `amount`, `from_location`, `to_location` |
| hotel | `name`, `check_in`, `check_out`, `stay_duration_days`, `amount`, `currency` |

**Error responses:**

| Status | Reason |
|--------|--------|
| 400 | Empty file |
| 415 | Unsupported file type |
| 422 | Missing `file` field |
| 503 | Models not yet loaded (retry after the indicated seconds) |

---

## History

### `GET /history`

Return all history records as a JSON array, newest first.

```json
[
  {
    "hash": "d41d8cd98f00b204e9800998ecf8427e",
    "filename": "receipt.jpg",
    "filename_generated": "27-02-2026_food_dinner.jpg",
    "ocr_text": ["..."],
    "result": { "category": "food", ... },
    "provenance": { ... },
    "correction": "",
    "action": "good",
    "timestamp": "2026-03-27T10:00:00.000Z",
    "original_file": "d41d8cd98f00b204e9800998ecf8427e.jpg"
  }
]
```

---

### `POST /history`

Upsert a record (insert or replace by `hash`). Optionally save the original file at the same time.

**Request** — multipart form:

| Field | Type | Description |
|-------|------|-------------|
| `record` | string (JSON) | History record object — must include `hash` |
| `file` | file (optional) | Original file to save alongside the record |

**Response** `200 OK` — the saved record (with `original_file` populated if a file was provided).

---

### `DELETE /history/{hash}`

Delete a record and its associated original file.

**Response** `200 OK` on success, `404` if the hash is not found.

---

## File serving

### `GET /files/{filename}`

Serve a saved original file (e.g. `d41d8...427e.jpg`).

**Response** `200 OK` with the file bytes, `404` if not found.

Path traversal attempts are rejected.

---

## Storage

### `GET /storage`

Report disk usage of the data directory.

```json
{
  "history_bytes": 12480,
  "files_bytes": 2097152,
  "total_bytes": 2109632
}
```

---

## Config

### `GET /config`

Return current server configuration (subset safe to expose to the UI).

```json
{
  "data_dir": "/Users/you/.bill_extractor",
  "ocr_servers": [
    { "url": "local", "enabled": true }
  ],
  "port": 8080
}
```

---

### `PATCH /config`

Update configuration fields. Allowed fields: `data_dir`, `ocr_servers`.

**Request body** (JSON):

```json
{
  "ocr_servers": [
    { "url": "local", "enabled": true },
    { "url": "http://gpu-box:8080", "enabled": true }
  ]
}
```

- If `data_dir` is changed, the history store is reinitialized immediately (no restart required).
- The `local` entry is always preserved — it is auto-inserted if missing.
- Unknown fields return `422`.

---

## Health

### `GET /health`

```json
{
  "status": "ok",
  "model_loaded": true,
  "headless": false
}
```

`model_loaded` is `false` while models are still loading after startup.

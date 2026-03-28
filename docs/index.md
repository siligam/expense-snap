# Bill Extractor

Extract structured expense data from receipt photos and PDFs using a two-stage AI pipeline.

```
Receipt photo or PDF  →  DocTR OCR  →  Qwen2.5-1.5B LLM  →  Structured JSON
```

## What it extracts

| Category | Fields |
|----------|--------|
| **Food** | date, time, total amount, currency, meal type (breakfast / lunch / dinner — inferred from time) |
| **Travel** | date, time, amount |
| **Hotel** | guest name, check-in date, check-out date, stay duration (days), amount, currency |

## Key features

- **Drag-and-drop upload** — images (JPEG, PNG, WEBP) and PDFs
- **Duplicate detection** — MD5 hash computed before upload; already-processed files are flagged instantly
- **Server-side history** — results persist to `~/.bill_extractor/history.json`; any browser sees the same data
- **Multi-server OCR** — round-robin across configured remote servers with automatic local fallback
- **CSV export** — filtered to the current date range, respects column visibility
- **Offline** — after first-time model download the app runs with no internet connection

## Quick links

- [Getting started](getting-started.md) — installation and first run
- [Configuration](configuration.md) — config file reference
- [REST API](api.md) — endpoints for programmatic use
- [Architecture](architecture.md) — how the pipeline works

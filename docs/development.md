# Development

## Setup

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

The `dev` extra installs `pytest`, `mkdocs`, and `mkdocs-material`.

---

## Running tests

```bash
python -m pytest
```

Tests live in `tests/`. There are three test modules:

| File | What it tests |
|------|---------------|
| `test_api.py` | FastAPI endpoints — routing, validation, response schema. Models are mocked; no GPU needed. |
| `test_config.py` | Config loading, defaults, backward-compat migration (`ocr_url` → `ocr_servers`), tilde expansion. |
| `test_history.py` | `HistoryStore` CRUD, atomic writes, file storage, disk usage. |

All tests use `tmp_path` fixtures — nothing is written to `~/.bill_extractor` during testing.

### Test client fixture pattern

`test_api.py` uses two fixtures:

- **`client`** (module-scoped) — patches `_extractor`, `_semaphore`, and `ocr_process` with mocks. Fast; reused across tests.
- **`full_client`** (function-scoped) — additionally patches `_store` with a fresh `HistoryStore` backed by a `tmp_path`. Used for tests that read/write history.

!!! important
    The lifespan in `app.py` has `if X is None:` guards for `_extractor`, `_semaphore`, and `_store`. Without these guards the lifespan would overwrite the test mocks when `TestClient.__enter__()` runs.

---

## Project structure

```
bill_extractor/
├── __init__.py          package version (0.5.0)
├── app.py               FastAPI application, CLI entry point
├── bill_examples.py     few-shot OCR examples for LLM prompts
├── bill_parser.py       LLM-based field extraction (DocTR + Qwen2.5)
├── config.py            Config dataclass + load_config()
├── download_models.py   one-time model download script
├── history.py           HistoryStore — thread-safe CRUD + atomic writes
├── ocr_reader.py        DocTR OCR wrapper
└── templates/
    └── index.html       Vue 3 single-page web UI (~1500 lines)

tests/
├── test_api.py
├── test_config.py
└── test_history.py

docs/                    MkDocs source (this site)
mkdocs.yml               MkDocs configuration
pyproject.toml           Package metadata and dependencies
PLAN.md                  Phase-by-phase development plan (local, git-ignored)
```

---

## Building the docs

```bash
# Serve locally with live reload
mkdocs serve

# Build static site to site/
mkdocs build
```

---

## Branching

- `main` — stable, has a live user. Merge only when a phase is complete and all tests pass.
- `dev` — active development branch. All work happens here.

Commit at natural checkpoints (end of a phase, before a significant refactor). Run `python -m pytest` before every commit.

---

## Adding a new receipt category

1. Add few-shot examples in `bill_extractor/bill_examples.py`
2. Add a `build_{category}_extraction_prompt` function and `extract_{category}` method in `bill_parser.py`
3. Add the category to the router prompt in `BillExtractor.route_category`
4. Update `PLAN.md` and `docs/index.md` with the new fields

# Contributing

## Setup

```bash
git clone https://github.com/siligam/expense-snap.git
cd expense-snap
uv venv --python 3.11
source .venv/bin/activate
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
uv pip install -e ".[dev]"
```

## Running tests

```bash
pytest                                    # all fast tests
pytest tests/test_ocr_integration.py     # requires downloaded models
pytest tests/test_frontend.py            # requires Playwright + running server
```

Install Playwright browsers once before running frontend tests:

```bash
playwright install chromium
```

## Submitting changes

1. Fork the repo and create a branch from `main`
2. Make your changes and add tests where appropriate
3. Run `pytest` and ensure all tests pass
4. Open a pull request — describe what changed and why

## Code style

- Python: standard library conventions, no formatter enforced
- Frontend: Vue 3 Composition API, no build step (CDN only)
- Keep the single-file frontend (`bill_extractor/templates/index.html`) readable — use `offset`/`limit` when reading it

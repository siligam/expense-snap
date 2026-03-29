# Getting started

## Requirements

- Python 3.10 or later
- ~4 GB disk space for model weights
- Apple Silicon (MPS), NVIDIA GPU (CUDA), or CPU — auto-detected at runtime

## Installation

### 1. Install uv

[uv](https://docs.astral.sh/uv/) is the recommended way to install Bill Extractor. It handles Python versions and dependencies in one tool with no separate conda or pyenv setup needed.

=== "macOS / Linux"
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows (PowerShell)"
    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

### 2. Clone the repository

```bash
git clone https://github.com/siligam/expense-snap.git
cd expense-snap
```

### 3. Create an environment and install

=== "macOS / Linux"
    ```bash
    uv venv --python 3.11
    source .venv/bin/activate
    uv pip install -e .
    ```

=== "Windows (PowerShell)"
    ```powershell
    uv venv --python 3.11
    .venv\Scripts\activate
    uv pip install -e .
    ```

!!! warning "Linux without an NVIDIA GPU"
    On Linux, the standard `torch` wheel from PyPI includes CUDA libraries by default (~1.5 GB extra).
    If the machine has no GPU, install the CPU-only wheels first to avoid this:
    ```bash
    uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    uv pip install -e .
    ```
    `torch` and `torchvision` must come from the **same index** — mixing a CPU torch
    with a CUDA torchvision (or vice versa) causes a runtime crash on import.

!!! note "NVIDIA GPU (CUDA)"
    Install CUDA-enabled wheels **before** the package install step:
    ```bash
    uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
    uv pip install -e .
    ```
    Replace `cu121` with your CUDA version if needed (e.g. `cu118`, `cu124`).

!!! note "macOS"
    No extra steps — `uv pip install -e .` picks up the standard PyPI wheel which
    includes MPS (Apple Silicon) support.

!!! note "Conda / venv alternative"
    uv is not required — any Python 3.10+ environment works:
    ```bash
    conda create -n receipt-ai python=3.11 -y && conda activate receipt-ai
    pip install -e .
    ```

### 4. Initialise (one-time)

Downloads both models and creates the data directory:

```bash
bill-extractor init
```

```bash
bill-extractor init
========================================

[1/3] Initialising configuration…
      data dir : /home/you/.bill_extractor
      history  : history.json
      files    : files/

[2/3] Downloading OCR models (DocTR)…
      done.

[3/3] Downloading LLM (Qwen2.5-1.5B-Instruct)…
      tokenizer done.
      weights done.

========================================
Setup complete. Start the app with:

    bill-extractor serve
```

~3.5 GB total. After this the app runs fully offline. Safe to re-run — already-cached files are skipped automatically.

### 5. Start the app

```bash
bill-extractor serve
```

The server starts on **http://localhost:8080** and opens your browser
automatically.

---

!!! tip
    `bill-extractor init` is safe to re-run at any time. If models are already cached
    it completes in seconds with no re-download.

## Running on a GPU server (headless)

If you want to run the extraction service on a remote machine (e.g. a
GPU server) and access the UI from a local browser:

**On the GPU server:**

```bash
bill-extractor serve --headless --port 8080
```

**On the local machine**, point the app at the remote server via
Settings → OCR Servers.

The headless server exposes only `POST /extract` — no UI, no history
routes. File contents are never stored or logged on the remote server;
only standard HTTP access logs are written.

---

## CLI extract (no UI)

Process a single file directly from the terminal:

```bash
bill-extractor extract samples/food_01.jpeg
```

Output:

```bash
❯ bill-extractor extract samples/food_01.jpeg
╭──────────────── food_01.jpeg ─────────────────────╮
│ Category      food                                │
│ Meal type     dinner                              │
│ Date          24/02/2026                          │
│ Time          19:55                               │
│ Total         63.00                               │
│ Currency      INR                                 │
│ OCR server    local                               │
╰───────────────────────────────────────────────────╯
```

Use `--server` to send to a specific extraction server:

```bash
bill-extractor extract receipt.jpg --server http://gpu-box:8080
```

Add `--save` to persist the result to history and the `files/` folder
(equivalent to saving from the web UI):

```bash
bill-extractor extract receipt.jpg --save
```

When stdout is a terminal, results are displayed as a formatted
table. When piped, raw JSON is emitted — so scripting still works:

```bash
bill-extractor extract receipt.jpg | jq .total_amount
```

---

## Data location

All persistent data lives in `~/.bill_extractor/` by default:

```bash
~/.bill_extractor/
├── config.json          ← configuration (auto-created on first run)
├── history.json         ← extraction history database
├── files/               ← renamed original receipts
└── bill_extractor.log   ← server log (rotating, 5 MB × 3 files)
```

You can change the data directory in
[Settings](web-ui.md#settings-tab) — the change takes effect
immediately without a server restart.

# Tutorial

This tutorial walks through two complete end-to-end workflows:

1. **Web UI** — upload receipts, review results, export a report
2. **CLI** — batch-process a folder of receipts from the terminal

Both assume you have already completed [Getting started](getting-started.md) and the server is running.

---

## Workflow 1 — Web UI

### Step 1 — Open the app

Navigate to **http://localhost:8080** in your browser. You land on the **Upload** tab.

---

### Step 2 — Upload receipts

Drag one or more receipt photos or PDFs onto the page, or click **Choose files** to browse.

Each file is processed independently. A card appears for each one:

- **Spinner** — OCR and LLM inference running (a few seconds on GPU, longer on CPU).
- **Result card** — extraction complete.
- **Duplicate** — the file was already processed (detected by MD5 hash). You can skip it or click **Process anyway** to re-extract.

!!! tip
    You can drop files at any time — even while earlier ones are still processing.
    Cards appear in the order files finish, not the order they were dropped.

---

### Step 3 — Review results

Each result card shows the extracted fields — date, amount, category, meal type (for food), hotel name (for hotel).

**Check the generated filename** at the top of the card, e.g. `27-02-2026_food_dinner.jpg`. This is built from the extracted date, category, and meal type. If any of those fields are wrong, the filename will be wrong too — fix the underlying field.

**If the extraction looks wrong:**

1. Click the **Bad** button.
2. Type a correction note — e.g. `"total is 126.00 not 63.00"` or `"category should be travel"`.
3. Click **Save correction**. The note is stored alongside the record in history.

**If the extraction looks right:**

Click **Good** (optional but useful for later filtering) and then move on.

---

### Step 4 — Save to history

Click **Save** on any card to persist it. This:

- Writes the record to `history.json`
- Copies the original file to `files/` with the generated filename (e.g. `27-02-2026_food_dinner.jpg`)

Saved records appear in the **History** tab immediately.

!!! note
    Unsaved cards exist only in the browser session. If you close or refresh the tab,
    unsaved results are lost. Save anything you want to keep before navigating away.

---

### Step 5 — Browse history

Switch to the **History** tab. All saved records appear as a table.

**Filter by date range** — drag the slider handles to narrow to a specific period. Use the preset buttons (**1M**, **3M**, **6M**, **YTD**) for common ranges.

**Filter by category or amount** — click **Filters** to open the filter panel.

**Sort** — click any column header to sort ascending or descending.

**Toggle columns** — use the chip buttons above the table to show or hide columns. Drag column headers to reorder. Preferences are saved automatically.

---

### Step 6 — Export

Click **Export CSV** to download all currently visible records as a spreadsheet. The export respects the active date range and filters — so if you want only food receipts from last month, set that filter first.

OCR text is excluded from the CSV even if that column is visible.

---

## Workflow 2 — CLI

The CLI is useful for scripting, automation, or batch-processing without opening a browser.

### Step 1 — Extract a single file

```bash
bill-extractor extract receipt.jpg
```

When run in a terminal, results are displayed as a formatted table:

```
╭─ receipt.jpg ─────────────────────╮
│ Category     food                  │
│ Meal type    dinner                │
│ Date         24/02/2026            │
│ Time         19:55                 │
│ Total        63.00                 │
│ Currency     INR                   │
│ OCR server   local                 │
╰────────────────────────────────────╯
```

---

### Step 2 — Save to history from the CLI

Add `--save` to write the result to history and copy the file to `files/` — exactly what the web UI save button does:

```bash
bill-extractor extract receipt.jpg --save
```

The server must be running for `--save` to work (it POSTs to `/history`).

---

### Step 3 — Batch-process a folder

Use a shell loop to process every JPEG in a folder:

=== "macOS / Linux"
    ```bash
    for f in ~/receipts/*.jpg; do
        bill-extractor extract "$f" --save
    done
    ```

=== "Windows (PowerShell)"
    ```powershell
    Get-ChildItem "$HOME\receipts\*.jpg" | ForEach-Object {
        bill-extractor extract $_.FullName --save
    }
    ```

Each file is sent to the server sequentially. Results are saved to history as they complete.

!!! tip
    The server processes one file at a time internally (GPU/CPU concurrency limit).
    Sending requests faster than it can process them is fine — they queue automatically.

---

### Step 4 — Script with JSON output

When stdout is piped, `bill-extractor extract` emits raw JSON — making it easy to use with `jq` or any scripting tool:

=== "macOS / Linux"
    ```bash
    # Extract just the total amount  (requires jq)
    bill-extractor extract receipt.jpg | jq -r .total_amount

    # Collect totals from multiple files into a CSV
    for f in ~/receipts/*.jpg; do
        result=$(bill-extractor extract "$f")
        date=$(echo "$result" | jq -r .date)
        amount=$(echo "$result" | jq -r .total_amount)
        echo "$f,$date,$amount"
    done > report.csv
    ```

=== "Windows (PowerShell)"
    ```powershell
    # Extract just the total amount  (ConvertFrom-Json is built into PowerShell)
    (bill-extractor extract receipt.jpg | ConvertFrom-Json).total_amount

    # Collect totals from multiple files into a CSV
    Get-ChildItem "$HOME\receipts\*.jpg" | ForEach-Object {
        $r = bill-extractor extract $_.FullName | ConvertFrom-Json
        "$($_.FullName),$($r.date),$($r.total_amount)"
    } | Set-Content report.csv
    ```

    !!! note
        `ConvertFrom-Json` is available in PowerShell 3+ (included in Windows 8 and later).
        No extra tools needed.

---

### Step 5 — Use a remote server

If you have a GPU server running `bill-extractor serve --headless`, point the CLI at it with `--server`:

```bash
bill-extractor extract receipt.jpg --server http://gpu-box:8080
```

If the remote is unreachable, the CLI automatically falls back to `http://localhost:8080`.

---

## What's next

- [Configuration](configuration.md) — change the data directory, add remote OCR servers, adjust port
- [Web UI reference](web-ui.md) — detailed description of every UI feature
- [REST API](api.md) — integrate with your own tools

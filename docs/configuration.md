# Configuration

## Config file location

On first run, Bill Extractor creates a default config file at:

```
~/.bill_extractor/config.json
```

YAML is also supported — place a `config.yaml` or `config.yml` in the same directory (requires `pip install pyyaml`). If both exist, YAML takes precedence.

You can also pass a specific path at startup:
```bash
bill-extractor serve --config /path/to/config.json
```

---

## Fields

### `history_file`

Path to the JSON history database.

```json
"history_file": "~/.bill_extractor/history.json"
```

Tilde (`~`) is expanded. The file is created automatically if it does not exist.

---

### `files_dir`

Directory where renamed original receipt files are saved.

```json
"files_dir": "~/.bill_extractor/files"
```

Created automatically on first use. Files are stored as `{md5hash}.{ext}`.

---

### `ocr_servers`

List of OCR servers to use for extraction. Bill Extractor tries enabled servers in order, round-robins across them on successive requests, and falls back to local models if all remotes fail.

```json
"ocr_servers": [
  { "url": "local", "enabled": true },
  { "url": "http://gpu-server:8080", "enabled": false }
]
```

| Entry | Meaning |
|-------|---------|
| `{ "url": "local", "enabled": true }` | Use the locally loaded models |
| `{ "url": "http://...", "enabled": true }` | Proxy to a remote `bill-extractor serve --headless` instance |

Rules:
- The `local` entry is always preserved — the app re-inserts it if you remove it via the UI.
- If all remote servers fail, the request falls back to the local models automatically.
- If `local` is the only enabled entry, models are loaded at startup (10 s, one-time).
- If only remotes are enabled, local model loading is skipped at startup (fast start); models are lazy-loaded only if remotes fail.

**Backward compatibility:** old configs with `"ocr_url": "http://..."` are automatically converted to the `ocr_servers` list format on load.

---

### `port`

Port the server listens on.

```json
"port": 8080
```

Can be overridden at runtime: `bill-extractor serve --port 9090`

---

## Changing settings at runtime

The [Settings tab](web-ui.md#settings-tab) in the web UI lets you:

- Change the data directory (takes effect immediately — no restart needed)
- Add, remove, or toggle OCR servers

Changes are applied via `PATCH /config` and written back to `config.json`.

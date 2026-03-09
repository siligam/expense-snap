from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

from .bill_parser import BillingInformationExtractor
from .ocr_reader import process as ocr_process

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
CACHE_FILE = DATA_DIR / "cache.json"
HISTORY_FILE = DATA_DIR / "history.json"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates")

print("Loading models, please wait...")
extractor = BillingInformationExtractor()
print("Ready.\n")


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _load_history_flat() -> list:
    """Load history as a flat list, migrating from old session-based format if needed."""
    raw = _load(HISTORY_FILE, [])
    if not raw:
        return []
    # Detect old format: list of sessions (each has an 'items' key)
    if isinstance(raw[0], dict) and "items" in raw[0]:
        flat = []
        seen = set()
        for session in raw:
            for item in session.get("items", []):
                h = item.get("hash")
                if h and h not in seen:
                    seen.add(h)
                    flat.append(item)
        _save(HISTORY_FILE, flat)  # migrate in place
        return flat
    return raw


def _find_in_cache(h: str) -> dict | None:
    for item in _load(CACHE_FILE, []):
        if item.get("hash") == h:
            return item
    return None


def _find_in_history(h: str) -> dict | None:
    for item in _load_history_flat():
        if item.get("hash") == h:
            return item
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/uploads/<filename>")
def serve_upload(filename: str):
    return send_from_directory(UPLOADS_DIR, filename)


@app.route("/api/process", methods=["POST"])
def process():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No image provided"}), 400

    image_bytes = file.read()
    image_hash = _hash(image_bytes)
    original_name = file.filename or "image.jpeg"

    # Check cache
    cached = _find_in_cache(image_hash)
    if cached:
        return jsonify({**cached, "source": "cache"})

    # Check history
    from_history = _find_in_history(image_hash)
    if from_history:
        cache = _load(CACHE_FILE, [])
        if not any(i.get("hash") == image_hash for i in cache):
            cache.append(from_history)
            _save(CACHE_FILE, cache)
        return jsonify({**from_history, "source": "history"})

    # Save image
    ext = Path(original_name).suffix or ".jpeg"
    filename = f"{image_hash}{ext}"
    image_path = UPLOADS_DIR / filename
    image_path.write_bytes(image_bytes)

    # OCR + extract
    try:
        ocr_lines = ocr_process(str(image_path))
        result = extractor.extract(ocr_lines)
        status = "ok"
    except Exception as exc:
        ocr_lines = []
        result = {}
        status = f"error: {exc}"

    item = {
        "hash": image_hash,
        "filename": original_name,
        "image_url": f"/uploads/{filename}",
        "ocr_text": ocr_lines,
        "result": result,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "status": status,
    }

    cache = _load(CACHE_FILE, [])
    cache.append(item)
    _save(CACHE_FILE, cache)

    return jsonify({**item, "source": "new"})


@app.route("/api/cache", methods=["GET"])
def get_cache():
    return jsonify(_load(CACHE_FILE, []))


@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify(_load_history_flat())


@app.route("/api/cache/<item_hash>", methods=["DELETE"])
def delete_cache_item(item_hash: str):
    cache = _load(CACHE_FILE, [])
    cache = [i for i in cache if i.get("hash") != item_hash]
    _save(CACHE_FILE, cache)
    return jsonify({"ok": True})


@app.route("/api/history/<item_hash>", methods=["DELETE"])
def delete_history_item(item_hash: str):
    history = _load_history_flat()
    history = [i for i in history if i.get("hash") != item_hash]
    _save(HISTORY_FILE, history)
    return jsonify({"ok": True})


@app.route("/api/history", methods=["DELETE"])
def clear_history():
    _save(HISTORY_FILE, [])
    return jsonify({"ok": True})


@app.route("/api/item/<item_hash>", methods=["PATCH"])
def update_item(item_hash: str):
    body = request.get_json(silent=True) or {}

    def _patch(item):
        if "action" in body:
            item["action"] = body["action"]
        if "correction" in body:
            item["correction"] = body["correction"]
        return item

    cache = _load(CACHE_FILE, [])
    cache_changed = False
    for item in cache:
        if item.get("hash") == item_hash:
            _patch(item)
            cache_changed = True
            break
    if cache_changed:
        _save(CACHE_FILE, cache)

    history = _load_history_flat()
    hist_changed = False
    for item in history:
        if item.get("hash") == item_hash:
            _patch(item)
            hist_changed = True
            break
    if hist_changed:
        _save(HISTORY_FILE, history)

    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
def reset():
    cache = _load(CACHE_FILE, [])
    if cache:
        history = _load_history_flat()
        existing_hashes = {i.get("hash") for i in history}
        new_items = [i for i in cache if i.get("hash") not in existing_hashes]
        if new_items:
            # Prepend new items (newest first)
            _save(HISTORY_FILE, new_items + history)
        added = len(new_items)
    else:
        added = 0
    _save(CACHE_FILE, [])
    return jsonify({"ok": True, "added": added})


def main():
    app.run(debug=False, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()

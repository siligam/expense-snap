from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

_BASE_DIR = Path(__file__).parent
logger = logging.getLogger("bill_extractor")

from .bill_parser import BillingInformationExtractor, BillingExtractionConfig
from .config import Config, load_config
from .history import HistoryStore
from .ocr_reader import process as ocr_process

try:
    from doctr import __version__ as _DOCTR_VERSION  # type: ignore[import]
except Exception:
    _DOCTR_VERSION = None

_DEFAULT_MODEL_NAME: str = BillingExtractionConfig().model_name

# ---------------------------------------------------------------------------
# Favicon (blue rounded square + white receipt with zigzag tear bottom)
# ---------------------------------------------------------------------------

_FAVICON_SVG: bytes = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#3b82f6"/>'
    '<path d="M9 5h14v20l-2-2-2 2-2-2-2 2-2-2-2 2-2-2V5z" fill="white"/>'
    '<rect x="12" y="9" width="8" height="2" rx="1" fill="#bfdbfe"/>'
    '<rect x="12" y="13" width="8" height="2" rx="1" fill="#bfdbfe"/>'
    '<rect x="12" y="17" width="5" height="2" rx="1" fill="#bfdbfe"/>'
    "</svg>"
).encode()

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

_log_configured = False  # True after CLI configures logging via uvicorn log_config


def _build_uvicorn_log_config(log_path: Path) -> dict:
    """Full logging config passed to uvicorn.run() — timestamps on console + file."""
    global _log_configured
    _log_configured = True
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(asctime)s %(levelprefix)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "file": {
                "format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console_default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "console_access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "formatter": "file",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_path),
                "maxBytes": 5_242_880,   # 5 MB
                "backupCount": 3,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn":        {"handlers": ["console_default", "file"], "level": "INFO", "propagate": False},
            "uvicorn.error":  {"handlers": ["console_default", "file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["console_access",  "file"], "level": "INFO", "propagate": False},
            "bill_extractor": {"handlers": ["console_default", "file"], "level": "INFO", "propagate": False},
        },
        "root": {"handlers": ["file"], "level": "WARNING"},
    }


def _setup_file_logging(log_path: Path) -> None:
    """Fallback: add file handler when running under direct `uvicorn` (not CLI).

    Skipped if the CLI already configured logging via _build_uvicorn_log_config().
    """
    if _log_configured:
        return

    from logging.handlers import RotatingFileHandler

    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(log_path, maxBytes=5_242_880, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    # Route all uvicorn loggers through root so the file handler catches them
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).propagate = True


# ---------------------------------------------------------------------------
# Global state — initialised once at startup via lifespan
# ---------------------------------------------------------------------------

_extractor: BillingInformationExtractor | None = None
_semaphore: asyncio.Semaphore | None = None
_store: HistoryStore | None = None
_config: Config | None = None
_lazy_loading = False          # True while models are loading in background
_lazy_load_event: asyncio.Event | None = None
_ocr_rr_idx = 0               # round-robin cursor for remote OCR servers

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------

def _load_models_sync() -> None:
    global _extractor
    _extractor = BillingInformationExtractor()


async def _ensure_models() -> None:
    """Lazy-load models on first fallback request.

    Returns immediately if already loaded (or mocked in tests).
    Raises 503 while initial load is in progress.
    """
    global _lazy_loading, _lazy_load_event, _extractor, _semaphore
    if _extractor is not None:
        return  # already loaded (or mocked in tests)

    loop = asyncio.get_running_loop()

    if _lazy_loading:
        assert _lazy_load_event is not None
        await asyncio.wait_for(_lazy_load_event.wait(), timeout=120)
        return

    # First call triggers the load
    _lazy_loading = True
    _lazy_load_event = asyncio.Event()
    _semaphore = asyncio.Semaphore(1)

    try:
        await loop.run_in_executor(None, _load_models_sync)
    finally:
        _lazy_loading = False
        _lazy_load_event.set()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    headless: bool = False,
    cfg: Config | None = None,
) -> FastAPI:
    """Create and return the FastAPI app.

    headless=True  → /extract only (remote GPU server mode)
    headless=False → full stack: /extract + history/file/storage routes + UI
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _extractor, _semaphore, _store, _config

        # Config (may already be set, e.g. from CLI args)
        if _config is None:
            _config = cfg or load_config()

        if not headless and _store is None:
            _store = HistoryStore(_config.history_file, _config.files_dir)

        # Model loading policy:
        # - headless: always eager (serve is a GPU node)
        # - no enabled remote servers: eager (local models always needed)
        # - remote servers configured: skip startup load (lazy fallback only)
        if _extractor is None:  # allow tests to mock before lifespan runs
            _remotes = [
                s["url"] for s in _config.ocr_servers
                if s.get("enabled") and s.get("url") != "local"
            ]
            if headless or not _remotes:
                print("Loading models, please wait…")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _load_models_sync)
                print("Ready.\n")
            else:
                print(f"Remote OCR server(s): {', '.join(_remotes)}")
                print("Models will be loaded lazily if remotes are unreachable.\n")

        if _semaphore is None:
            _semaphore = asyncio.Semaphore(1)

        _setup_file_logging(_config.history_file.parent / "bill_extractor.log")

        yield

    _origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
    allowed_origins = [o.strip() for o in _origins_env.split(",")]

    app = FastAPI(
        title="Bill Extractor",
        version="0.5.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r".*" if "*" in allowed_origins else None,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # ----------------------------------------------------------------
    # Routes — always registered
    # ----------------------------------------------------------------

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(content=_FAVICON_SVG, media_type="image/svg+xml")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "model_loaded": _extractor is not None,
            "headless": headless,
        }

    @app.post("/extract")
    async def extract(file: UploadFile = File(...)):
        from datetime import datetime, timezone
        submitted_at = datetime.now(timezone.utc).isoformat()

        ext = Path(file.filename or "upload").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Round-robin across all enabled servers (local + remote)
        global _ocr_rr_idx
        _servers = _config.ocr_servers if _config else []
        pool = [s["url"] for s in _servers if s.get("enabled")]

        if not pool:
            raise HTTPException(status_code=503, detail="No OCR servers configured.")

        # Grab and advance the index before any await so concurrent requests
        # each get a distinct starting position (no yield point between read and write).
        start = _ocr_rr_idx % len(pool)
        _ocr_rr_idx = (start + 1) % len(pool)
        for i in range(len(pool)):
            url = pool[(start + i) % len(pool)]

            if url == "local":
                await _ensure_models()
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                try:
                    tmp.write(contents)
                    tmp.close()
                    async with _semaphore:
                        loop = asyncio.get_running_loop()
                        ocr_lines, result = await loop.run_in_executor(
                            None, _run_inference, tmp.name
                        )
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(
                        status_code=500, detail=f"Extraction failed: {exc}"
                    ) from exc
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
                completed_at = datetime.now(timezone.utc).isoformat()
                logger.info("extract: %s  server=local", file.filename or "upload")
                return {"ocr_text": ocr_lines, **result, "status": "ok",
                        "provenance": _make_provenance(submitted_at, completed_at, "local")}
            else:
                try:
                    ocr_lines, result = await _proxy_extract(
                        url, file.filename or "upload", ext, contents
                    )
                    completed_at = datetime.now(timezone.utc).isoformat()
                    logger.info("extract: %s  server=%s", file.filename or "upload", url)
                    return {"ocr_text": ocr_lines, **result, "status": "ok",
                            "provenance": _make_provenance(submitted_at, completed_at, url)}
                except httpx.HTTPError:
                    continue  # server unreachable — try next in pool

        raise HTTPException(status_code=503, detail="No OCR servers reachable.")

    # ----------------------------------------------------------------
    # Routes — full-stack only (history + file serving + UI)
    # ----------------------------------------------------------------

    if not headless:

        @app.get("/")
        async def index():
            return FileResponse(_BASE_DIR / "templates" / "index.html")

        @app.get("/history")
        async def get_history():
            return _store.all()

        @app.post("/history")
        async def post_history(
            record: str = Form(...),
            file: UploadFile | None = File(default=None),
        ):
            try:
                rec = json.loads(record)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid JSON in record: {exc}")

            if file and file.filename:
                data = await file.read()
                if data:
                    ext = Path(file.filename).suffix.lower()
                    # Prefer the human-readable generated name so files/ is browsable
                    generated = rec.get("filename_generated", "")
                    stem = Path(generated).stem if generated else rec.get("hash", "unknown")
                    # Collision avoidance: append _2, _3, … if the name already exists
                    fname = f"{stem}{ext}"
                    counter = 1
                    while _store.get_file_path(fname) is not None:
                        counter += 1
                        fname = f"{stem}_{counter}{ext}"
                    _store.save_file(fname, data)
                    rec["original_file"] = fname

            saved = _store.upsert(rec)
            return saved

        @app.delete("/history/{hash_}")
        async def delete_history(hash_: str):
            rec = _store.get(hash_)
            if rec and rec.get("original_file"):
                _store.delete_file(rec["original_file"])
            deleted = _store.delete(hash_)
            if not deleted:
                raise HTTPException(status_code=404, detail="Record not found.")
            return {"status": "deleted", "hash": hash_}

        @app.get("/files/{filename}")
        async def get_file(filename: str):
            # Prevent path traversal
            if "/" in filename or "\\" in filename or ".." in filename:
                raise HTTPException(status_code=400, detail="Invalid filename.")
            p = _store.get_file_path(filename)
            if p is None:
                raise HTTPException(status_code=404, detail="File not found.")
            return FileResponse(str(p))

        @app.get("/storage")
        async def storage():
            return _store.disk_usage()

        @app.get("/config")
        async def get_config():
            return {
                "data_dir": str(_config.data_dir),
                "ocr_servers": _config.ocr_servers,
                "port": _config.port,
            }

        @app.patch("/config")
        async def patch_config(body: dict):
            allowed = {"ocr_servers", "data_dir"}
            unknown = set(body) - allowed
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail=f"Read-only or unknown fields: {', '.join(sorted(unknown))}. "
                           f"Editable: {', '.join(sorted(allowed))}.",
                )
            if "ocr_servers" in body:
                servers = body["ocr_servers"]
                if not isinstance(servers, list):
                    raise HTTPException(status_code=422, detail="ocr_servers must be a list.")
                # Ensure local entry is always present
                if not any(s.get("url") == "local" for s in servers):
                    servers = [{"url": "local", "enabled": True}] + servers
                _config.ocr_servers = servers
            if "data_dir" in body:
                new_dir = Path(os.path.expanduser(str(body["data_dir"])))
                new_dir.mkdir(parents=True, exist_ok=True)
                _config.history_file = new_dir / "history.json"
                _config.files_dir = new_dir / "files"
                # Swap the store immediately — no restart needed.
                # Existing data remains at the old location; the user migrates manually.
                global _store
                _store = HistoryStore(_config.history_file, _config.files_dir)
            # Persist atomically to config.json in the (possibly new) data_dir
            cfg_path = _config.history_file.parent / "config.json"
            persisted = {
                "history_file": str(_config.history_file),
                "files_dir": str(_config.files_dir),
                "ocr_servers": _config.ocr_servers,
                "port": _config.port,
            }
            tmp = cfg_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(persisted, indent=2) + "\n")
            tmp.replace(cfg_path)
            return {
                "data_dir": str(_config.data_dir),
                "ocr_servers": _config.ocr_servers,
                "port": _config.port,
            }

    return app


# ---------------------------------------------------------------------------
# Blocking inference helper
# ---------------------------------------------------------------------------

def _make_provenance(submitted_at: str, completed_at: str, ocr_server: str) -> dict:
    """Build the provenance block attached to every extraction result."""
    return {
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "ocr_server": ocr_server,
        "doctr_version": _DOCTR_VERSION,
        "model_name": _extractor.config.model_name if _extractor else _DEFAULT_MODEL_NAME,
    }


def _run_inference(file_path: str) -> tuple[list[str], dict]:
    ocr_lines = ocr_process(file_path)
    result = _extractor.extract(ocr_lines)
    return ocr_lines, result


# ---------------------------------------------------------------------------
# Remote proxy helper
# ---------------------------------------------------------------------------

async def _proxy_extract(
    base_url: str,
    filename: str,
    ext: str,
    contents: bytes,
) -> tuple[list[str], dict]:
    url = base_url.rstrip("/") + "/extract"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            files={"file": (filename, contents, _mime(ext))},
        )
        resp.raise_for_status()
    data = resp.json()
    ocr_lines = data.pop("ocr_text", [])
    data.pop("status", None)
    return ocr_lines, data


def _mime(ext: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# Module-level app (used by uvicorn and tests)
# ---------------------------------------------------------------------------

app = create_app()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(prog="bill-extractor")
    sub = parser.add_subparsers(dest="cmd")

    serve_p = sub.add_parser("serve", help="Start the server")
    serve_p.add_argument("--headless", action="store_true", help="OCR endpoint only")
    serve_p.add_argument("--port", type=int, default=None)
    serve_p.add_argument("--ocr-url", dest="ocr_url", default=None)

    extract_p = sub.add_parser("extract", help="Extract a single file")
    extract_p.add_argument("file", help="Path to image or PDF")
    extract_p.add_argument("--server", default=None, help="Remote server URL")
    extract_p.add_argument("--save", action="store_true", help="Save result to history and files/")

    sub.add_parser("init", help="Download models and initialise data directory (run once after install)")

    args = parser.parse_args()

    if args.cmd == "extract":
        import sys
        _run_extract_cmd(args.file, args.server, save=args.save)
        sys.exit(0)

    if args.cmd == "init":
        import sys
        _run_init_cmd()
        sys.exit(0)

    # Default: serve
    cfg = load_config()
    if args.cmd == "serve":
        if args.port:
            cfg.port = args.port
        if args.ocr_url:
            cfg.ocr_servers = [
                {"url": "local", "enabled": False},
                {"url": args.ocr_url, "enabled": True},
            ]
        headless = args.headless
    else:
        headless = False

    global _config
    _config = cfg

    if not headless:
        import threading
        def _open_browser():
            import time; time.sleep(1.5)
            webbrowser.open(f"http://localhost:{cfg.port}")
        threading.Thread(target=_open_browser, daemon=True).start()

    target_app = create_app(headless=headless, cfg=cfg)
    log_cfg = _build_uvicorn_log_config(cfg.history_file.parent / "bill_extractor.log")
    uvicorn.run(target_app, host="0.0.0.0", port=cfg.port, reload=False, log_config=log_cfg)


def _run_init_cmd() -> None:
    """Download models and create data directory. Safe to re-run."""
    import subprocess, sys

    print("bill-extractor init")
    print("=" * 40)

    # 1. Config + directories (in-process — no model loading involved)
    print("\n[1/3] Initialising configuration…")
    cfg = load_config()
    cfg.files_dir.mkdir(parents=True, exist_ok=True)
    print(f"      data dir : {cfg.data_dir}")
    print(f"      history  : {cfg.history_file.name}")
    print(f"      files    : {cfg.files_dir.name}/")

    # 2+3. Run the download script in a subprocess.
    #
    # bill_parser.py sets HF_HUB_OFFLINE in the environment before anything
    # imports huggingface_hub. Once that library is imported its offline flag
    # is cached as a Python bool — no in-process override is reliable. A fresh
    # subprocess never imports bill_parser, so HF_HUB_OFFLINE is never set and
    # downloads proceed normally. This is exactly what `uv run python
    # download_models.py` does when called manually.
    print("\n[2/3] Downloading OCR models (DocTR)…")
    print("[3/3] Downloading LLM (Qwen2.5-1.5B-Instruct)…")
    print("      (progress shown below)\n")

    download_script = Path(__file__).parent / "download_models.py"
    result = subprocess.run([sys.executable, str(download_script)])
    if result.returncode != 0:
        print("\nDownload failed — check the output above for details.", file=sys.stderr)
        sys.exit(result.returncode)

    print("\n" + "=" * 40)
    print("Setup complete. Start the app with:\n")
    print("    bill-extractor serve\n")


def _run_extract_cmd(file_path: str, server_url: str | None, save: bool = False) -> None:
    import hashlib
    import sys
    from datetime import datetime, timezone
    import httpx as _httpx

    path = Path(file_path)
    if not path.exists():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        print(f"Error: unsupported file type '{ext}'", file=sys.stderr)
        sys.exit(1)

    cfg = load_config()
    urls_to_try: list[str] = []
    if server_url:
        urls_to_try.append(server_url)
    urls_to_try.append(f"http://localhost:{cfg.port}")

    data = path.read_bytes()

    for url in urls_to_try:
        try:
            with _httpx.Client(timeout=120) as client:
                resp = client.post(
                    url.rstrip("/") + "/extract",
                    files={"file": (path.name, data, _mime(ext))},
                )
                resp.raise_for_status()
                result = resp.json()
                print(json.dumps(result, indent=2, ensure_ascii=False))

                if save:
                    file_hash = hashlib.md5(data).hexdigest()
                    ocr_text = result.pop("ocr_text", [])
                    result.pop("status", None)
                    provenance = result.pop("provenance", {})
                    # Build generated filename from extracted fields
                    parts = []
                    if result.get("date"):
                        parts.append(result["date"].replace("/", "-"))
                    if result.get("category"):
                        parts.append(result["category"])
                    if result.get("meal_type"):
                        parts.append(result["meal_type"])
                    filename_generated = ("_".join(parts) + ext) if parts else path.name
                    record = {
                        "hash": file_hash,
                        "filename": path.name,
                        "filename_generated": filename_generated,
                        "ocr_text": ocr_text,
                        "result": result,
                        "provenance": provenance,
                        "correction": "",
                        "action": "",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    save_resp = client.post(
                        url.rstrip("/") + "/history",
                        data={"record": json.dumps(record)},
                        files={"file": (path.name, data, _mime(ext))},
                    )
                    save_resp.raise_for_status()
                    print(f"Saved: {save_resp.json().get('original_file', path.name)}", file=sys.stderr)
                return
        except _httpx.HTTPError:
            continue

    print("Error: no reachable server found.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

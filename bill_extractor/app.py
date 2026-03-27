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

from .bill_parser import BillingInformationExtractor
from .config import Config, load_config
from .history import HistoryStore
from .ocr_reader import process as ocr_process

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
        # - no ocr_url: eager (local server, models always needed)
        # - ocr_url set: skip startup load (lazy fallback only)
        if _extractor is None:  # allow tests to mock before lifespan runs
            if headless or _config.ocr_url is None:
                print("Loading models, please wait…")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _load_models_sync)
                print("Ready.\n")
            else:
                print(f"Remote OCR configured: {_config.ocr_url}")
                print("Models will be loaded lazily if remote is unreachable.\n")

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
        allow_methods=["POST", "GET", "DELETE"],
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
        ext = Path(file.filename or "upload").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Try remote OCR proxy first
        if _config and _config.ocr_url:
            try:
                ocr_lines, result = await _proxy_extract(
                    _config.ocr_url, file.filename or "upload", ext, contents
                )
                return {"ocr_text": ocr_lines, **result, "status": "ok"}
            except httpx.HTTPError:
                pass  # fall through to local

        # Local inference
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
            raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc
        finally:
            Path(tmp.name).unlink(missing_ok=True)

        return {"ocr_text": ocr_lines, **result, "status": "ok"}

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
                "history_file": str(_config.history_file),
                "files_dir": str(_config.files_dir),
                "ocr_url": _config.ocr_url,
                "port": _config.port,
            }

        @app.patch("/config")
        async def patch_config(body: dict):
            allowed = {"ocr_url", "port"}
            unknown = set(body) - allowed
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail=f"Read-only or unknown fields: {', '.join(sorted(unknown))}. "
                           f"Editable: {', '.join(sorted(allowed))}.",
                )
            if "ocr_url" in body:
                _config.ocr_url = body["ocr_url"] or None
            if "port" in body:
                _config.port = int(body["port"])
            # Persist to the config file (JSON only for simplicity)
            cfg_path = _config.history_file.parent / "config.json"
            data = {
                "history_file": str(_config.history_file),
                "files_dir": str(_config.files_dir),
                "ocr_url": _config.ocr_url,
                "port": _config.port,
            }
            tmp = cfg_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n")
            tmp.replace(cfg_path)
            return data

    return app


# ---------------------------------------------------------------------------
# Blocking inference helper
# ---------------------------------------------------------------------------

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

    args = parser.parse_args()

    if args.cmd == "extract":
        import sys
        _run_extract_cmd(args.file, args.server)
        sys.exit(0)

    # Default: serve
    cfg = load_config()
    if args.cmd == "serve":
        if args.port:
            cfg.port = args.port
        if args.ocr_url:
            cfg.ocr_url = args.ocr_url
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


def _run_extract_cmd(file_path: str, server_url: str | None) -> None:
    import sys
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

    with open(file_path, "rb") as f:
        data = f.read()

    for url in urls_to_try:
        try:
            with _httpx.Client(timeout=120) as client:
                resp = client.post(
                    url.rstrip("/") + "/extract",
                    files={"file": (path.name, data, _mime(ext))},
                )
                resp.raise_for_status()
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
                return
        except _httpx.HTTPError:
            continue

    print("Error: no reachable server found.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

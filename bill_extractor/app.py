from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .bill_parser import BillingInformationExtractor
from .ocr_reader import process as ocr_process

# ---------------------------------------------------------------------------
# Global state — initialised once at startup via lifespan
# ---------------------------------------------------------------------------

_extractor: BillingInformationExtractor | None = None
_semaphore: asyncio.Semaphore | None = None

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _extractor, _semaphore
    print("Loading models, please wait...")
    _extractor = BillingInformationExtractor()
    _semaphore = asyncio.Semaphore(1)   # serialise GPU/MPS inference
    print("Ready.\n")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

# Comma-separated origins in env var; default allows all (open internal tool)
_origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",")]

app = FastAPI(title="Bill Extractor", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r".*" if "*" in ALLOWED_ORIGINS else None,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _extractor is not None}


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

    # Write to a temp file — ocr_reader needs a file path, not bytes
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


def _run_inference(file_path: str) -> tuple[list[str], dict]:
    """Blocking inference — runs in a thread via run_in_executor."""
    ocr_lines = ocr_process(file_path)
    result = _extractor.extract(ocr_lines)
    return ocr_lines, result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("bill_extractor.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()

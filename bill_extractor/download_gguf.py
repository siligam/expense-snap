"""Download GGUF model files from HuggingFace Hub.

Usage:
    python -m bill_extractor.download_gguf qwen2.5-1.5b-q4km
    python -m bill_extractor.download_gguf qwen2.5-0.5b-q4km
    python -m bill_extractor.download_gguf --list

The HF token is read from the HF_TOKEN environment variable.
Never pass the token as a CLI argument or hardcode it.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from loguru import logger

from .config import DEFAULT_DIR

MODELS_DIR = DEFAULT_DIR / "models"

# (repo_id, filename)
GGUF_MODELS: dict[str, tuple[str, str]] = {
    "qwen2.5-1.5b-q4km": (
        "bartowski/Qwen2.5-1.5B-Instruct-GGUF",
        "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
    ),
    "qwen2.5-0.5b-q4km": (
        "bartowski/Qwen2.5-0.5B-Instruct-GGUF",
        "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    ),
}


def download_gguf(
    model_key: str,
    dest_dir: Path = MODELS_DIR,
    token: str | None = None,
) -> Path:
    """Download a GGUF file to dest_dir and return its local path."""
    from huggingface_hub import hf_hub_download

    if model_key not in GGUF_MODELS:
        raise ValueError(
            f"Unknown model key {model_key!r}. "
            f"Available: {', '.join(GGUF_MODELS)}"
        )

    repo_id, filename = GGUF_MODELS[model_key]
    token = token or os.environ.get("HF_TOKEN")
    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading {} from {} …", filename, repo_id)
    local_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(dest_dir),
        token=token,
    )
    path = Path(local_path)
    logger.info("Saved to {}", path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download GGUF model files for bill-extractor."
    )
    parser.add_argument(
        "model_key",
        nargs="?",
        choices=list(GGUF_MODELS),
        help="Model to download.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available model keys and exit.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=MODELS_DIR,
        help=f"Destination directory (default: {MODELS_DIR})",
    )
    args = parser.parse_args()

    if args.list:
        for key, (repo, fname) in GGUF_MODELS.items():
            print(f"  {key:30s}  {repo}/{fname}")
        return

    if not args.model_key:
        parser.print_help()
        return

    if not os.environ.get("HF_TOKEN"):
        print("Warning: HF_TOKEN not set. Download may fail for gated models.")

    path = download_gguf(args.model_key, dest_dir=args.dest)
    print(f"\nModel path: {path}")
    print(f'\nAdd to ~/.bill_extractor/config.json:')
    print(f'  "llm_backend": "llamacpp",')
    print(f'  "llm_model_path": "{path}"')


if __name__ == "__main__":
    main()

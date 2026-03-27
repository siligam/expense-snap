from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path.home() / ".bill_extractor"

_DEFAULT_CONFIG: dict[str, Any] = {
    "history_file": str(DEFAULT_DIR / "history.json"),
    "files_dir": str(DEFAULT_DIR / "files"),
    "ocr_url": None,
    "port": 8080,
}


@dataclass
class Config:
    history_file: Path = field(default_factory=lambda: DEFAULT_DIR / "history.json")
    files_dir: Path = field(default_factory=lambda: DEFAULT_DIR / "files")
    ocr_url: str | None = None
    port: int = 8080


def _write_default(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(_DEFAULT_CONFIG, f, indent=2)
        f.write("\n")


def _load_raw(path: Path) -> dict[str, Any]:
    ext = path.suffix.lower()
    text = path.read_text()
    if ext in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import]
            return yaml.safe_load(text) or {}
        except ImportError:
            raise RuntimeError(
                "pyyaml is required to read YAML config files. "
                "Install it with: pip install pyyaml"
            )
    return json.loads(text)


def load_config(path: Path | str | None = None) -> Config:
    """Load config from *path*, or auto-discover in ~/.bill_extractor/.

    Creates a default config.json on first run if none exists.
    """
    if path is not None:
        cfg_path = Path(path).expanduser()
    else:
        # Search for existing config
        for name in ("config.yaml", "config.yml", "config.json"):
            candidate = DEFAULT_DIR / name
            if candidate.exists():
                cfg_path = candidate
                break
        else:
            # First run — create default JSON config
            cfg_path = DEFAULT_DIR / "config.json"
            _write_default(cfg_path)

    raw = _load_raw(cfg_path)

    def _expand(key: str, raw: dict, fallback: Any) -> Any:
        val = raw.get(key, fallback)
        if isinstance(val, str):
            return Path(os.path.expanduser(val))
        return fallback if val is None else val

    return Config(
        history_file=_expand("history_file", raw, DEFAULT_DIR / "history.json"),
        files_dir=_expand("files_dir", raw, DEFAULT_DIR / "files"),
        ocr_url=raw.get("ocr_url", None),
        port=int(raw.get("port", 8080)),
    )

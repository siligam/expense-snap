from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class HistoryStore:
    """Thread-safe history store backed by a single JSON file.

    Records are kept as a list of dicts.  Keyed on ``hash`` for O(1) lookup.
    """

    def __init__(self, history_file: Path, files_dir: Path) -> None:
        self._path = Path(history_file)
        self._files_dir = Path(files_dir)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._files_dir.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write_locked([])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_locked(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def _write_locked(self, records: list[dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        tmp.replace(self._path)  # atomic on POSIX; best-effort on Windows

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read_locked())

    def get(self, hash_: str) -> dict[str, Any] | None:
        with self._lock:
            for rec in self._read_locked():
                if rec.get("hash") == hash_:
                    return rec
        return None

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace a record identified by ``record["hash"]``."""
        hash_ = record.get("hash")
        with self._lock:
            records = self._read_locked()
            for i, rec in enumerate(records):
                if rec.get("hash") == hash_:
                    records[i] = record
                    break
            else:
                records.append(record)
            self._write_locked(records)
        return record

    def delete(self, hash_: str) -> bool:
        """Delete record *hash_*.  Returns True if it existed."""
        with self._lock:
            records = self._read_locked()
            new_records = [r for r in records if r.get("hash") != hash_]
            if len(new_records) == len(records):
                return False
            self._write_locked(new_records)
        return True

    # ------------------------------------------------------------------
    # File storage
    # ------------------------------------------------------------------

    def save_file(self, filename: str, data: bytes) -> None:
        dest = self._files_dir / filename
        dest.write_bytes(data)

    def get_file_path(self, filename: str) -> Path | None:
        p = self._files_dir / filename
        return p if p.exists() else None

    def delete_file(self, filename: str) -> bool:
        p = self._files_dir / filename
        if p.exists():
            p.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # Storage info
    # ------------------------------------------------------------------

    def disk_usage(self) -> dict[str, int]:
        """Return byte sizes of history file and files directory."""
        history_bytes = self._path.stat().st_size if self._path.exists() else 0
        files_bytes = sum(
            f.stat().st_size
            for f in self._files_dir.iterdir()
            if f.is_file()
        ) if self._files_dir.exists() else 0
        return {
            "history_bytes": history_bytes,
            "files_bytes": files_bytes,
            "total_bytes": history_bytes + files_bytes,
        }

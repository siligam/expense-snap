"""Tests for bill_extractor.history — HistoryStore CRUD and thread safety."""
import threading
import pytest
from pathlib import Path

from bill_extractor.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history.json", tmp_path / "files")


def test_initial_state_empty(store):
    assert store.all() == []


def test_upsert_insert(store):
    rec = {"hash": "abc123", "filename": "receipt.jpg"}
    store.upsert(rec)
    assert len(store.all()) == 1
    assert store.get("abc123") == rec


def test_upsert_replace(store):
    store.upsert({"hash": "abc", "value": 1})
    store.upsert({"hash": "abc", "value": 2})
    assert len(store.all()) == 1
    assert store.get("abc")["value"] == 2


def test_delete_existing(store):
    store.upsert({"hash": "del1", "x": 1})
    assert store.delete("del1") is True
    assert store.get("del1") is None


def test_delete_missing(store):
    assert store.delete("nonexistent") is False


def test_get_missing(store):
    assert store.get("nope") is None


def test_multiple_records(store):
    for i in range(5):
        store.upsert({"hash": f"h{i}", "n": i})
    assert len(store.all()) == 5


def test_file_save_and_retrieve(store, tmp_path):
    store.save_file("test.jpg", b"FAKEJPEG")
    p = store.get_file_path("test.jpg")
    assert p is not None
    assert p.read_bytes() == b"FAKEJPEG"


def test_file_delete(store):
    store.save_file("del.jpg", b"data")
    assert store.delete_file("del.jpg") is True
    assert store.get_file_path("del.jpg") is None


def test_file_delete_missing(store):
    assert store.delete_file("nope.jpg") is False


def test_disk_usage(store):
    store.upsert({"hash": "x"})
    store.save_file("x.jpg", b"A" * 1000)
    usage = store.disk_usage()
    assert usage["history_bytes"] > 0
    assert usage["files_bytes"] == 1000
    assert usage["total_bytes"] == usage["history_bytes"] + 1000


def test_atomic_write_survives_concurrent_upserts(store):
    errors = []

    def worker(n):
        try:
            for i in range(10):
                store.upsert({"hash": f"t{n}_{i}", "n": n * 10 + i})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.all()) == 50

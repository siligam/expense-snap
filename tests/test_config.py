"""Tests for bill_extractor.config — config loading and defaults."""
import json
import pytest
from pathlib import Path

from bill_extractor.config import Config, load_config, DEFAULT_DIR


def test_load_config_creates_default_json(tmp_path, monkeypatch):
    import bill_extractor.config as cfg_mod
    cfg_mod.DEFAULT_DIR = tmp_path
    try:
        cfg = load_config()
        assert (tmp_path / "config.json").exists()
        assert isinstance(cfg, Config)
        assert cfg.port == 8080
        assert cfg.ocr_servers == [{"url": "local", "enabled": True}]
    finally:
        cfg_mod.DEFAULT_DIR = DEFAULT_DIR


def test_load_config_reads_json(tmp_path):
    servers = [{"url": "local", "enabled": False}, {"url": "http://gpu:8080", "enabled": True}]
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "history_file": str(tmp_path / "h.json"),
        "files_dir": str(tmp_path / "files"),
        "ocr_servers": servers,
        "port": 9090,
    }))
    cfg = load_config(cfg_file)
    assert cfg.port == 9090
    assert cfg.ocr_servers == servers
    assert cfg.history_file == tmp_path / "h.json"


def test_load_config_backward_compat_ocr_url(tmp_path):
    """Old configs with ocr_url are converted to ocr_servers."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "history_file": str(tmp_path / "h.json"),
        "files_dir": str(tmp_path / "files"),
        "ocr_url": "http://gpu:8080",
        "port": 8080,
    }))
    cfg = load_config(cfg_file)
    assert any(s["url"] == "http://gpu:8080" and s["enabled"] for s in cfg.ocr_servers)
    assert any(s["url"] == "local" and not s["enabled"] for s in cfg.ocr_servers)


def test_load_config_backward_compat_null_ocr_url(tmp_path):
    """Old configs with null ocr_url → local-only server list."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "history_file": str(tmp_path / "h.json"),
        "files_dir": str(tmp_path / "files"),
        "ocr_url": None,
        "port": 8080,
    }))
    cfg = load_config(cfg_file)
    assert cfg.ocr_servers == [{"url": "local", "enabled": True}]


def test_load_config_expands_tilde(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "history_file": "~/my_history.json",
        "files_dir": "~/my_files",
        "port": 8080,
    }))
    cfg = load_config(cfg_file)
    assert not str(cfg.history_file).startswith("~")
    assert cfg.history_file == Path.home() / "my_history.json"


def test_load_config_missing_keys_use_defaults(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}")
    cfg = load_config(cfg_file)
    assert cfg.port == 8080
    assert cfg.ocr_servers == [{"url": "local", "enabled": True}]


def test_config_data_dir_property(tmp_path):
    cfg = Config(history_file=tmp_path / "history.json", files_dir=tmp_path / "files")
    assert cfg.data_dir == tmp_path


def test_load_config_yaml_raises_without_pyyaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("port: 9000\n")
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no pyyaml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="pyyaml"):
        load_config(cfg_file)

"""config モジュールのユニットテスト。"""
from pathlib import Path

import pytest

from whisper_transcribe import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """テスト中は実際の設定ファイルに触れない。"""
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")


def test_get_set_roundtrip() -> None:
    config.set_value("language", "en")
    config.set_value("timestamps", True)
    assert config.get_value("language") == "en"
    assert config.get_bool("timestamps", False) is True


def test_defaults_when_missing() -> None:
    assert config.get_str("model_size", "large-v3") == "large-v3"
    assert config.get_bool("auto_transcribe", False) is False
    assert config.get_record_filename_format() == config.DEFAULT_RECORD_FILENAME_FORMAT
    assert config.get_recording_cache_limit() == config.DEFAULT_RECORDING_CACHE_LIMIT


def test_vault_dir_missing_path_returns_none(tmp_path: Path) -> None:
    config.set_value("vault_dir", str(tmp_path / "nonexistent"))
    assert config.get_vault_dir() is None


def test_vault_dir_valid(tmp_path: Path) -> None:
    config.set_vault_dir(tmp_path)
    assert config.get_vault_dir() == tmp_path


def test_recording_cache_limit_rejects_invalid() -> None:
    config.set_value("recording_cache_limit", -5)
    assert config.get_recording_cache_limit() == config.DEFAULT_RECORDING_CACHE_LIMIT

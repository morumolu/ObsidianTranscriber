"""アプリ設定 (~/.whisper_transcribe.json) の読み書き。"""
import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".whisper_transcribe.json"

# 録音ファイル名の strftime 形式 (例: 20260705_0343)
DEFAULT_RECORD_FILENAME_FORMAT = "%Y%m%d_%H%M"

# 録音 (中間生成物) のキャッシュ先と保持数
RECORDINGS_CACHE_DIR = Path.home() / ".whisper_transcribe" / "recordings"
DEFAULT_RECORDING_CACHE_LIMIT = 20


def load_config() -> dict[str, Any]:
    try:
        config: str = CONFIG_PATH.read_text(encoding="utf-8")
        return dict(json.loads(config)) # noqa
    except (OSError, ValueError):
        return {}


def get_value(key: str, default: Any = None) -> Any:
    return load_config().get(key, default)


def set_value(key: str, value: Any) -> None:
    config = load_config()
    config[key] = value
    try:
        CONFIG_PATH.write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def get_record_filename_format() -> str:
    fmt = get_value("record_filename_format")
    return fmt if isinstance(fmt, str) and fmt else DEFAULT_RECORD_FILENAME_FORMAT


def set_record_filename_format(fmt: str) -> None:
    set_value("record_filename_format", fmt)


def get_str(key: str, default: str) -> str:
    value = get_value(key)
    return value if isinstance(value, str) and value else default


def get_bool(key: str, default: bool) -> bool:
    value = get_value(key)
    return value if isinstance(value, bool) else default


def get_vault_dir() -> Path | None:
    """Obsidian Vault (録音の保存先) フォルダ。未設定・消失時は None。"""
    value = get_value("vault_dir")
    if isinstance(value, str) and value:
        path = Path(value)
        if path.is_dir():
            return path
    return None


def set_vault_dir(path: Path) -> None:
    set_value("vault_dir", str(path))


def get_recordings_cache_dir() -> Path:
    """録音キャッシュのディレクトリを返す (無ければ作成)。"""
    RECORDINGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return RECORDINGS_CACHE_DIR


def get_recording_cache_limit() -> int:
    value = get_value("recording_cache_limit")
    return value if isinstance(value, int) and value > 0 else DEFAULT_RECORDING_CACHE_LIMIT


def set_recording_cache_limit(limit: int) -> None:
    set_value("recording_cache_limit", limit)

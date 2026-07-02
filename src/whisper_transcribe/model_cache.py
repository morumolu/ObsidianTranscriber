from dataclasses import dataclass
from pathlib import Path

from faster_whisper.utils import _MODELS as _REPO_IDS
from huggingface_hub import scan_cache_dir
from huggingface_hub.errors import CacheNotFound

try:
    from .model_size import ModelSize
except ImportError:  # 直接スクリプト実行時のフォールバック
    from model_size import ModelSize  # type: ignore[no-redef,import-not-found]

# Whisper が扱う ModelSize に対応するリポジトリのみを管理対象にする
# (同じ HuggingFace キャッシュを共有する他アプリのモデルには触れない)
_OUR_SIZES = {m.value for m in ModelSize}
_REPO_TO_SIZE = {repo_id: size for size, repo_id in _REPO_IDS.items() if size in _OUR_SIZES}


@dataclass(frozen=True)
class CachedModel:
    model_size: str
    repo_id: str
    size_bytes: int
    size_str: str
    path: Path
    revision_hashes: tuple[str, ...]


def list_cached_models() -> list[CachedModel]:
    """Whisper がダウンロード済みのモデルをキャッシュから一覧取得する。"""
    try:
        info = scan_cache_dir()
    except CacheNotFound:
        return []

    cached = [
        CachedModel(
            model_size=_REPO_TO_SIZE[repo.repo_id],
            repo_id=repo.repo_id,
            size_bytes=repo.size_on_disk,
            size_str=repo.size_on_disk_str,
            path=Path(repo.repo_path),
            revision_hashes=tuple(rev.commit_hash for rev in repo.revisions),
        )
        for repo in info.repos
        if repo.repo_id in _REPO_TO_SIZE
    ]
    cached.sort(key=lambda c: c.size_bytes, reverse=True)
    return cached


def delete_cached_model(cached: CachedModel) -> None:
    """指定モデルのキャッシュを削除する。"""
    info = scan_cache_dir()
    strategy = info.delete_revisions(*cached.revision_hashes)
    strategy.execute()


def format_size(num_bytes: int) -> str:
    """バイト数を人間可読な文字列に整形する（例: 1.5G）。"""
    size = float(num_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}T"

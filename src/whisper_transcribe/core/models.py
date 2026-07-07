"""Whisper モデルの取得・ロードと実行デバイス (CPU/GPU) の解決。"""
import ctypes.util
import os
import sys
import threading
from functools import lru_cache
from logging import getLogger
from pathlib import Path
from typing import Callable

from .model_size import ModelSize

logger = getLogger(__name__)

# 進捗コールバック: (現在値, 総量)
ProgressCallback = Callable[[float, float], None]
# ログコールバック: 1行のメッセージ
LogCallback = Callable[[str], None]


def setup_cuda_dll_path() -> None:
    """Windows環境で、CUDA関連DLLの場所を検索パスに追加する。

    開発環境では venv 内の nvidia パッケージを、PyInstaller ビルドでは
    exe と同じフォルダの `cuda` サブフォルダ (sotto-build --gpu が生成)
    を PATH に追加する。DLL が見つかれば GPU、無ければ CPU で動作する。
    """
    if sys.platform != "win32":
        return

    if getattr(sys, "frozen", False):
        cuda_dir = Path(sys.executable).parent / "cuda"
        if cuda_dir.is_dir():
            os.environ["PATH"] = str(cuda_dir) + os.pathsep + os.environ["PATH"]
        return

    nvidia_base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_base.exists():
        return

    bin_dirs = [
        str(pkg_dir / "bin")
        for pkg_dir in nvidia_base.iterdir()
        if (pkg_dir / "bin").exists()
    ]

    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ["PATH"]


# faster_whisper (ctranslate2) を使う前に DLL 検索パスを整えておく
setup_cuda_dll_path()

from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.utils import _MODELS, download_model  # noqa: E402
from huggingface_hub import snapshot_download  # noqa: E402


def model_name(model_size: ModelSize | str) -> str:
    """ModelSize / str のどちらでも Whisper が受け取れる文字列に正規化する。"""
    return model_size.value if isinstance(model_size, ModelSize) else str(model_size)


@lru_cache(maxsize=1)
def cuda_runtime_available() -> bool:
    """CUDA ランタイム DLL (cublas / cuDNN) が見つかるかを確認する。

    ctranslate2 は実行時に PATH から DLL をロードするため、
    venv の nvidia パッケージ・システムの CUDA Toolkit いずれでも
    PATH 上に DLL があれば True になる。
    """
    return all(
        ctypes.util.find_library(dll) is not None
        for dll in ("cublas64_12", "cudnn_ops64_9")
    )


def resolve_device(device: str) -> str:
    """device 指定を実行環境に応じて解決する。

    ctranslate2 の "auto" は GPU ドライバの有無だけで CUDA を選ぶため、
    CUDA ランタイム DLL が無い環境 (CUDA非同梱の exe など) では実行時に失敗する。
    DLL がロードできない場合は CPU に固定する。
    """
    if device == "auto" and not cuda_runtime_available():
        return "cpu"
    return device


_MODEL_FILE_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def _repo_cache_dir(repo_id: str) -> Path:
    from huggingface_hub.constants import HF_HUB_CACHE

    return Path(HF_HUB_CACHE) / ("models--" + repo_id.replace("/", "--"))


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _repo_total_size(repo_id: str) -> int:
    """ダウンロード対象ファイルの合計サイズを HF API から取得する (失敗時 0)。"""
    import fnmatch

    from huggingface_hub import HfApi

    try:
        info = HfApi().model_info(repo_id, files_metadata=True)
        return sum(
            s.size or 0
            for s in (info.siblings or [])
            if any(fnmatch.fnmatch(s.rfilename, p) for p in _MODEL_FILE_PATTERNS)
        )
    except Exception:  # noqa: BLE001 - 進捗表示できないだけでダウンロードは続行可能
        return 0


def ensure_model_downloaded(
        model_size: ModelSize | str,
        log: LogCallback | None = None,
        download_progress: ProgressCallback | None = None,
) -> None:
    """モデルが未キャッシュならダウンロードする。進捗は download_progress (done, total バイト) に通知。

    hf hub はファイル単位の進捗フックを公開していないため、キャッシュフォルダの
    サイズを別スレッドでポーリングして進捗を概算する。
    """
    name = model_name(model_size)
    try:
        download_model(name, local_files_only=True)
        return  # キャッシュ済み
    except Exception:  # noqa: BLE001 - 未キャッシュならダウンロードに進む
        pass

    if log:
        log(f"Downloading model: {name}")
    repo_id = _MODELS.get(name, name)

    stop_polling = threading.Event()
    if download_progress is not None:
        # xet 経由だとバイト列が別のチャンクキャッシュに書かれ、フォルダサイズの
        # ポーリングで進捗を測れないため、通常の HTTP ダウンロードに切り替える
        import huggingface_hub.constants as hf_constants

        hf_constants.HF_HUB_DISABLE_XET = True

        total = _repo_total_size(repo_id)
        cache_dir = _repo_cache_dir(repo_id)
        base = _dir_size(cache_dir)

        def poll() -> None:
            while total and not stop_polling.wait(0.5):
                done = max(0, _dir_size(cache_dir) - base)
                download_progress(float(min(done, total)), float(total))

        threading.Thread(target=poll, daemon=True).start()

    try:
        snapshot_download(repo_id, allow_patterns=_MODEL_FILE_PATTERNS)
    finally:
        stop_polling.set()


def load_model(
        model_size: ModelSize | str,
        device: str = "auto",
        compute_type: str = "auto",
) -> WhisperModel:
    """Whisper モデルを読み込む。

    device / compute_type は既定で "auto"。CUDA が利用可能なら GPU + float16、
    無ければ CPU + int8 が自動選択される（ctranslate2 の auto 解決）。
    """
    device = resolve_device(device)
    return WhisperModel(model_name(model_size), device=device, compute_type=compute_type)

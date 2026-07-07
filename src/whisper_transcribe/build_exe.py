"""Windows用exeをビルドするエントリポイント (`uv run sotto-build`)。

sotto.spec は相対パス (launcher_gui.py, src/...) を使っているため、
呼び出し元のカレントディレクトリに依存しないようリポジトリルートへ移動してから実行する。

`--gpu` を付けると、venv 内の NVIDIA CUDA DLL を dist/SOTTO/cuda/ にコピーする。
exe は起動時にこのフォルダを検出して GPU で動作する (無ければ CPU)。
"""
import os
import shutil
import sys
from pathlib import Path

from PyInstaller.__main__ import run as pyinstaller_run

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = PROJECT_ROOT / "dist" / "SOTTO"


def copy_cuda_dlls(target: Path) -> None:
    """venv の nvidia パッケージから CUDA DLL 一式を exe 横の cuda フォルダへコピーする。"""
    nvidia_base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    dlls = sorted(nvidia_base.glob("*/bin/*.dll")) if nvidia_base.exists() else []
    if not dlls:
        print(f"error: CUDA DLLs not found under {nvidia_base}", file=sys.stderr)
        raise SystemExit(1)

    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for dll in dlls:
        shutil.copy2(dll, target / dll.name)
        total += dll.stat().st_size
    print(f"Copied {len(dlls)} CUDA DLLs ({total / 1024 / 1024 / 1024:.2f} GB) to {target}")


def main() -> None:
    os.chdir(PROJECT_ROOT)
    gpu = "--gpu" in sys.argv[1:]
    pyinstaller_run(["sotto.spec", "--noconfirm"])
    if gpu:
        copy_cuda_dlls(DIST_DIR / "cuda")


if __name__ == "__main__":
    main()

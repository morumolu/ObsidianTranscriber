"""Windows用exeをビルドするエントリポイント (`uv run wisper-build`)。

wisper.spec は相対パス (launcher_gui.py, src/...) を使っているため、
呼び出し元のカレントディレクトリに依存しないようリポジトリルートへ移動してから実行する。
"""
import os
from pathlib import Path

from PyInstaller.__main__ import run as pyinstaller_run

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    os.chdir(PROJECT_ROOT)
    pyinstaller_run(["wisper.spec", "--noconfirm"])


if __name__ == "__main__":
    main()

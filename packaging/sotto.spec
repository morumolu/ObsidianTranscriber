# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: SOTTO GUI (onedir, windowed, CUDA非同梱/CPU動作)。

ビルド:
    uv run sotto-build  (GPU版: uv run sotto-build --gpu)
生成物:
    dist/SOTTO/SOTTO.exe  (フォルダごと配布)
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

# spec は packaging/ 配下にあるため、リポジトリルートを基準にパスを解決する
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "src", "whisper_transcribe", "ui", "assets", "icon.ico")

datas = []
binaries = []
hiddenimports = []

# アプリアイコン (ウィンドウ表示用に _internal へ同梱)
datas += [(ICON, "whisper_transcribe/ui/assets")]

# ドラッグ&ドロップ (tkdnd バイナリ) + ttkbootstrap テーマ
for mod in ("tkinterdnd2", "ttkbootstrap"):
    d, b, h = collect_all(mod)
    datas += d
    binaries += b
    hiddenimports += h

# faster-whisper / PyAV / onnxruntime / 録音 (PortAudio, libsndfile) のデータ・ネイティブ依存
for mod in ("faster_whisper", "av", "onnxruntime", "sounddevice", "soundfile"):
    d, b, h = collect_all(mod)
    datas += d
    binaries += b
    hiddenimports += h

# ctranslate2 は DLL 本体のみ収集 (CUDA 版 DLL は含まれない=CPUで動作)
binaries += collect_dynamic_libs("ctranslate2")
hiddenimports += ["ctranslate2"]

# CUDA 巨大 DLL 群を除外してサイズを抑える
excludes = [
    "nvidia",
    "torch",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
]

a = Analysis(
    [os.path.join(SPECPATH, "launcher_gui.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SOTTO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUIアプリ。ビルド不具合の調査時は True にすると stdout/stderr が見える
    disable_windowed_traceback=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SOTTO",
)

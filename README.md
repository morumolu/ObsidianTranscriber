# SOTTO - Speech to Transcribed Obsidian

ローカルで音声を録音・文字起こしし、Obsidian向けMarkdownとして保存するツール。
faster-whisper 使用。*sotto voce*（ささやき声で）と日本語の「そっと」から。

Administrator mode

```pwsh
choco install ffmpeg
```

## 実行

```pwsh
uv run sotto -i input.wav      # CLI
uv run sotto-gui               # GUI
```

## Windows exe ビルド

```pwsh
uv run sotto-build
```

生成物: `dist/SOTTO/SOTTO.exe`（フォルダごと配布、onedir形式）。
CUDA関連DLLは同梱していません。実行時にCUDAランタイムDLLが見つかればGPU、
見つからなければCPUで自動的に動作します。

## exe で GPU を使う

### 方法1: GPU版ビルド（推奨）

```pwsh
uv run sotto-build --gpu
```

venv内のCUDA DLL一式が `dist/SOTTO/cuda/` にコピーされます（約1.9GB増）。
exeは起動時にこのフォルダを自動検出してGPUで動作します。実行マシンにはNVIDIAドライバのみ必要です。
`cuda` フォルダを削除すればCPU動作に戻ります（exe本体は共通）。

### 方法2: システムにCUDAをインストール

1. NVIDIAドライバ（最新推奨）
2. CUDA Toolkit 12.x（`cublas64_12.dll` が含まれる）
3. cuDNN 9（`cudnn_ops64_9.dll` 等が含まれる）
4. 2と3のDLLがあるフォルダを環境変数 PATH に追加

いずれの場合も、DLLが見つからなければ自動的にCPUで動作します。
どちらで動いているかは処理ログの `Loading model: ... (device=...)` で確認できます（cpu=CPU動作、auto=GPU動作）。

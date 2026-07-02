# Whisper Transcription Tool

Administrator mode

```pwsh
choco install ffmpeg
```

## 実行

```pwsh
uv run whisper-transcribe -i input.wav      # CLI
uv run whisper-transcribe-gui               # GUI
```

## Windows exe ビルド

```pwsh
uv run whisper-transcribe-build
```

生成物: `dist/Whisper/Whisper.exe`（フォルダごと配布、onedir形式）。
CUDA関連DLLは同梱していません。実行時にCUDAランタイムDLLが見つかればGPU、
見つからなければCPUで自動的に動作します。

## exe で GPU を使う

実行マシンに以下をセットアップすると、exeが起動時に自動検出してGPUを使用します。

1. NVIDIAドライバ（最新推奨）
2. CUDA Toolkit 12.x（`cublas64_12.dll` が含まれる）
3. cuDNN 9（`cudnn_ops64_9.dll` 等が含まれる）
4. 2と3のDLLがあるフォルダ（例: `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin` と cuDNN の `bin`）を環境変数 PATH に追加

PATH に DLL が見つからない場合は自動的にCPUで動作するため、GPUなし環境でも同じexeがそのまま使えます。
どちらで動いているかは処理ログの `Loading model: ... (device=...)` で確認できます（cpu=CPU動作、auto=GPU動作）。
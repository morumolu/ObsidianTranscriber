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
CUDA関連DLLは同梱せず、CPUで動作します。
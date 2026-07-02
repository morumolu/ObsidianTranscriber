# Wisper

Administrator mode

```pwsh
choco install ffmpeg
```

## 実行

```pwsh
uv run wisper -i input.wav      # CLI
uv run wisper-gui               # GUI
```

## Windows exe ビルド

```pwsh
uv run wisper-build
```

生成物: `dist/Wisper/Wisper.exe`（フォルダごと配布、onedir形式）。
CUDA関連DLLは同梱せず、CPUで動作します。
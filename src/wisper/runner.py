import os
import sys
import logging
from logging import getLogger, basicConfig
from pathlib import Path
from datetime import datetime
from typing import Annotated, Optional, Callable
from zoneinfo import ZoneInfo

from faster_whisper.transcribe import Segment

try:
    from .model_size import ModelSize
except ImportError:  # 直接スクリプト実行時のフォールバック
    from model_size import ModelSize


def setup_cuda_dll_path() -> None:
    """Windows環境で、venv内のNVIDIA CUDA関連DLLを検索パスに追加する。"""
    if sys.platform != "win32":
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


setup_cuda_dll_path()

import typer
from faster_whisper import WhisperModel

logger = getLogger(__name__)
basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = typer.Typer()

SAMPLE_FILE = Path(__file__).parent.parent.parent / "assets" / "sample.wav"

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}

INPUT_FILE_ARG = Annotated[
    str, typer.Option("--input", "-i", help="Path to the audio file to transcribe")
]
OUTPUT_FILE_ARG = Annotated[
    Optional[str],
    typer.Option("--output", "-o",
                 help="Path to save the Markdown output (default: same name as input, .md extension)"),
]
MODEL_SIZE_ARG = Annotated[
    ModelSize, typer.Option("--model", "-m", help="Whisper model size")
]
LANGUAGE_ARG = Annotated[
    str, typer.Option("--language", "-l", help="Audio language code")
]
TIMESTAMP_ARG = Annotated[
    bool, typer.Option("--timestamps", "-t", help="Include per-segment timestamps in output")
]
DEBUG_ARG = Annotated[
    bool, typer.Option("--debug", "-d", help="Enable debug logging")
]

TZ: str = "Asia/Tokyo"

SEGMENT_SEPARATOR: str = "\n\n"

# 進捗コールバック: (現在の処理済み秒, 総秒数)
ProgressCallback = Callable[[float, float], None]
# ログコールバック: 1行のメッセージ
LogCallback = Callable[[str], None]


def model_name(model_size) -> str:
    """ModelSize / str のどちらでも Whisper が受け取れる文字列に正規化する。"""
    return model_size.value if isinstance(model_size, ModelSize) else str(model_size)


def load_model(model_size, device: str = "auto", compute_type: str = "auto") -> WhisperModel:
    """Whisper モデルを読み込む。

    device / compute_type は既定で "auto"。CUDA が利用可能なら GPU + float16、
    無ければ CPU + int8 が自動選択される（ctranslate2 の auto 解決）。
    """
    return WhisperModel(model_name(model_size), device=device, compute_type=compute_type)


def transcribe_file(
        input_path: Path,
        output_path: Path,
        model_size=ModelSize.large_v3,
        language: str = "ja",
        timestamps: bool = False,
        progress: Optional[ProgressCallback] = None,
        log: Optional[LogCallback] = None,
        model: Optional[WhisperModel] = None,
        device: str = "auto",
        compute_type: str = "auto",
) -> Path:
    """音声ファイルを文字起こしし、Obsidian向けMarkdownとして保存する中核処理。

    CLI と GUI の双方から呼び出す。progress / log は任意のコールバック。
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    validate_input_file(input_path)
    validate_output_path(output_path)

    def emit(msg: str) -> None:
        logger.info(msg)
        if log:
            log(msg)

    emit(f"Loading model: {model_name(model_size)} (device={device}, compute={compute_type})")
    if model is None:
        model = load_model(model_size, device=device, compute_type=compute_type)

    emit(f"Transcribing: {input_path.name}")
    segments, info = model.transcribe(str(input_path), language=language)

    total = float(info.duration or 0.0)
    emit(f"Duration: {total:.1f}s / detected language: {info.language}")

    collected: list[Segment] = []
    for segment in segments:
        text = segment.text.strip()
        emit(f"[{segment.start:.2f}s - {segment.end:.2f}s] {text}")
        collected.append(segment)
        if progress and total:
            progress(min(segment.end, total), total)
    if progress and total:
        progress(total, total)

    now = datetime.now(tz=ZoneInfo(TZ))
    frontmatter = (
        "---\n"
        f"source: audio-transcription\n"
        f"source_file: {input_path.name}\n"
        f"model: {model_name(model_size)}\n"
        f"language: {language}\n"
        f"created: {now.strftime('%Y-%m-%d %H:%M')}\n"
        "verified: false\n"
        "---\n\n"
    )

    logger.debug("%s", frontmatter)

    full_text = SEGMENT_SEPARATOR.join(seg.text.strip() for seg in collected)

    body = f"# {input_path.stem}\n\n{full_text}\n"

    if timestamps:
        body += "\n## Segments\n\n"
        for seg in collected:
            body += f"- `{seg.start:.2f}s - {seg.end:.2f}s` {seg.text.strip()}\n"

    output_path.write_text(frontmatter + body, encoding="utf-8")
    emit(f"Saved to: {output_path}")
    return output_path


@app.command()
def transcribe(
        input_file: INPUT_FILE_ARG = str(SAMPLE_FILE),
        output_file: OUTPUT_FILE_ARG = None,
        model_size: MODEL_SIZE_ARG = ModelSize.large_v3,
        language: LANGUAGE_ARG = "ja",
        timestamps: TIMESTAMP_ARG = False,
        is_debug: DEBUG_ARG = False
):
    """Transcribe an audio file and save as an Obsidian-friendly Markdown note."""
    if is_debug:
        logger.setLevel(logging.DEBUG)

    input_path = Path(input_file)
    output_path = Path(output_file) if output_file else input_path.with_suffix(".md")

    transcribe_file(
        input_path,
        output_path,
        model_size=model_size,
        language=language,
        timestamps=timestamps,
        log=typer.echo,
    )


def validate_input_file(input_path: Path) -> None:
    """入力ファイルの存在・形式を検証し、不正なら即座にエラー終了する。"""
    if not input_path.exists():
        typer.secho(f"Error: Input file not found: {input_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if not input_path.is_file():
        typer.secho(f"Error: Input path is not a file: {input_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        typer.secho(
            f"Error: Unsupported file extension '{input_path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)


def validate_output_path(output_path: Path) -> None:
    """出力先の親フォルダが存在するか、書き込み可能かを検証する。"""
    parent = output_path.parent

    if not parent.exists():
        typer.secho(f"Error: Output directory does not exist: {parent}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if output_path.exists() and not os.access(output_path, os.W_OK):
        typer.secho(f"Error: Output file is not writable: {output_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

import ctypes.util
import logging
import os
import sys
import threading
from datetime import datetime
from functools import lru_cache
from logging import basicConfig, getLogger
from pathlib import Path
from typing import Annotated, Callable
from zoneinfo import ZoneInfo

from .model_size import ModelSize


class TranscriptionCancelled(Exception):
    """ユーザー操作による文字起こしの中断。"""


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
from faster_whisper.transcribe import Segment

logger = getLogger(__name__)
basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = typer.Typer()

SAMPLE_FILE = Path(__file__).parent.parent.parent / "assets" / "sample.wav"

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}

INPUT_FILE_ARG = Annotated[
    str, typer.Option("--input", "-i", help="Path to the audio file to transcribe")
]
OUTPUT_FILE_ARG = Annotated[
    str | None,
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

SEGMENT_SEPARATOR: str = "\n"

# 進捗コールバック: (現在の処理済み秒, 総秒数)
ProgressCallback = Callable[[float, float], None]
# ログコールバック: 1行のメッセージ
LogCallback = Callable[[str], None]


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


def transcribe_file(
        input_path: Path,
        output_path: Path,
        model_size: ModelSize | str = ModelSize.large_v3,
        language: str = "ja",
        timestamps: bool = False,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
        model: WhisperModel | None = None,
        device: str = "auto",
        compute_type: str = "auto",
        cancel_event: threading.Event | None = None,
        max_duration: float | None = None,
        save_output: bool = True,
) -> Path | None:
    """音声ファイルを文字起こしし、Obsidian向けMarkdownとして保存する中核処理。

    CLI と GUI の双方から呼び出す。progress / log は任意のコールバック。
    入力・出力が不正な場合は FileNotFoundError / ValueError を送出する。
    cancel_event がセットされると TranscriptionCancelled を送出する（ファイルは保存しない）。
    max_duration を指定すると先頭 N 秒で打ち切る。save_output=False で保存をスキップし None を返す。
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    validate_input_file(input_path)
    validate_output_path(output_path)

    def emit(msg: str) -> None:
        logger.info(msg)
        if log:
            log(msg)

    device = resolve_device(device)
    emit(f"Loading model: {model_name(model_size)} (device={device}, compute={compute_type})")
    if model is None:
        model = load_model(model_size, device=device, compute_type=compute_type)

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise TranscriptionCancelled()

    check_cancelled()
    emit(f"Transcribing: {input_path.name}")
    segments, info = model.transcribe(str(input_path), language=language)

    total = float(info.duration or 0.0)
    if max_duration is not None:
        total = min(total, max_duration)
        emit(f"Test mode: first {max_duration:.0f}s only")
    emit(f"Duration: {total:.1f}s / detected language: {info.language}")

    collected: list[Segment] = []
    for segment in segments:
        check_cancelled()
        text = segment.text.strip()
        emit(f"[{segment.start:.2f}s - {segment.end:.2f}s] {text}")
        collected.append(segment)
        if progress and total:
            progress(min(segment.end, total), total)
        if max_duration is not None and segment.end >= max_duration:
            break
    if progress and total:
        progress(total, total)

    if not save_output:
        emit("Test transcription finished (not saved).")
        return None

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
        is_debug: DEBUG_ARG = False,
) -> None:
    """Transcribe an audio file and save as an Obsidian-friendly Markdown note."""
    if is_debug:
        logger.setLevel(logging.DEBUG)

    input_path = Path(input_file)
    output_path = Path(output_file) if output_file else input_path.with_suffix(".md")

    try:
        transcribe_file(
            input_path,
            output_path,
            model_size=model_size,
            language=language,
            timestamps=timestamps,
            log=typer.echo,
        )
    except (OSError, ValueError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def validate_input_file(input_path: Path) -> None:
    """入力ファイルの存在・形式を検証し、不正なら例外を送出する。"""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_path}")

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{input_path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def validate_output_path(output_path: Path) -> None:
    """出力先の親フォルダが存在するか、書き込み可能かを検証する。"""
    parent = output_path.parent

    if not parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {parent}")

    if output_path.exists() and not os.access(output_path, os.W_OK):
        raise ValueError(f"Output file is not writable: {output_path}")


if __name__ == "__main__":
    app()

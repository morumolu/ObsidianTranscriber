"""音声ファイルを Obsidian 向け Markdown に文字起こしする中核処理。"""
import logging
import os
import threading
from datetime import datetime
from logging import basicConfig, getLogger
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import (
    LogCallback,
    ProgressCallback,
    WhisperModel,
    ensure_model_downloaded,
    load_model,
    model_name,
    resolve_device,
)
from .model_size import ModelSize

logger = getLogger(__name__)
basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}

TZ: str = "Asia/Tokyo"

SEGMENT_SEPARATOR: str = "\n"


class TranscriptionCancelled(Exception):
    """ユーザー操作による文字起こしの中断。"""


def transcribe_to_markdown(
        input_path: Path,
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
        download_progress: ProgressCallback | None = None,
) -> str:
    """音声ファイルを文字起こしし、Obsidian向けMarkdown文字列を返す。

    progress / log / download_progress は任意のコールバック。
    入力が不正な場合は FileNotFoundError / ValueError を送出する。
    cancel_event がセットされると TranscriptionCancelled を送出する。
    max_duration を指定すると先頭 N 秒で打ち切る。
    """
    input_path = Path(input_path)
    validate_input_file(input_path)

    def emit(msg: str) -> None:
        logger.info(msg)
        if log:
            log(msg)

    device = resolve_device(device)
    if model is None:
        ensure_model_downloaded(model_size, log=emit, download_progress=download_progress)
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

    collected = []
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

    return frontmatter + body


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
        download_progress: ProgressCallback | None = None,
) -> Path | None:
    """文字起こしして Markdown ファイルに保存する (transcribe_to_markdown + 書き出し)。

    save_output=False で保存をスキップし None を返す。
    """
    output_path = Path(output_path)
    validate_output_path(output_path)

    def emit(msg: str) -> None:
        logger.info(msg)
        if log:
            log(msg)

    content = transcribe_to_markdown(
        input_path,
        model_size=model_size,
        language=language,
        timestamps=timestamps,
        progress=progress,
        log=log,
        model=model,
        device=device,
        compute_type=compute_type,
        cancel_event=cancel_event,
        max_duration=max_duration,
        download_progress=download_progress,
    )

    if not save_output:
        emit("Test transcription finished (not saved).")
        return None

    output_path.write_text(content, encoding="utf-8")
    emit(f"Saved to: {output_path}")
    return output_path


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

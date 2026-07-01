import os
import sys
from pathlib import Path
from datetime import datetime


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

app = typer.Typer()

DEFAULT_FILE = Path(__file__).parent.parent.parent / "assets" / "sample.wav"

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}


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


@app.command()
def transcribe(
        input_file: str = typer.Option(..., "--input", "-i", help="Path to the audio file to transcribe"),
        output_file: str = typer.Option(None, "--output", "-o",
                                        help="Path to save the Markdown output (default: same name as input, .md extension)"),
        model_size: str = typer.Option("large-v3", "--model", "-m", help="Whisper model size"),
        language: str = typer.Option("ja", "--language", "-l", help="Audio language code"),
        timestamps: bool = typer.Option(False, "--timestamps", "-t", help="Include per-segment timestamps in output"),
):
    """Transcribe an audio file and save as an Obsidian-friendly Markdown note."""
    input_path = Path(input_file)
    validate_input_file(input_path)

    output_path = Path(output_file) if output_file else input_path.with_suffix(".md")
    validate_output_path(output_path)

    typer.echo(f"Loading model: {model_size}")
    model = WhisperModel(model_size, device="cuda", compute_type="float16")

    typer.echo(f"Transcribing: {input_file}")
    segments, info = model.transcribe(input_file, language=language)
    segments = list(segments)
    full_text = " ".join(seg.text.strip() for seg in segments)

    now = datetime.now()
    frontmatter = (
        "---\n"
        f"source: audio-transcription\n"
        f"source_file: {input_path.name}\n"
        f"model: {model_size}\n"
        f"language: {language}\n"
        f"created: {now.strftime('%Y-%m-%d %H:%M')}\n"
        "verified: false\n"
        "---\n\n"
    )

    body = f"# {input_path.stem}\n\n{full_text}\n"

    if timestamps:
        body += "\n## Segments\n\n"
        for seg in segments:
            body += f"- `{seg.start:.2f}s - {seg.end:.2f}s` {seg.text.strip()}\n"

    output_path.write_text(frontmatter + body, encoding="utf-8")
    typer.echo(f"Saved to: {output_path}")


if __name__ == "__main__":
    app()


@app.command()
def transcribe(
        input_file: str = typer.Option(DEFAULT_FILE, "--input", "-i", help="Path to the audio file to transcribe"),
        model_size: str = typer.Option("large-v3", "--model", "-m", help="Whisper model size"),
        language: str = typer.Option("ja", "--language", "-l", help="Audio language code"),
):
    """Transcribe an audio file using faster-whisper."""

    if not Path(input_file).exists():
        typer.echo(f"Input file does not exist: {input_file}")
        sys.exit(1)

    typer.echo(f"Loading model: {model_size}")
    model = WhisperModel(model_size, device="cuda", compute_type="float16")

    typer.echo(f"Transcribing: {input_file}")
    segments, info = model.transcribe(input_file, language=language)

    for segment in segments:
        typer.echo(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")


if __name__ == "__main__":
    app()

"""typer ベースの CLI (`uv run sotto`)。"""
import logging
from pathlib import Path
from typing import Annotated

import typer

from .core.model_size import ModelSize
from .core.transcribe import logger, transcribe_file

app = typer.Typer()

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "assets" / "sample.wav"

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


if __name__ == "__main__":
    app()
